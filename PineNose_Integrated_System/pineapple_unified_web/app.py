from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime, timedelta
from pathlib import Path
import json
import uuid
import io
import zipfile
import csv
import html

app = Flask(__name__)

# =========================================================
# Raspberry Pi 服務網址
# =========================================================
SMELL_PAGE_URL = "http://172.20.10.3:5051"
PHOTO_PAGE_URL = "http://172.20.10.3:5002"

# =========================================================
# 本機端歷史紀錄設定
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
HISTORY_FILE = DATA_DIR / "history.json"
RETENTION_DAYS = 30
EXPIRING_SOON_DAYS = 3


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def parse_dt(value):
    return datetime.fromisoformat(value)


def ensure_history_file():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not HISTORY_FILE.exists():
        data = {
            "folders": [
                {
                    "id": "default",
                    "name": "預設資料夾",
                    "created_at": now_iso()
                }
            ],
            "records": []
        }
        save_history(data)


def load_history():
    ensure_history_file()

    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    data = cleanup_expired_records(data)
    save_history(data)
    return data


def save_history(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cleanup_expired_records(data):
    today = datetime.now()
    kept = []

    for record in data.get("records", []):
        try:
            expires_at = parse_dt(record["expires_at"])
            if expires_at >= today:
                kept.append(record)
        except Exception:
            # 如果資料格式壞掉，保守起見先保留
            kept.append(record)

    data["records"] = kept
    return data


def enrich_records(data):
    today = datetime.now()

    folder_map = {
        folder["id"]: folder["name"]
        for folder in data.get("folders", [])
    }

    records = []
    expiring_soon = []

    for record in data.get("records", []):
        item = dict(record)

        try:
            expires_at = parse_dt(item["expires_at"])
            remaining_days = (expires_at.date() - today.date()).days
        except Exception:
            remaining_days = RETENTION_DAYS

        item["remaining_days"] = max(0, remaining_days)
        item["folder_name"] = folder_map.get(item.get("folder_id"), "未分類")

        if 0 <= remaining_days <= EXPIRING_SOON_DAYS:
            expiring_soon.append(item)

        records.append(item)

    records.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return records, expiring_soon


@app.after_request
def add_cors_headers(response):
    # 讓 5000 成熟度頁之後可以 POST 到 8000 儲存歷史紀錄
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.route("/")
def index():
    return render_template(
        "index.html",
        smell_url=SMELL_PAGE_URL,
        photo_url=PHOTO_PAGE_URL,
        history_url="/history"
    )


@app.route("/history")
def history_page():
    data = load_history()
    records, expiring_soon = enrich_records(data)

    return render_template(
        "history.html",
        folders=data.get("folders", []),
        records=records,
        expiring_soon=expiring_soon,
        retention_days=RETENTION_DAYS
    )


@app.route("/api/history", methods=["GET"])
def api_history():
    data = load_history()
    records, expiring_soon = enrich_records(data)

    return jsonify({
        "ok": True,
        "folders": data.get("folders", []),
        "records": records,
        "expiring_soon": expiring_soon
    })


@app.route("/api/history/folders", methods=["POST", "OPTIONS"])
def api_create_folder():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()

    if not name:
        return jsonify({"ok": False, "message": "資料夾名稱不可空白"}), 400

    data = load_history()

    for folder in data.get("folders", []):
        if folder["name"] == name:
            return jsonify({"ok": True, "folder": folder, "message": "資料夾已存在"})

    folder = {
        "id": "folder_" + uuid.uuid4().hex[:10],
        "name": name,
        "created_at": now_iso()
    }

    data.setdefault("folders", []).append(folder)
    save_history(data)

    return jsonify({"ok": True, "folder": folder})


@app.route("/api/history/save", methods=["POST", "OPTIONS"])
def api_save_record():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}

    filename = (payload.get("filename") or "").strip()
    folder_id = (payload.get("folder_id") or "default").strip()
    new_folder_name = (payload.get("new_folder_name") or "").strip()

    if not filename:
        filename = "鳳梨成熟度紀錄_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    data = load_history()

    # 如果使用者輸入新資料夾，就先建立資料夾
    if new_folder_name:
        existed = None
        for folder in data.get("folders", []):
            if folder["name"] == new_folder_name:
                existed = folder
                break

        if existed:
            folder_id = existed["id"]
        else:
            new_folder = {
                "id": "folder_" + uuid.uuid4().hex[:10],
                "name": new_folder_name,
                "created_at": now_iso()
            }
            data.setdefault("folders", []).append(new_folder)
            folder_id = new_folder["id"]

    folder_ids = {folder["id"] for folder in data.get("folders", [])}
    if folder_id not in folder_ids:
        folder_id = "default"

    created_at = datetime.now()
    expires_at = created_at + timedelta(days=RETENTION_DAYS)

    record = {
        "id": "record_" + uuid.uuid4().hex[:12],
        "filename": filename,
        "folder_id": folder_id,
        "created_at": created_at.isoformat(timespec="seconds"),
        "expires_at": expires_at.isoformat(timespec="seconds"),

        # 成熟度資料
        "ripeness_label": payload.get("ripeness_label", ""),
        "confidence": payload.get("confidence", ""),
        "stage": payload.get("stage", ""),
        "probabilities": payload.get("probabilities", {}),
        "features": payload.get("features", {}),

        # 保留原始文字，避免不同版本結果格式不一樣時資料不見
        "raw_text": payload.get("raw_text", ""),

        # 備註
        "note": payload.get("note", "")
    }

    data.setdefault("records", []).append(record)
    save_history(data)

    return jsonify({
        "ok": True,
        "message": "歷史紀錄已儲存",
        "record": record
    })


