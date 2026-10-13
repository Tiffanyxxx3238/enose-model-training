from pathlib import Path
from datetime import datetime

import requests
from flask import Flask, request, jsonify, render_template_string, send_from_directory


# =========================
# 基本設定
# =========================

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Windows 端三階段模型 Server
MODEL_SERVER_URL = "http://172.20.10.10:5001/predict"

app = Flask(__name__)


# =========================
# HTML 網頁模板
# =========================

HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
    <meta charset="UTF-8">
    <title>鳳梨照片辨識系統</title>

    <style>
        body {
            margin: 0;
            font-family: "Microsoft JhengHei", Arial, sans-serif;
            background-color: #fffaf0;
            color: #2d2d2d;
            text-align: center;
        }

        .container {
            max-width: 1000px;
            margin: 0 auto;
            padding: 35px 20px;
        }

        h1 {
            color: #1f6f3d;
            font-size: 36px;
            margin-bottom: 10px;
        }

        .subtitle {
            font-size: 24px;
            color: #555;
            margin-bottom: 10px;
        }

        .description {
            font-size: 20px;
            color: #666;
            margin-bottom: 35px;
        }

        .upload-box {
            border-top: 3px dashed #f0b52d;
            border-bottom: 3px dashed #f0b52d;
            padding: 35px 20px;
            margin-top: 20px;
            background-color: #fff7e8;
        }

        .upload-box h2 {
            font-size: 24px;
            margin-bottom: 25px;
        }

        input[type="file"] {
            font-size: 18px;
            margin-bottom: 25px;
        }

        button {
            background-color: #2f9b4f;
            color: white;
            border: none;
            border-radius: 16px;
            padding: 16px 42px;
            font-size: 24px;
            font-weight: bold;
            cursor: pointer;
        }

        button:hover {
            background-color: #267d40;
        }

        .preview-area {
            margin-top: 25px;
        }

        .preview-title {
            font-size: 20px;
            font-weight: bold;
            margin-bottom: 12px;
            color: #444;
        }

        #previewImage {
            display: none;
            max-width: 380px;
            max-height: 290px;
            border-radius: 14px;
            border: 3px solid #e5c46b;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18);
            object-fit: contain;
            background-color: white;
        }

        .result-box {
            margin-top: 35px;
            padding: 28px;
            background-color: #ffffff;
            border-radius: 18px;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
            text-align: left;
        }

        .result-title {
            font-size: 28px;
            font-weight: bold;
            color: #1f6f3d;
            text-align: center;
            margin-bottom: 22px;
        }

        .result-content {
            display: flex;
            gap: 28px;
            align-items: flex-start;
            justify-content: center;
            flex-wrap: wrap;
        }

        .result-image {
            max-width: 350px;
            max-height: 300px;
            border-radius: 14px;
            border: 3px solid #e5c46b;
            object-fit: contain;
            background-color: white;
        }

        .result-text {
            min-width: 360px;
            max-width: 520px;
            font-size: 18px;
            line-height: 1.8;
        }

        .stage-card {
            margin-bottom: 15px;
            padding: 14px 16px;
            border-radius: 14px;
            background-color: #f8f8f8;
            border-left: 6px solid #999;
        }

        .stage-pass {
            border-left-color: #2f9b4f;
            background-color: #eefaf1;
        }

        .stage-fail {
            border-left-color: #c0392b;
            background-color: #fff0ee;
        }

        .stage-warn {
            border-left-color: #d97b00;
            background-color: #fff6e6;
        }

        .stage-title {
            font-size: 20px;
            font-weight: bold;
            margin-bottom: 6px;
        }

        .main-result {
            font-size: 25px;
            font-weight: bold;
            color: #d97b00;
            margin-top: 8px;
        }

        .prob-list {
            margin-top: 16px;
            padding-top: 12px;
            border-top: 1px solid #ddd;
        }

        .warning {
            margin-top: 10px;
            color: #c0392b;
            font-weight: bold;
        }

        .success {
            color: #1f6f3d;
            font-weight: bold;
        }

        .orange {
            color: #d97b00;
            font-weight: bold;
        }

        .small-info {
            color: #666;
            font-size: 15px;
            margin-top: 4px;
        }

        .note {
            color: #555;
            font-size: 15px;
            margin-top: 8px;
        }

        .error {
            margin-top: 25px;
            color: #c0392b;
            font-size: 20px;
            font-weight: bold;
        }
    </style>
