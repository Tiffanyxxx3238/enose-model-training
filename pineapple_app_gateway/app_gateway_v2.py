"""
app_gateway_v2.py
放在 Raspberry Pi 的 ~/pineapple_app_gateway/ 資料夾

API:
  GET  /health
  POST /calibrate
  POST /scan
  GET  /status
  POST /scan_records
"""

import glob
import hashlib
import json
import pickle
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import serial
from flask import Flask, jsonify, request


# ─────────────────────────────────────────
# 路徑設定
# ─────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

# 你的專案如果是 pineapple_final，請用這個
PINEAPPLE_DIR = BASE_DIR.parent / "pineapple_final"

# 如果你之後改回 ~/pineapple，就改成這行：
# PINEAPPLE_DIR = BASE_DIR.parent / "pineapple"

MODEL_PATH = PINEAPPLE_DIR / "deploy_student.pkl"
FEATURES_PATH = PINEAPPLE_DIR / "feature_columns.json"
META_PATH = PINEAPPLE_DIR / "deploy_meta.json"
AIR_BASE_PATH = PINEAPPLE_DIR / "air_base.json"
RECORDS_PATH = BASE_DIR / "scan_records.json"


# ─────────────────────────────────────────
# 常數
# ─────────────────────────────────────────
WINDOW = 30
BAUD = 115200

# 多窗口投票：取最後 WINDOW + (N_WINDOWS-1)*WINDOW_STEP 筆，切成 N 個 30 筆窗口
# 每個窗口各自推論，平均機率後再決定階段（1 Hz 下約 50 秒）
N_WINDOWS = 3
WINDOW_STEP = 10
SCAN_ROWS = WINDOW + (N_WINDOWS - 1) * WINDOW_STEP

# 後處理模式：
#   "raw"    = 只用模型機率（預設）
#   "legacy" = 舊版初熟／過熟修正規則（門檻是依舊版未正規化的比值調出來的，僅供對照）
POSTPROCESS_MODE = "raw"

# 訓練資料為 1 Hz（pineapple_sample_collection.ino：SAMPLE_INTERVAL_MS = 1000）
# 實際取樣間隔中位數超出此範圍時，窗口就不等於訓練時的 30 秒
EXPECTED_INTERVAL_SEC = 1.0
INTERVAL_TOLERANCE_SEC = 0.2

# 開始取樣時用來描述感測器初始狀態的筆數（只記錄，不做判斷）
ONSET_ROWS = 5

GAS_SENSORS = ["MQ2", "MQ3", "MQ9", "MQ135", "TGS2602"]
BME_KEYS = ["Temp_C", "Humidity_pct", "Pressure_hPa"]
CALIBRATION_KEYS = GAS_SENSORS + BME_KEYS

STAGE_ZH = {
    0: "未熟",
    1: "初熟",
    2: "成熟",
    3: "過熟",
}

STAGE_EN = {
    0: "unripe",
    1: "transition",
    2: "ripe",
    3: "overripe",
}

SUGGESTION = {
    0: "建議再等待 3-5 天，鳳梨尚未成熟。",
    1: "建議再等 1-2 天，風味會更佳。",
    2: "立即食用，現在風味最佳！",
    3: "請盡快食用，避免繼續過熟。",
}


# ─────────────────────────────────────────
# 全域狀態
# ─────────────────────────────────────────
_lock = threading.Lock()
_state = {
    "status": "idle",
    "progress": 0,
    "result": None,
    "error": None,
    "scan_id": None,
}


def _set_state(**kwargs):
    with _lock:
        _state.update(kwargs)


def _get_state():
    with _lock:
        return dict(_state)


# ─────────────────────────────────────────
# 模型快取
# ─────────────────────────────────────────
_model = None
_features = None
_meta = None
_model_sha256 = None
_last_scan_end = None


def _load_model():
    global _model, _features, _meta, _model_sha256

    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"模型檔案不存在：{MODEL_PATH}")

    if not FEATURES_PATH.exists():
        raise FileNotFoundError(f"特徵欄位不存在：{FEATURES_PATH}")

    _model_sha256 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()

    with open(MODEL_PATH, "rb") as f:
        _model = pickle.load(f)

    with open(FEATURES_PATH, "r", encoding="utf-8") as f:
        _features = json.load(f)

    n_model = getattr(_model, "n_features_in_", None)
    if n_model is not None and n_model != len(_features):
        raise ValueError(
            f"模型需要 {n_model} 個特徵，但 feature_columns.json 有 {len(_features)} 個，"
            "請確認兩者來自同一個部署包"
        )

    if META_PATH.exists():
        with open(META_PATH, "r", encoding="utf-8") as f:
            _meta = json.load(f)
    else:
        _meta = {}

    print(f"[Model] 載入完成，特徵數：{len(_features)}，SHA-256：{_model_sha256}")