@app.route("/api/history/delete", methods=["POST", "OPTIONS"])
def api_delete_records():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    ids = set(payload.get("ids", []))

    data = load_history()
    before = len(data.get("records", []))
    data["records"] = [
        record for record in data.get("records", [])
        if record.get("id") not in ids
    ]
    after = len(data.get("records", []))

    save_history(data)

    return jsonify({
        "ok": True,
        "message": f"已刪除 {before - after} 筆紀錄"
    })


@app.route("/api/history/move", methods=["POST", "OPTIONS"])
def api_move_records():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    ids = set(payload.get("ids", []))
    target_folder_id = payload.get("target_folder_id", "default")

    data = load_history()

    folder_ids = {folder["id"] for folder in data.get("folders", [])}
    if target_folder_id not in folder_ids:
        return jsonify({"ok": False, "message": "目標資料夾不存在"}), 400

    moved = 0

    for record in data.get("records", []):
        if record.get("id") in ids:
            record["folder_id"] = target_folder_id
            moved += 1

    save_history(data)

    return jsonify({
        "ok": True,
        "message": f"已搬移 {moved} 筆紀錄"
    })
@app.route("/api/history/folders/delete", methods=["POST", "OPTIONS"])
def api_delete_folder():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    folder_id = payload.get("folder_id", "")

    if not folder_id:
        return jsonify({"ok": False, "message": "缺少資料夾 ID"}), 400

    if folder_id == "default":
        return jsonify({"ok": False, "message": "預設資料夾不能刪除"}), 400

    data = load_history()

    folder_name = None
    new_folders = []

    for folder in data.get("folders", []):
        if folder.get("id") == folder_id:
            folder_name = folder.get("name", "")
        else:
            new_folders.append(folder)

    if folder_name is None:
        return jsonify({"ok": False, "message": "找不到資料夾"}), 404

    before_count = len(data.get("records", []))

    data["folders"] = new_folders
    data["records"] = [
        record for record in data.get("records", [])
        if record.get("folder_id") != folder_id
    ]

    deleted_count = before_count - len(data["records"])

    save_history(data)

    return jsonify({
        "ok": True,
        "message": f"已刪除資料夾「{folder_name}」，並刪除其中 {deleted_count} 筆紀錄"
    })
@app.route("/api/history/folders/clear", methods=["POST", "OPTIONS"])
def api_clear_folder_records():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    folder_id = payload.get("folder_id", "")

    if not folder_id:
        return jsonify({"ok": False, "message": "缺少資料夾 ID"}), 400

    data = load_history()

    folder_map = {
        folder.get("id"): folder.get("name")
        for folder in data.get("folders", [])
    }

    if folder_id not in folder_map:
        return jsonify({"ok": False, "message": "找不到資料夾"}), 404

    before_count = len(data.get("records", []))

    data["records"] = [
        record for record in data.get("records", [])
        if record.get("folder_id") != folder_id
    ]

    deleted_count = before_count - len(data["records"])

    save_history(data)

    return jsonify({
        "ok": True,
        "message": f"已刪除「{folder_map[folder_id]}」內的 {deleted_count} 筆紀錄"
    })