</head>

<body>
    <div class="container">
        <h1>🍍 鳳梨照片辨識系統</h1>
        <div class="subtitle">App 模擬網頁版</div>
        <div class="description">
            上傳照片後，系統會依序判斷：照片是否有內容、是否為鳳梨、以及鳳梨品種。
        </div>

        <div class="upload-box">
            <h2>請選擇一張照片</h2>

            <form method="POST" action="/web/predict" enctype="multipart/form-data">
                <input type="file" name="image" accept="image/*" required onchange="previewFile(event)">
                <br>

                <div class="preview-area">
                    <div class="preview-title">照片預覽</div>
                    <img id="previewImage">
                </div>

                <br>
                <button type="submit">開始辨識</button>
            </form>
        </div>

        {% if error %}
        <div class="error">
            {{ error }}
        </div>
        {% endif %}

        {% if result %}
        <div class="result-box">
            <div class="result-title">辨識結果</div>

            <div class="result-content">
                <div>
                    <img class="result-image" src="{{ image_url }}">
                </div>

                <div class="result-text">

                    <!-- Stage 1：照片內容檢查 -->
                    <div class="stage-card {% if result.get('has_content') %}stage-pass{% else %}stage-fail{% endif %}">
                        <div class="stage-title">階段一：照片內容檢查</div>

                        {% if result.get("has_content") %}
                            <div class="success">通過：照片中有明顯內容</div>
                        {% else %}
                            <div class="warning">未通過：{{ result.get("message") }}</div>
                        {% endif %}

                        {% if result.get("content_check") %}
                            <div class="small-info">
                                亮度平均：{{ "%.2f"|format(result["content_check"].get("mean_brightness", 0)) }}，
                                邊緣比例：{{ "%.4f"|format(result["content_check"].get("edge_ratio", 0)) }}
                            </div>
                        {% endif %}
                    </div>

                    <!-- Stage 2：鳳梨偵測 -->
                    {% if result.get("pred_zh_name") == "偵測到多顆鳳梨" %}
                    <div class="stage-card stage-warn">
                    {% elif result.get("is_pineapple") %}
                    <div class="stage-card stage-pass">
                    {% else %}
                    <div class="stage-card stage-fail">
                    {% endif %}
                        <div class="stage-title">階段二：鳳梨偵測</div>

                        {% if result.get("pred_zh_name") == "偵測到多顆鳳梨" %}
                            <div class="orange">偵測到多顆鳳梨</div>
                            <div>{{ result.get("message") }}</div>
                            <div>偵測數量：{{ result.get("num_boxes", 0) }}</div>
                            <div>最高偵測信心：{{ "%.2f"|format(result.get("det_confidence", 0) * 100) }}%</div>

                        {% elif result.get("is_pineapple") %}
                            <div class="success">通過：已偵測到單顆鳳梨</div>
                            <div>偵測數量：{{ result.get("num_boxes", 1) }}</div>
                            <div>鳳梨偵測信心：{{ "%.2f"|format(result.get("det_confidence", 0) * 100) }}%</div>

                        {% else %}
                            <div class="warning">{{ result.get("pred_zh_name", "未偵測到鳳梨") }}</div>
                            <div>{{ result.get("message") }}</div>
                        {% endif %}
                    </div>

                    <!-- Stage 3：品種分類 -->
                    {% if result.get("stage") == 3 and result.get("is_pineapple") and result.get("pred_zh_name") != "偵測到多顆鳳梨" %}
                    <div class="stage-card stage-pass">
                        <div class="stage-title">階段三：鳳梨品種分類</div>

                        <div class="main-result">
                            預測品種：{{ result["pred_zh_name"] }}
                        </div>

                        <div>英文類別：{{ result["pred_class"] }}</div>
                        <div>品種信心分數：{{ "%.2f"|format(result["confidence"] * 100) }}%</div>

                        {% if result["low_confidence"] %}
                        <div class="warning">
                            提醒：模型信心偏低，建議重新拍攝或人工確認。
                        </div>
                        {% endif %}

                        <div class="prob-list">
                            <strong>各類別機率：</strong><br>
                            {% for item in result["all_probs"] %}
                                {{ item["zh_name"] }}（{{ item["class"] }}）：
                                {{ "%.2f"|format(item["probability"] * 100) }}%<br>
                            {% endfor %}
                        </div>

                        <div class="note">
                            說明：目前系統會先用 YOLO 偵測鳳梨位置，再由分類模型進行品種判斷。
                        </div>
                    </div>

                    {% elif result.get("pred_zh_name") == "偵測到多顆鳳梨" %}
                    <div class="stage-card stage-warn">
                        <div class="stage-title">階段三：鳳梨品種分類</div>
                        <div class="orange">未進行品種分類：偵測到多顆鳳梨，請一次拍攝一顆。</div>
                    </div>

                    {% else %}
                    <div class="stage-card stage-fail">
                        <div class="stage-title">階段三：鳳梨品種分類</div>
                        <div class="warning">未進行品種分類：前一階段未通過。</div>
                    </div>
                    {% endif %}

                </div>
            </div>
        </div>
        {% endif %}
    </div>

    <script>
        function previewFile(event) {
            const file = event.target.files[0];
            const preview = document.getElementById("previewImage");

            if (file) {
                const reader = new FileReader();

                reader.onload = function(e) {
                    preview.src = e.target.result;
                    preview.style.display = "inline-block";
                };

                reader.readAsDataURL(file);
            } else {
                preview.src = "";
                preview.style.display = "none";
            }
        }
    </script>