# ─────────────────────────────────────────
# 工具函式
# ─────────────────────────────────────────
def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        v = float(value)
        if not np.isfinite(v):
            return default
        return v
    except Exception:
        return default


def _read_arduino_row(row):
    parsed = {
        "timestamp_ms": _safe_float(row.get("timestamp_ms")),
        "MQ2": _safe_float(row.get("MQ2_raw")),
        "MQ3": _safe_float(row.get("MQ3_raw")),
        "MQ9": _safe_float(row.get("MQ9_raw")),
        "MQ135": _safe_float(row.get("MQ135_raw")),
        "TGS2602": _safe_float(row.get("TGS2602_raw")),
        "Temp_C": _safe_float(row.get("Temp_C")),
        "Humidity_pct": _safe_float(row.get("Humidity_pct")),
        "Pressure_hPa": _safe_float(row.get("Pressure_hPa")),
    }

    for key in GAS_SENSORS:
        if parsed[key] is None:
            return None

    return parsed


def _get_arduino_port():
    return "COM5"


def _open_serial_and_wait_header():
    port = _get_arduino_port()

    if not port:
        raise RuntimeError("找不到 Arduino，請確認 USB 連接")

    print(f"[Serial] 使用 port：{port}")

    ser = serial.Serial(port, BAUD, timeout=1)
    time.sleep(2)
#    ser.reset_input_buffer()

    header = None
    deadline = time.time() + 15

    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="ignore").strip()

        if line.startswith("timestamp_ms,"):
            header = [x.strip() for x in line.split(",")]
            break

    if header is None:
        ser.close()
        raise RuntimeError("等不到 Arduino CSV header，請確認 use_this.ino 已燒錄")

    return ser, header, port


def _safe_ratio(a, b):
    return float(a) / (float(b) + 1e-9)


def _safe_corr(x, y):
    if len(x) < 2 or len(y) < 2:
        return 0.0
    try:
        c = np.corrcoef(x, y)[0, 1]
        return float(c) if np.isfinite(c) else 0.0
    except Exception:
        return 0.0


def _safe_slope(x):
    if len(x) < 2:
        return 0.0
    try:
        return float(np.polyfit(range(len(x)), x, 1)[0])
    except Exception:
        return 0.0


def _safe_mean_diff(x):
    if len(x) < 2:
        return 0.0
    try:
        d = np.diff(x)
        return float(np.mean(d)) if len(d) > 0 else 0.0
    except Exception:
        return 0.0


def _safe_auc(x):
    try:
        return float(np.trapz(x))
    except Exception:
        return 0.0


def _base_value(air, sensor_name):
    v = air.get(sensor_name, 1.0)
    if v is None or not np.isfinite(v) or v == 0:
        return 1.0
    return float(v)


def _validate_air_base(air):
    # 推論前檢查：任何一個氣體感測器基準無效就不推論，避免 _base_value 默默改用 1.0
    problems = []
    for s in GAS_SENSORS:
        v = _safe_float(air.get(s))
        if v is None:
            problems.append(f"{s} 缺少基準值")
        elif not (10 <= v <= 1000):
            # 與 use_this.ino 的 isValidMQRaw 範圍一致
            problems.append(f"{s} 基準值 {v:.1f} 超出 10～1000")
    return problems


def _sampling_quality(rows):
    ts = [r["timestamp_ms"] for r in rows if r.get("timestamp_ms") is not None]
    if len(ts) < 2:
        return {"status": "unknown", "median_interval_sec": None, "span_sec": None}

    intervals = np.diff(ts) / 1000.0
    median_interval = float(np.median(intervals))

    if np.any(intervals <= 0):
        # timestamp 倒退通常代表 Arduino 在取樣途中重啟
        status = "timestamp_reset"
    elif abs(median_interval - EXPECTED_INTERVAL_SEC) > INTERVAL_TOLERANCE_SEC:
        status = "interval_abnormal"
    else:
        status = "ok"

    return {
        "status": status,
        "median_interval_sec": round(median_interval, 4),
        "max_interval_sec": round(float(np.max(intervals)), 4),
        "span_sec": round((ts[-1] - ts[0]) / 1000.0, 3),
    }


