"""
Step 6A：備份與回復測試（完全隔離的暫存站點；只用套件內的 pinenose_backup.py 與 start／stop 腳本）

流程：模擬前一版（同一 commit 以不同 release_id 建置，標示為模擬）→ 模擬使用者資料 → 備份（先 dry-run）→ 驗證 →
安裝並切換到候選版 → 健康檢查 → 候選版產生較新的資料 → 模擬候選版啟動失敗（程式被竄改）→ 回復（先 dry-run）→
前一版啟動、健康檢查 → 確認資料未損毀、較新歷史未被覆寫、AIR 未被清空、未核准模型沒有被開啟。
另測：資料衝突（不覆寫、另存）、備份被竄改（拒絕回復）、release 目錄遺失（從備份還原）、核准清單不隨回復恢復。
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "test_support"))
from common import (EVAL, HERE, RELEASE_PY, REPO, RESULTS, RUN_ROOT, WT, base_env, check, http, install, mgr, package,  # noqa: E402
                    port_open, rec, run, sh, sha256, site_config, tree_hashes, wait_terminal, write_json)

T0 = time.time()
PKG = package()
RID = PKG.name[:-len(".tar.gz")]
ROOT = RUN_ROOT / "rollback"
if ROOT.exists():
    shutil.rmtree(ROOT)
ROOT.mkdir(parents=True)
SITE = ROOT / "site"
ART2 = ROOT / "artifacts_prev"
PREV = "pinenose-rc-prev-simulated"
v = json.loads(__import__("tarfile").open(PKG).extractfile(f"{RID}/VERSION.json").read())
code, out, _ = run([sys.executable, WT / "pinenose_release/build_release.py", "--commit", v["source_commit"], "--out-dir", ART2, "--release-id", PREV, "--repo", REPO])
assert code == 0, out
PREV_PKG = ART2 / f"{PREV}.tar.gz"
TOOL = None
CTL = ROOT / "fake_serial_control.json"
ENV = base_env({"FAKE_SERIAL_CONTROL": str(CTL), "FAKE_SERIAL_LOG": str(ROOT / "fake_serial_events.jsonl")}, fake_serial=True)
PORTS = (16000, 16001, 19000)
GW = "http://127.0.0.1:16001"

sys.path.insert(0, str(EVAL / "r1_controlled_retraining"))
from repaired_parser import read_raw_xlsx_fixed  # noqa: E402
PB = pd.read_csv(EVAL / "r1_controlled_retraining/pipeline_b_corrected_training.csv", encoding="utf-8-sig")
DAY = PB[PB.in_S99].iloc[0]
SENS = ["MQ2", "MQ3", "MQ9", "MQ135", "TGS2602"]
HEADER = ["timestamp_ms", "timestamp_s", "MQ2_raw", "MQ3_raw", "MQ9_raw", "MQ135_raw", "TGS2602_raw", "Temp_C", "Humidity_pct", "Pressure_hPa"]


def air_lines():
    df = read_raw_xlsx_fixed(str(WT / "enose_model_training/orkspace/data/raw" / DAY.air_file))
    df = df[df[[f"{s}_raw" for s in SENS]].notna().all(axis=1)].reset_index(drop=True)
    return [",".join("" if pd.isna(r.get(c)) else str(r.get(c)) for c in HEADER) for _, r in df.iterrows()]


def tool(*args, execute=False):
    return run([RELEASE_PY, SITE / "releases" / current() / "ops/pinenose_backup.py", *args, *(["--execute"] if execute else [])])


def current():
    return (SITE / "current_release").read_text(encoding="utf-8").strip()


def calibrate():
    write_json(CTL, {"lines": air_lines(), "header": True})
    st, js = http("POST", f"{GW}/calibrate", {})
    return wait_terminal(GW, js["scan_id"])


HIST = SITE / "data/formal/scan_history/history_formal.jsonl"
UPL = SITE / "data/formal/scan_history/client_uploads_formal.jsonl"
AIR = SITE / "data/formal/air/air_base.json"
REG = SITE / "site/model_registry.formal.json"
PROF = None


def t01():
    global PROF
    rdir, out = install(SITE, PREV_PKG)
    PROF = site_config(SITE, rdir, "formal", PORTS, max_age=3600, serial_port="FAKE0", unified=False)
    code, out, _ = sh(rdir, "start_pineapple_system.sh", PROF, ENV)
    cal = calibrate()
    HIST.parent.mkdir(parents=True, exist_ok=True)
    sim = [{"scan_id": f"sim-{i:03d}", "result_kind": "FORMAL", "note": "SIMULATED user record for rollback test (no approved model exists)"} for i in range(5)]
    HIST.write_text("".join(json.dumps(x) + "\n" for x in sim), encoding="utf-8")
    UPL.write_text(json.dumps({"scan_id": "sim-000", "note": "SIMULATED upload"}) + "\n", encoding="utf-8")
    st, h = http("GET", f"{GW}/health")
    return (code == 0 and cal["status"] == "done" and current() == PREV and h["release_id"] == PREV and AIR.exists()), \
        f"previous release {PREV} running (exit {code}); real /calibrate → {cal['status']}; simulated history 5 lines + 1 upload"


check("B", "B01-SIMULATED-PREVIOUS", "模擬前一版運作中，含 AIR（實際校正路徑產生）與模擬使用者歷史", t01)
AIR_PREV_ID = json.loads(AIR.read_text(encoding="utf-8"))["_meta"]["calibration_id"]
write_json(REG, {"_note": "SIMULATED: an approval that existed at backup time", "models": {"f" * 64: {"status": "approved", "feature_columns": []}}})


def t02():
    before = tree_hashes(SITE)
    code, out, _ = tool("backup", "--site", SITE)
    after = tree_hashes(SITE)
    code2, out2, _ = tool("backup", "--site", SITE, execute=True)
    bdir = sorted((SITE / "backups").iterdir())[-1]
    man = json.loads((bdir / "backup_manifest.json").read_text(encoding="utf-8"))
    cats = sorted({x["category"] for x in man["files"]})
    code3, out3, _ = tool("verify", "--backup", bdir)
    return (code == 0 and before == after and "[DRY-RUN]" in out and code2 == 0 and cats == ["air", "config", "history", "program"] and code3 == 0
            and all(len(x["sha256"]) == 64 for x in man["files"])), \
        f"dry-run changed nothing={before == after}; backup {bdir.name}: {len(man['files'])} files, categories {cats}; verify exit {code3}"


check("B", "B02-BACKUP", "備份：預設 dry-run 不改任何檔；--execute 備份程式／設定／AIR／歷史並產生 SHA-256 清單；驗證通過", t02)
BDIR = sorted((SITE / "backups").iterdir())[-1]
write_json(REG, {"_note": "approval removed after backup (current state)", "models": {}})


def t03():
    sh(SITE / "releases" / PREV, "stop_pineapple_system.sh", PROF, ENV)
    code, out, _ = tool("install", "--site", SITE, "--package", PKG, execute=True)
    code2, out2, _ = tool("switch", "--site", SITE, "--release", RID, execute=True)
    code3, out3, _ = sh(SITE / "releases" / RID, "start_pineapple_system.sh", PROF, ENV)
    st, h = http("GET", f"{GW}/health")
    return (code == 0 and code2 == 0 and code3 == 0 and h["release_id"] == RID and h["model_error"]["code"] == "MODEL_NOT_APPROVED"), \
        f"install {code} / switch {code2} / start {code3}; health release={h['release_id']} model={h['model_error']['code']}"


check("B", "B03-SWITCH-TO-CANDIDATE", "安裝並切換到候選版，健康檢查通過（成熟度推論仍未核准）", t03)


def t04():
    cal = calibrate()
    with open(HIST, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"scan_id": "sim-new-001", "result_kind": "FORMAL", "note": "SIMULATED newer record written while candidate ran"}) + "\n")
    new_id = json.loads(AIR.read_text(encoding="utf-8"))["_meta"]["calibration_id"]
    return cal["status"] == "done" and new_id != AIR_PREV_ID, f"candidate recalibrated (new calibration_id {new_id[:8]}…) and appended 1 newer history record"


check("B", "B04-NEWER-DATA", "候選版產生較新資料（新 AIR 校正、追加歷史）", t04)
AIR_NEW = AIR.read_bytes()
HIST_NEW = HIST.read_bytes()


def t05():
    sh(SITE / "releases" / RID, "stop_pineapple_system.sh", PROF, ENV)
    f = SITE / "releases" / RID / "app/pineapple_final/app_local.py"
    f.write_bytes(f.read_bytes() + b"\n# corrupted\n")
    code, out, _ = sh(SITE / "releases" / RID, "start_pineapple_system.sh", PROF, ENV)
    return code == 2 and "RELEASE_INTEGRITY_FAILED" in out and not port_open(16001), f"start candidate → exit {code} {out.strip().splitlines()[-1][:120]}"


check("B", "B05-CANDIDATE-START-FAILS", "模擬候選版啟動失敗（程式檔被破壞）：明確失敗、不啟動任何服務", t05)


def t06():
    before = tree_hashes(SITE)
    code, out, _ = run([RELEASE_PY, SITE / "releases" / PREV / "ops/pinenose_backup.py", "rollback", "--site", SITE, "--backup", BDIR])
    same = tree_hashes(SITE) == before
    code2, out2, _ = run([RELEASE_PY, SITE / "releases" / PREV / "ops/pinenose_backup.py", "rollback", "--site", SITE, "--backup", BDIR, "--execute"])
    code3, out3, _ = sh(SITE / "releases" / current(), "start_pineapple_system.sh", PROF, ENV)
    st, h = http("GET", f"{GW}/health")
    reg = json.loads(REG.read_text(encoding="utf-8"))["models"]
    ok = (code == 0 and same and code2 == 0 and current() == PREV and code3 == 0 and h["release_id"] == PREV and AIR.read_bytes() == AIR_NEW
          and HIST.read_bytes() == HIST_NEW and b"sim-new-001" in HIST.read_bytes() and reg == {} and h["model_error"]["code"] == "MODEL_NOT_APPROVED"
          and UPL.exists())
    return ok, (f"dry-run changed nothing={same}; rollback exit {code2} → current={current()}; restart exit {code3}, health release={h['release_id']}; "
                f"newer AIR kept={AIR.read_bytes() == AIR_NEW}; newer history kept={HIST.read_bytes() == HIST_NEW}; registry after rollback={reg} "
                f"(backup had an approved entry; not restored); model={h['model_error']['code']}")


check("B", "B06-ROLLBACK", "回復：dry-run 不改檔；回到前一版並啟動成功；較新的 AIR 與歷史保留；核准清單不回復；未核准模型仍未開啟", t06)


def t07():
    sh(SITE / "releases" / PREV, "stop_pineapple_system.sh", PROF, ENV)
    HIST.write_text('{"scan_id": "rewritten", "note": "SIMULATED non-append modification"}\n', encoding="utf-8")
    cur = HIST.read_bytes()
    code, out, _ = run([RELEASE_PY, SITE / "releases" / PREV / "ops/pinenose_backup.py", "rollback", "--site", SITE, "--backup", BDIR, "--execute"])
    side = list(HIST.parent.glob("history_formal.jsonl.from_backup_*"))
    ok = code == 4 and "[CONFLICT]" in out and HIST.read_bytes() == cur and len(side) == 1 and side[0].read_bytes().count(b"sim-") == 5
    kept = HIST.read_bytes() == cur
    HIST.write_bytes(HIST_NEW)
    return ok, f"exit {code}; current (modified) file kept as-is={kept}; backup copy saved as {[s.name for s in side]}"


check("B", "B07-DATA-CONFLICT", "資料衝突（目前歷史不是備份的延伸）：不覆寫、另存備份版本、明確回報（exit 4）", t07)


def t08():
    f = next(p for p in BDIR.rglob("*.jsonl"))
    orig = f.read_bytes()
    f.write_bytes(orig + b"tamper\n")
    before = tree_hashes(SITE / "data")
    c1, o1, _ = run([RELEASE_PY, SITE / "releases" / PREV / "ops/pinenose_backup.py", "verify", "--backup", BDIR])
    c2, o2, _ = run([RELEASE_PY, SITE / "releases" / PREV / "ops/pinenose_backup.py", "rollback", "--site", SITE, "--backup", BDIR, "--execute"])
    unchanged = tree_hashes(SITE / "data") == before
    f.write_bytes(orig)
    return c1 == 3 and c2 == 3 and "BACKUP_INTEGRITY_FAILED" in o2 and unchanged, f"verify exit {c1}; rollback exit {c2}; data unchanged={unchanged}"


check("B", "B08-TAMPERED-BACKUP", "備份被竄改：驗證失敗，回復拒絕執行且不改任何資料（exit 3）", t08)


def t09():
    shutil.rmtree(SITE / "releases" / PREV)
    (SITE / "current_release").write_text(RID + "\n", encoding="utf-8")
    tmp_tool = ROOT / "pinenose_backup_from_candidate_pkg.py"
    import tarfile
    with tarfile.open(PKG) as tf:
        tmp_tool.write_bytes(tf.extractfile(f"{RID}/ops/pinenose_backup.py").read())
    code, out, _ = run([RELEASE_PY, tmp_tool, "rollback", "--site", SITE, "--backup", BDIR, "--execute"])
    ok_dir = (SITE / "releases" / PREV / "SHA256SUMS").exists()
    code2, out2, _ = sh(SITE / "releases" / PREV, "start_pineapple_system.sh", PROF, ENV)
    st, h = http("GET", f"{GW}/health")
    sh(SITE / "releases" / PREV, "stop_pineapple_system.sh", PROF, ENV)
    return code == 0 and ok_dir and current() == PREV and code2 == 0 and h["release_id"] == PREV, \
        f"previous release dir deleted → rollback restored it from backup (exit {code}), integrity verified, started (exit {code2}), health release={h['release_id']}"


check("B", "B09-RESTORE-PROGRAM-FROM-BACKUP", "前一版程式目錄遺失：回復從備份還原並驗證 SHA256SUMS 後可啟動", t09)


def t10():
    left = list(SITE.rglob("*.pid.json"))
    return not left and not port_open(16001) and not port_open(16000), f"pid files left={left}; ports free"


check("B", "B10-CLEAN-STOP", "測試結束沒有殘留程序與 PID 檔", t10)

df = pd.DataFrame(RESULTS)
df.to_csv(HERE / "backup_rollback_test_results.csv", index=False, encoding="utf-8-sig")
print(f"\nbackup/rollback: {int((df.verdict == 'PASS').sum())}/{len(df)} PASS; {time.time() - T0:.0f}s")
sys.exit(0 if (df.verdict == "PASS").all() else 1)