</body>
</html>
"""


# =========================
# 上傳圖片讀取路由
# =========================

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# =========================
# 首頁：網頁版
# =========================

@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_PAGE, result=None, error=None, image_url=None)


# =========================
# API 狀態測試
# =========================

@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "status": "ok",
        "message": "Raspberry Pi gateway is running.",
        "model_server": MODEL_SERVER_URL,
    })


# =========================
# 共用：把圖片轉送到 Windows 模型 Server
# =========================

def send_to_model_server(save_path, filename, content_type="image/jpeg"):
    with open(save_path, "rb") as f:
        files = {
            "image": (filename, f, content_type)
        }

        response = requests.post(
            MODEL_SERVER_URL,
            files=files,
            timeout=30
        )

    if response.status_code != 200:
        raise RuntimeError(response.text)

    return response.json()


# =========================
# 網頁版上傳辨識
# =========================

@app.route("/web/predict", methods=["POST"])
def web_predict():
    if "image" not in request.files:
        return render_template_string(
            HTML_PAGE,
            result=None,
            error="沒有收到圖片，請重新選擇檔案。",
            image_url=None
        )

    image_file = request.files["image"]

    if image_file.filename == "":
        return render_template_string(
            HTML_PAGE,
            result=None,
            error="尚未選擇圖片。",
            image_url=None
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{image_file.filename}"
    save_path = UPLOAD_DIR / filename
    image_file.save(save_path)

    try:
        result_json = send_to_model_server(
            save_path,
            filename,
            image_file.content_type or "image/jpeg"
        )

        image_url = f"/uploads/{filename}"

        return render_template_string(
            HTML_PAGE,
            result=result_json,
            error=None,
            image_url=image_url
        )

    except Exception as e:
        return render_template_string(
            HTML_PAGE,
            result=None,
            error=f"辨識失敗：{str(e)}",
            image_url=f"/uploads/{filename}"
        )


# =========================
# API：手機 App / curl 用
# =========================

@app.route("/variety/predict", methods=["POST"])
def variety_predict():
    if "image" not in request.files:
        return jsonify({
            "status": "error",
            "message": "No image uploaded. Field name must be image."
        }), 400

    image_file = request.files["image"]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{image_file.filename}"
    save_path = UPLOAD_DIR / filename
    image_file.save(save_path)

    try:
        result = send_to_model_server(
            save_path,
            filename,
            image_file.content_type or "image/jpeg"
        )

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": "Failed to connect to model server.",
            "detail": str(e),
        }), 500

    return jsonify({
        "status": "ok",
        "source": "raspberry_pi_gateway",
        "saved_image": str(save_path),
        "result": result,
    })


# =========================
# Main
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