def _onset_state(rows, air):
    # 取樣開頭幾筆的相對基準值與斜率，用來累積「感測器是否已恢復」的實測資料
    head = rows[:ONSET_ROWS]
    return {
        s: {
            "mean_norm": round(float(np.mean([r[s] for r in head]) / _base_value(air, s)), 5),
            "slope": round(_safe_slope([r[s] for r in head]), 5),
        }
        for s in GAS_SENSORS
    }


def _build_features(rows, air):
    data = {
        s: np.array([r[s] for r in rows], dtype=float)
        for s in GAS_SENSORS
    }

    feat = {}

    # 比值特徵必須和訓練一致：先各自除以空氣基準，再相除
    # （訓練端 add_cross_ratio_features：{s1}_mean_norm / ({s2}_mean_norm + 1e-9)）
    mean_norm = {
        s: np.mean(data[s]) / _base_value(air, s)
        for s in GAS_SENSORS
    }
    feat["MQ2_MQ3_ratio"] = _safe_ratio(mean_norm["MQ2"], mean_norm["MQ3"])
    feat["MQ3_MQ135_ratio"] = _safe_ratio(mean_norm["MQ3"], mean_norm["MQ135"])
    feat["MQ3_TGS2602_ratio"] = _safe_ratio(mean_norm["MQ3"], mean_norm["TGS2602"])
    feat["MQ3_MQ135_correlation"] = _safe_corr(data["MQ3"], data["MQ135"])

    # 舊版（原始讀值相除）的比值，只給 legacy 後處理規則與 debug 使用，不進模型
    feat["MQ2_MQ3_raw_ratio"] = _safe_ratio(np.mean(data["MQ2"]), np.mean(data["MQ3"]))
    feat["MQ3_MQ135_raw_ratio"] = _safe_ratio(np.mean(data["MQ3"]), np.mean(data["MQ135"]))

    feat["MQ2_auc_norm"] = _safe_auc(data["MQ2"]) / (len(data["MQ2"]) * _base_value(air, "MQ2"))
    feat["MQ2_mean_norm"] = np.mean(data["MQ2"]) / _base_value(air, "MQ2")

    feat["MQ3_range_norm"] = (
        np.max(data["MQ3"]) - np.min(data["MQ3"])
    ) / _base_value(air, "MQ3")
    feat["MQ3_max_norm"] = np.max(data["MQ3"]) / _base_value(air, "MQ3")
    feat["MQ3_std_norm"] = np.std(data["MQ3"]) / _base_value(air, "MQ3")

    feat["MQ9_slope"] = _safe_slope(data["MQ9"])
    feat["MQ9_min_norm"] = np.min(data["MQ9"]) / _base_value(air, "MQ9")
    feat["MQ9_delta_mean"] = _safe_mean_diff(data["MQ9"])

    feat["TGS2602_min_norm"] = np.min(data["TGS2602"]) / _base_value(air, "TGS2602")
    feat["TGS2602_delta_std"] = (
        np.std(np.diff(data["TGS2602"]))
        if len(data["TGS2602"]) >= 2
        else 0.0
    )
    feat["TGS2602_std_norm"] = np.std(data["TGS2602"]) / _base_value(air, "TGS2602")

    return feat, data


# ─────────────────────────────────────────
# 後處理邏輯
# ─────────────────────────────────────────
def _legacy_feat(feat):
    # 舊規則的門檻（例如 ratio > 2.00）是依原始讀值比值調出來的，
    # 套用舊規則時換回舊比值，避免與正規化後的比值混用
    legacy = dict(feat)
    legacy["MQ2_MQ3_ratio"] = feat["MQ2_MQ3_raw_ratio"]
    legacy["MQ3_MQ135_ratio"] = feat["MQ3_MQ135_raw_ratio"]
    return legacy