def make_record_export_object(record, folder_name=""):
    return {
        "id": record.get("id"),
        "filename": record.get("filename"),
        "folder_id": record.get("folder_id"),
        "folder_name": folder_name,
        "created_at": record.get("created_at"),
        "expires_at": record.get("expires_at"),
        "ripeness_label": record.get("ripeness_label"),
        "confidence": record.get("confidence"),
        "stage": record.get("stage"),
        "probabilities": record.get("probabilities", {}),
        "features": record.get("features", {}),
        "note": record.get("note"),
        "raw_text": record.get("raw_text")
    }


def safe_filename(name):
    bad_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for ch in bad_chars:
        name = name.replace(ch, "_")
    return name.strip() or "history_record"


@app.route("/api/history/download", methods=["POST", "OPTIONS"])
def api_download_history():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}

    ids = set(payload.get("ids", []))
    folder_id = payload.get("folder_id", "")
    download_type = payload.get("type", "selected")

    data = load_history()

    folder_map = {
        folder.get("id"): folder.get("name")
        for folder in data.get("folders", [])
    }

    records = data.get("records", [])

    if download_type == "folder":
        if not folder_id:
            return jsonify({"ok": False, "message": "缺少資料夾 ID"}), 400

        selected_records = [
            record for record in records
            if record.get("folder_id") == folder_id
        ]

        base_name = safe_filename(folder_map.get(folder_id, "folder_records"))

    else:
        if not ids:
            return jsonify({"ok": False, "message": "請先選取要下載的紀錄"}), 400

        selected_records = [
            record for record in records
            if record.get("id") in ids
        ]

        base_name = "selected_history_records"

    if not selected_records:
        return jsonify({"ok": False, "message": "沒有可下載的紀錄"}), 404

    # 只有一筆：下載單一 JSON
    if len(selected_records) == 1:
        record = selected_records[0]
        folder_name = folder_map.get(record.get("folder_id"), "未分類")
        export_obj = make_record_export_object(record, folder_name)

        json_bytes = json.dumps(
            export_obj,
            ensure_ascii=False,
            indent=2
        ).encode("utf-8")

        file_obj = io.BytesIO(json_bytes)
        filename = safe_filename(record.get("filename", "history_record")) + ".json"

        return send_file(
            file_obj,
            as_attachment=True,
            download_name=filename,
            mimetype="application/json"
        )

    # 多筆：下載 ZIP
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        summary = {
            "exported_at": now_iso(),
            "count": len(selected_records),
            "records": []
        }

        for record in selected_records:
            folder_name = folder_map.get(record.get("folder_id"), "未分類")
            export_obj = make_record_export_object(record, folder_name)

            filename = safe_filename(record.get("filename", record.get("id", "record"))) + ".json"
            zf.writestr(
                filename,
                json.dumps(export_obj, ensure_ascii=False, indent=2)
            )

            summary["records"].append({
                "id": record.get("id"),
                "filename": record.get("filename"),
                "folder_name": folder_name,
                "created_at": record.get("created_at"),
                "ripeness_label": record.get("ripeness_label"),
                "confidence": record.get("confidence")
            })

        zf.writestr(
            "_summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2)
        )

    zip_buffer.seek(0)

    zip_name = safe_filename(base_name) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip"

    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name=zip_name,
        mimetype="application/zip"
    )
def safe_report_filename(name):
    bad_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    name = str(name or "history_record")
    for ch in bad_chars:
        name = name.replace(ch, "_")
    return name.strip() or "history_record"


