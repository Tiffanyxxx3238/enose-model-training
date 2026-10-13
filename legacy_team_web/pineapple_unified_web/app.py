from flask import Flask, render_template

app = Flask(__name__)

# 目前的 Raspberry Pi IP 是 192.168.0.152
# 氣味成熟度頁面：樹莓派本機 port 5000
# 照片品種辨識呈現頁：樹莓派本機 port 5002
SMELL_PAGE_URL = "http://192.168.0.152:5000"
PHOTO_PAGE_URL = "http://192.168.0.152:5002"


@app.route("/")
def index():
    return render_template(
        "index.html",
        smell_url=SMELL_PAGE_URL,
        photo_url=PHOTO_PAGE_URL
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