def _air_or_no_sample_guard(feat, proba):
    mq2_mean_norm = float(feat.get("MQ2_mean_norm", 999.0))
    mq9_min_norm = float(feat.get("MQ9_min_norm", 999.0))
    tgs2602_min_norm = float(feat.get("TGS2602_min_norm", 999.0))
    mq3_std_norm = float(feat.get("MQ3_std_norm", 999.0))
    tgs2602_std_norm = float(feat.get("TGS2602_std_norm", 999.0))
    mq9_slope = float(feat.get("MQ9_slope", 999.0))
    mq3_mq135_ratio = float(feat.get("MQ3_MQ135_ratio", 0.0))
    p3 = float(proba[3]) if len(proba) >= 4 else 0.0

    if tgs2602_min_norm > 1.02:
        return False
    if mq3_mq135_ratio > 2.00:
        return False
    if p3 >= 0.08 and mq3_mq135_ratio > 1.98:
        return False

    baseline_hits = sum([
        0.99 <= mq2_mean_norm <= 1.01,
        0.99 <= mq9_min_norm <= 1.01,
        0.99 <= tgs2602_min_norm <= 1.01,
    ])

    weak_signal_hits = sum([
        mq3_std_norm < 0.0028,
        tgs2602_std_norm < 0.0030,
        abs(mq9_slope) < 0.006,
    ])

    return baseline_hits == 3 and weak_signal_hits >= 2


def _early_stage_override(pred, proba, feat):
    if int(pred) != 2:
        return pred, False

    p0 = float(proba[0])
    p1 = float(proba[1])
    p2 = float(proba[2])
    p3 = float(proba[3])

    tgs = float(feat.get("TGS2602_min_norm", 1.0))
    mq2 = float(feat.get("MQ2_mean_norm", 1.0))
    mq9 = float(feat.get("MQ9_min_norm", 1.0))
    mq3s = float(feat.get("MQ3_std_norm", 999.0))
    mq3r = float(feat.get("MQ3_range_norm", 999.0))
    ratio = float(feat.get("MQ3_MQ135_ratio", 0.0))
    em = p0 + p1

    if p2 <= 0.70 and p3 <= 0.13 and tgs < 0.94 and mq2 < 1.00 and mq9 < 0.97:
        return 0, True

    if p2 <= 0.50 and p3 <= 0.12 and em >= 0.35 and mq3s <= 0.0015 and mq3r <= 0.0025:
        return 0, True

    if (
        p2 <= 0.88
        and p3 <= 0.10
        and 0.94 <= tgs < 1.02
        and mq2 < 1.02
        and mq9 < 0.98
        and mq3s < 0.0065
        and mq3r < 0.0080
        and ratio > 2.00
    ):
        return 1, True

    if p2 <= 0.60 and p3 <= 0.14 and p1 >= 0.18 and em >= 0.35 and ratio > 1.70:
        return 1, True

    return pred, False


def _overripe_override(pred, proba, feat):
    if int(pred) != 2:
        return pred, False

    p0, p1, p2, p3 = [float(proba[i]) for i in range(4)]

    ratio = float(feat.get("MQ3_MQ135_ratio", 0.0))
    tgs = float(feat.get("TGS2602_min_norm", 0.0))
    mq2 = float(feat.get("MQ2_mean_norm", 999.0))
    em = p0 + p1

    if em >= 0.30 and p2 <= 0.60:
        return pred, False

    strong = p3 >= 0.14 and p2 >= 0.60 and tgs >= 1.05 and ratio >= 2.08
    normal = p3 >= 0.15 and p2 >= 0.60 and ratio >= 2.00 and mq2 <= 1.02
    soft = p3 >= 0.15 and p2 >= 0.65 and ratio >= 2.00

    if strong or normal or soft:
        return 3, True

    return pred, False


def _build_raw_maturity_percent(proba):
    score = (proba[0] * 0 + proba[1] * 1 + proba[2] * 2 + proba[3] * 3) / 3.0
    return int(round(score * 100))


def _build_early_display_percent(final_pred, feat):
    tgs = float(feat.get("TGS2602_min_norm", 1.0))
    mq2 = float(feat.get("MQ2_mean_norm", 1.0))
    mq9 = float(feat.get("MQ9_min_norm", 1.0))

    if int(final_pred) == 0:
        strength = np.clip((tgs - 0.90) / 0.05, 0.0, 1.0)
        return int(round(15 + 10 * strength))

    if int(final_pred) == 1:
        strength = np.clip(
            (
                (tgs - 0.95) / 0.05
                + (1.0 - abs(mq2 - 1.0))
                + (1.0 - abs(mq9 - 1.0))
            )
            / 3.0,
            0.0,
            1.0,
        )
        return int(round(35 + 13 * strength))

    return None