def build_history_record_html_report(record, folder_name=""):
    filename = html.escape(str(record.get("filename", "")))
    folder_name = html.escape(str(folder_name or "未分類"))
    ripeness_label = html.escape(str(record.get("ripeness_label", "")))
    confidence = html.escape(str(record.get("confidence", "")))
    created_at = html.escape(str(record.get("created_at", "")))
    expires_at = html.escape(str(record.get("expires_at", "")))
    note = html.escape(str(record.get("note", "")))
    raw_text = html.escape(str(record.get("raw_text", "")))

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>{filename}</title>
<style>
body {{
    font-family: "Microsoft JhengHei", "Noto Sans TC", Arial, sans-serif;
    margin: 0;
    background: #f4f6ec;
    color: #102d1b;
}}
.container {{
    max-width: 960px;
    margin: 36px auto;
    background: white;
    border-radius: 24px;
    padding: 34px;
    box-shadow: 0 20px 60px rgba(38, 68, 40, 0.14);
}}
h1 {{
    margin: 0 0 8px;
    font-size: 30px;
}}
.subtitle {{
    color: #637267;
    margin-bottom: 28px;
}}
.grid {{
    display: grid;
    grid-template-columns: 180px 1fr;
    gap: 12px;
    border-top: 1px solid #e5e7eb;
    padding-top: 18px;
}}
.label {{
    font-weight: 900;
    color: #245936;
}}
.value {{
    color: #102d1b;
}}
.section {{
    margin-top: 28px;
}}
pre {{
    background: #0f172a;
    color: #d1fae5;
    padding: 18px;
    border-radius: 16px;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.7;
    max-height: 520px;
    overflow: auto;
}}
.badge {{
    display: inline-block;
    padding: 8px 12px;
    border-radius: 999px;
    background: #eef5e8;
    color: #245936;
    font-weight: 900;
}}
</style>
</head>
<body>
<div class="container">
    <div class="badge">Pineapple History Report</div>
    <h1>{filename}</h1>
    <div class="subtitle">鳳梨成熟度辨識歷史紀錄報告</div>

    <div class="grid">
        <div class="label">資料夾</div>
        <div class="value">{folder_name}</div>

        <div class="label">成熟度結果</div>
        <div class="value">{ripeness_label}</div>

        <div class="label">信心分數</div>
        <div class="value">{confidence}</div>

        <div class="label">建立時間</div>
        <div class="value">{created_at}</div>

        <div class="label">到期時間</div>
        <div class="value">{expires_at}</div>

        <div class="label">備註</div>
        <div class="value">{note}</div>
    </div>

    <div class="section">
        <h2>原始輸出資料</h2>
        <pre>{raw_text}</pre>
    </div>
</div>
</body>
</html>
"""


def build_history_summary_csv(records, folder_map):
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "檔案名稱",
        "資料夾",
        "成熟度結果",
        "信心分數",
        "建立時間",
        "到期時間",
        "備註"
    ])

    for record in records:
        writer.writerow([
            record.get("filename", ""),
            folder_map.get(record.get("folder_id"), "未分類"),
            record.get("ripeness_label", ""),
            record.get("confidence", ""),
            record.get("created_at", ""),
            record.get("expires_at", ""),
            record.get("note", "")
        ])

    return output.getvalue().encode("utf-8-sig")


@app.route("/api/history/download_report", methods=["POST", "OPTIONS"])
def api_download_history_report():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}

    ids = set(payload.get("ids", []))
    folder_id = payload.get("folder_id", "")
    download_type = payload.get("type", "selected")

    data = load_history()

    folder_map = {
        folder.get("id"): folder.get("name")
        for folder in data.get("folders", [])
    }

    records = data.get("records", [])

    if download_type == "folder":
        if not folder_id:
            return jsonify({"ok": False, "message": "缺少資料夾 ID"}), 400

        selected_records = [
            record for record in records
            if record.get("folder_id") == folder_id
        ]

        base_name = safe_report_filename(folder_map.get(folder_id, "folder_records"))

    else:
        if not ids:
            return jsonify({"ok": False, "message": "請先選取要下載的紀錄"}), 400

        selected_records = [
            record for record in records
            if record.get("id") in ids
        ]

        base_name = "selected_history_records"

    if not selected_records:
        return jsonify({"ok": False, "message": "沒有可下載的紀錄"}), 404

    # 單筆選取下載：直接下載 HTML
    if len(selected_records) == 1 and download_type != "folder":
        record = selected_records[0]
        folder_name = folder_map.get(record.get("folder_id"), "未分類")

        html_content = build_history_record_html_report(record, folder_name).encode("utf-8")
        file_obj = io.BytesIO(html_content)

        filename = safe_report_filename(record.get("filename", "history_record")) + ".html"

        return send_file(
            file_obj,
            as_attachment=True,
            download_name=filename,
            mimetype="text/html"
        )

    # 多筆或資料夾下載：ZIP，裡面有 summary.csv 和每筆 HTML
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("summary.csv", build_history_summary_csv(selected_records, folder_map))

        for record in selected_records:
            folder_name = folder_map.get(record.get("folder_id"), "未分類")
            report_html = build_history_record_html_report(record, folder_name)

            report_name = safe_report_filename(record.get("filename", record.get("id", "record"))) + ".html"
            zf.writestr(report_name, report_html)

    zip_buffer.seek(0)

    zip_name = safe_report_filename(base_name) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip"

    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name=zip_name,
        mimetype="application/zip"
    )
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