def _build_final_display_percent(raw_pct, final_pred, override_used, proba, feat):
    if not override_used or final_pred != 3:
        return raw_pct

    p3 = float(proba[3])
    tgs = float(feat.get("TGS2602_min_norm", 1.0))
    ratio = float(feat.get("MQ3_MQ135_ratio", 1.0))

    p3_s = np.clip((p3 - 0.08) / 0.22, 0.0, 1.0)
    tgs_s = np.clip((tgs - 0.970) / 0.165, 0.0, 1.0)
    r_s = np.clip((ratio - 2.00) / 0.18, 0.0, 1.0)

    strength = (p3_s + tgs_s + r_s) / 3.0
    pct = int(round(83 + 17 * strength))

    return max(raw_pct, max(83, min(100, pct)))


def _get_display_text(proba, pred):
    sorted_idx = np.argsort(proba)[::-1]
    top1 = int(sorted_idx[0])
    top2 = int(sorted_idx[1])
    p3 = float(proba[3])

    if top1 == 2 and p3 >= 0.18:
        return "成熟，明顯接近過熟"

    if top1 == 2 and p3 >= 0.08:
        return "成熟，但已有過熟傾向"

    if abs(top1 - top2) == 1 and proba[top2] >= 0.15:
        return f"{STAGE_ZH[top1]}（接近{STAGE_ZH[top2]}）"

    return STAGE_ZH[top1]


# ─────────────────────────────────────────
# 推論核心
# ─────────────────────────────────────────
def _run_inference(warmup_sec: int, scan_id: str):
    try:
        if _model is None or _features is None:
            _set_state(status="error", error="MODEL_NOT_LOADED")
            return

        if not AIR_BASE_PATH.exists():
            _set_state(status="error", error="NO_AIR_BASE")
            return

        with open(AIR_BASE_PATH, "r", encoding="utf-8") as f:
            air = json.load(f)

        air_problems = _validate_air_base(air)
        if air_problems:
            _set_state(status="error", error="AIR_BASE_INVALID：" + "；".join(air_problems) + "，請重新空氣校正")
            return

        global _last_scan_end
        sec_since_last_scan = (
            round(time.time() - _last_scan_end, 1) if _last_scan_end is not None else None
        )

        ser, header, port = _open_serial_and_wait_header()

        total_sec = warmup_sec + SCAN_ROWS
        all_rows = []
        t0 = time.time()

        while time.time() - t0 < total_sec:
            line = ser.readline().decode("utf-8", errors="ignore").strip()

            if not line:
                continue

            if line[0] in ("#", "✅", "❌", "📋", "⏱", "🍍", "="):
                continue

            vals = [x.strip() for x in line.split(",")]

            if len(vals) != len(header):
                continue

            row = dict(zip(header, vals))
            parsed = _read_arduino_row(row)

            if parsed is None:
                continue

            all_rows.append(parsed)

            elapsed = time.time() - t0
            progress = min(99, int(elapsed / total_sec * 100))
            _set_state(progress=progress)

        ser.close()
        _last_scan_end = time.time()

        if not all_rows:
            _set_state(status="error", error="沒有收集到任何感測資料")
            return

        if len(all_rows) < WINDOW:
            _set_state(
                status="error",
                error=f"取樣不足：只收到 {len(all_rows)} 筆，至少需要 {WINDOW} 筆",
            )
            return

        rows = all_rows[-SCAN_ROWS:]

        # 多窗口推論：每個 30 筆窗口各算一次特徵與機率，再平均
        window_results = []
        for start in range(0, len(rows) - WINDOW + 1, WINDOW_STEP):
            w_feat, _ = _build_features(rows[start:start + WINDOW], air)

            missing = [f for f in _features if f not in w_feat]
            if missing:
                raise ValueError(f"FEATURE_MISMATCH：gateway 無法計算模型需要的特徵 {missing}")

            x = np.array([w_feat[f] for f in _features], dtype=float)
            if not np.all(np.isfinite(x)):
                bad = [f for f, v in zip(_features, x) if not np.isfinite(v)]
                raise ValueError(f"特徵數值異常（NaN/inf）：{bad}")

            w_proba = np.zeros(4, dtype=float)
            if hasattr(_model, "predict_proba"):
                w_proba[_model.classes_.astype(int)] = _model.predict_proba(x.reshape(1, -1))[0]
            else:
                w_proba[int(_model.predict(x.reshape(1, -1))[0])] = 1.0

            window_results.append({
                "start_row": start,
                "stage": int(np.argmax(w_proba)),
                "proba": w_proba,
                "feat": w_feat,
            })

        proba = np.mean([w["proba"] for w in window_results], axis=0)
        raw_pred = int(np.argmax(proba))

        window_stages = [w["stage"] for w in window_results]
        agreement = window_stages.count(raw_pred) / len(window_stages)
        stable = agreement > 0.5

        # 舊規則與 guard 沿用最後一個窗口（等同舊版只看最後 30 筆）
        feat = window_results[-1]["feat"]
        legacy_feat = _legacy_feat(feat)

        # guard 門檻是舊版調的，只記錄、不影響判斷
        guard_triggered = _air_or_no_sample_guard(legacy_feat, proba)
        raw_pct = _build_raw_maturity_percent(proba)

        # raw 模式：顯示文字只用階段名稱，「接近／過熟傾向」等提示交給 probabilities 呈現
        display_text = STAGE_ZH[raw_pred]
        final_pred = raw_pred
        final_pct = raw_pct
        early_used = False
        override_used = False

        if POSTPROCESS_MODE == "legacy":
            display_text = _get_display_text(proba, raw_pred)
            final_pred, early_used = _early_stage_override(raw_pred, proba, legacy_feat)

            if early_used:
                if final_pred == 0:
                    display_text = "未熟（接近初熟）"
                elif final_pred == 1:
                    display_text = "初熟（接近成熟）"
                else:
                    display_text = STAGE_ZH.get(final_pred, str(final_pred))

                final_pct = _build_early_display_percent(final_pred, legacy_feat)
                if final_pct is None:
                    final_pct = raw_pct
            else:
                final_pred, override_used = _overripe_override(raw_pred, proba, legacy_feat)

                if override_used:
                    display_text = "過熟"

                final_pct = _build_final_display_percent(
                    raw_pct,
                    final_pred,
                    override_used,
                    proba,
                    legacy_feat,
                )

        sampling = _sampling_quality(rows)

        # quality_status：量測本身是否有效，與分類結果分開
        #   ok                                  → measurement_valid = True
        #   unstable（窗口結果不一致）            → 回傳結果，但 measurement_valid = False
        #   unknown（無法讀到 timestamp_ms）      → 回傳結果，但 measurement_valid = False
        #   timestamp_reset / interval_abnormal → 資料不符合模型前提，以 error 結束（見下方）
        sampling_failed = sampling["status"] in ("timestamp_reset", "interval_abnormal")
        if sampling_failed:
            quality_status = sampling["status"]
        elif not stable:
            quality_status = "unstable"
            display_text = f"{display_text}（量測不穩定，建議重測）"
        else:
            quality_status = "ok" if sampling["status"] == "ok" else "unknown"
        measurement_valid = quality_status == "ok"

        _, data = _build_features(rows, air)

        sensor_means = {
            s: float(np.mean(data[s]))
            for s in GAS_SENSORS
        }

        sensor_raw = {
            "MQ2": sensor_means["MQ2"],
            "MQ3": sensor_means["MQ3"],
            "MQ9": sensor_means["MQ9"],
            "MQ135": sensor_means["MQ135"],
            "TGS2602": sensor_means["TGS2602"],
        }

        sensor_percent = {
            s: round(min(100.0, sensor_means[s] / 1023.0 * 100.0), 2)
            for s in GAS_SENSORS
        }

        temp_values = [r["Temp_C"] for r in rows if r.get("Temp_C") is not None]
        humidity_values = [r["Humidity_pct"] for r in rows if r.get("Humidity_pct") is not None]
        pressure_values = [r["Pressure_hPa"] for r in rows if r.get("Pressure_hPa") is not None]

        environment = {
            "temperature": round(float(np.mean(temp_values)), 2) if temp_values else None,
            "humidity": round(float(np.mean(humidity_values)), 2) if humidity_values else None,
            "pressure": round(float(np.mean(pressure_values)), 2) if pressure_values else None,
        }

        result = {
            "id": scan_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",

            "stage": final_pred,
            "ripeness": STAGE_EN[final_pred],
            "label_zh": STAGE_ZH[final_pred],
            "display_text": display_text,
            "percent": final_pct,

            "ripenessLabelZh": display_text,
            "ripenessLabelEn": STAGE_EN[final_pred].capitalize(),
            "maturityPercent": final_pct,
            "confidence": round(float(np.max(proba)), 4),

            "probabilities": {
                "stage0": round(float(proba[0]), 4),
                "stage1": round(float(proba[1]), 4),
                "stage2": round(float(proba[2]), 4),
                "stage3": round(float(proba[3]), 4),
            },

            "sensor_percent": sensor_percent,
            "sensor_raw": sensor_raw,

            "environment": environment,

            "suggestion": SUGGESTION.get(final_pred, ""),
            "suggestions": [SUGGESTION.get(final_pred, "")],

            "guard_triggered": guard_triggered,
            "override_used": override_used,

            "quality_status": quality_status,
            "measurement_valid": measurement_valid,

            # 數值意義說明：避免把模型推估值誤讀成實測值或正確率
            "field_notes": {
                "maturityPercent": "模型推估指標 = (p1 + 2*p2 + 3*p3) / 3，非糖度或實測熟度",
                "confidence": "平均後最高類別機率，未經機率校準，不等於實際正確率",
            },

            "stability": {
                "n_windows": len(window_results),
                "window_stages": window_stages,
                "agreement": round(agreement, 4),
                "stable": stable,
            },

            "sampling": sampling,

            "debug": {
                "raw_pred": raw_pred,
                "final_pred": final_pred,
                "postprocess_mode": POSTPROCESS_MODE,
                "model_sha256": _model_sha256,
                "sec_since_last_scan": sec_since_last_scan,
                "onset_state": _onset_state(rows, air),
                "early_override_used": early_used,
                "overripe_override_used": override_used,
                "feature_values": feat,
                "windows": [
                    {
                        "start_row": w["start_row"],
                        "stage": w["stage"],
                        "proba": [round(float(p), 4) for p in w["proba"]],
                        "feature_values": w["feat"],
                    }
                    for w in window_results
                ],
                "n_rows_collected": len(all_rows),
                "air_base": air,
                "arduino_port": port,
            },
        }

        if sampling_failed:
            # App 收到 error 不會顯示分類；result 仍保留在 state 供除錯
            _set_state(
                status="error",
                progress=100,
                result=result,
                error=f"SAMPLING_{quality_status.upper()}：取樣時間異常（{sampling}），請重新量測",
            )
            print(f"[Scan] 取樣時間異常：{sampling}")
            return

        _set_state(status="done", progress=100, result=result, error=None)

        print(f"[Scan] 完成：{STAGE_ZH[final_pred]} ({final_pct}%)")

    except Exception as e:
        print(f"[Scan] 錯誤：{e}")
        _set_state(status="error", error=str(e))


# ─────────────────────────────────────────
# 空氣校正
# ─────────────────────────────────────────
def _run_calibration():
    try:
        ser, header, port = _open_serial_and_wait_header()

        all_rows = []
        t0 = time.time()

        while time.time() - t0 < 30:
            line = ser.readline().decode("utf-8", errors="ignore").strip()

            if not line:
                continue

            if line[0] in ("#", "✅", "❌", "📋", "⏱", "🍍", "="):
                continue

            vals = [x.strip() for x in line.split(",")]

            if len(vals) != len(header):
                continue

            row = dict(zip(header, vals))
            parsed = _read_arduino_row(row)

            if parsed is None:
                continue

            all_rows.append(parsed)

            progress = min(99, int((time.time() - t0) / 30 * 100))
            _set_state(progress=progress)

        ser.close()

        if not all_rows:
            _set_state(status="error", error="校正期間沒有收到資料")
            return

        air = {}

        for key in CALIBRATION_KEYS:
            values = [r[key] for r in all_rows if r.get(key) is not None]
            if values:
                air[key] = float(np.mean(values))

        air["_meta"] = {
            "created_at": datetime.utcnow().isoformat() + "Z",
            "duration_sec": 30,
            "sample_count": len(all_rows),
            "arduino_port": port,
            "gas_sensors": GAS_SENSORS,
            "environment_keys": BME_KEYS,
        }

        with open(AIR_BASE_PATH, "w", encoding="utf-8") as f:
            json.dump(air, f, indent=2, ensure_ascii=False)

        print(f"[Calibrate] 完成，air_base.json 已儲存：{air}")

        _set_state(status="idle", progress=100, result=None, error=None)

    except Exception as e:
        print(f"[Calibrate] 錯誤：{e}")
        _set_state(status="error", error=str(e))


# ─────────────────────────────────────────
# Flask App
# ─────────────────────────────────────────
app = Flask(__name__)


@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, ngrok-skip-browser-warning"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/health", methods=["GET"])
def health():
    air_exists = AIR_BASE_PATH.exists()

    calibrated_at = None
    air_base_preview = None

    if air_exists:
        calibrated_at = datetime.utcfromtimestamp(
            AIR_BASE_PATH.stat().st_mtime
        ).isoformat() + "Z"

        try:
            with open(AIR_BASE_PATH, "r", encoding="utf-8") as f:
                air_base_preview = json.load(f)
        except Exception:
            air_base_preview = None

    ports = sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*"))

    return jsonify({
        "status": "ok",
        "air_base_exists": air_exists,
        "air_calibrated_at": calibrated_at,
        "air_base_preview": air_base_preview,
        "model_exists": MODEL_PATH.exists(),
        "model_loaded": _model is not None,
        "model_sha256": _model_sha256,
        "n_features": len(_features) if _features is not None else None,
        "postprocess_mode": POSTPROCESS_MODE,
        "feature_columns_exists": FEATURES_PATH.exists(),
        "arduino_ports": ports,
        "pineapple_dir": str(PINEAPPLE_DIR),
        "time": datetime.utcnow().isoformat() + "Z",
    })


@app.route("/calibrate", methods=["POST", "OPTIONS"])
def calibrate():
    if request.method == "OPTIONS":
        return "", 204

    state = _get_state()

    if state["status"] in ("scanning", "calibrating"):
        return jsonify({"error": "BUSY"}), 409

    _set_state(status="calibrating", progress=0, result=None, error=None)

    t = threading.Thread(target=_run_calibration, daemon=True)
    t.start()

    return jsonify({
        "ok": True,
        "message": "空氣校正已開始，約 30 秒後完成",
    }), 200


@app.route("/scan", methods=["POST", "OPTIONS"])
def scan():
    if request.method == "OPTIONS":
        return "", 204

    state = _get_state()

    if state["status"] in ("scanning", "calibrating"):
        return jsonify({"error": "BUSY"}), 409

    if not AIR_BASE_PATH.exists():
        return jsonify({"error": "NO_AIR_BASE"}), 400

    data = request.get_json(silent=True) or {}

    warmup_sec = int(data.get("warmup_sec", 0))
    scan_id = str(uuid.uuid4())

    _set_state(
        status="scanning",
        progress=0,
        result=None,
        error=None,
        scan_id=scan_id,
    )

    t = threading.Thread(
        target=_run_inference,
        args=(warmup_sec, scan_id),
        daemon=True,
    )
    t.start()

    return jsonify({
        "ok": True,
        "scan_id": scan_id,
    }), 200


@app.route("/status", methods=["GET"])
def status():
    state = _get_state()

    return jsonify({
        "status": state["status"],
        "progress": state["progress"],
        "result": state["result"],
        "error": state["error"],
        "scan_id": state["scan_id"],
    })


@app.route("/scan_records", methods=["POST", "OPTIONS"])
def scan_records():
    if request.method == "OPTIONS":
        return "", 204

    payload = request.get_json(silent=True) or {}

    records = []

    if RECORDS_PATH.exists():
        try:
            with open(RECORDS_PATH, "r", encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            records = []

    record = {
        "id": payload.get("id", str(uuid.uuid4())),
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "data": payload,
    }

    records.insert(0, record)

    with open(RECORDS_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"[Records] 已儲存紀錄：{record['id']}")

    return jsonify({
        "ok": True,
        "id": record["id"],
    }), 200


@app.route("/scan_records/<record_id>/feedback", methods=["POST", "OPTIONS"])
def feedback(record_id):
    if request.method == "OPTIONS":
        return "", 204

    payload = request.get_json(silent=True) or {}

    print(f"[Feedback] record={record_id} payload={payload}")

    return jsonify({"ok": True}), 200


# ─────────────────────────────────────────
# 啟動
# ─────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("🍍 Pineapple Gateway v2 啟動中")
    print(f"  PINEAPPLE_DIR : {PINEAPPLE_DIR}")
    print(f"  MODEL_PATH    : {MODEL_PATH}")
    print(f"  AIR_BASE_PATH : {AIR_BASE_PATH}")
    print(f"  RECORDS_PATH  : {RECORDS_PATH}")
    print("=" * 50)

    try:
        _load_model()
    except Exception as e:
        print(f"[WARNING] 模型載入失敗：{e}")
        print("請確認 deploy_student.pkl 和 feature_columns.json 存在於 pineapple 資料夾")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True,
    )