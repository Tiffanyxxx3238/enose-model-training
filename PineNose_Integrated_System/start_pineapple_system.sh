#!/bin/bash
# PineNose Raspberry Pi 一鍵啟動腳本
# 沿用原本三個服務，更新成熟度辨識 Port 為 5051

echo "Starting PineNose System..."

LOG_DIR="$HOME/pineapple_logs"
mkdir -p "$LOG_DIR"

start_service() {
    local name="$1"
    local port="$2"
    local workdir="$3"
    local logfile="$4"
    shift 4

    echo
    echo "[$name] Checking port $port..."

    if ss -ltnH "( sport = :$port )" | grep -q LISTEN; then
        echo "[OK] $name already running on port $port"
        return 0
    fi

    if [ ! -d "$workdir" ]; then
        echo "[ERROR] Directory not found: $workdir"
        return 1
    fi

    (
        cd "$workdir" || exit 1
        nohup "$@" > "$LOG_DIR/$logfile" 2>&1 < /dev/null &
    )

    sleep 3

    if ss -ltnH "( sport = :$port )" | grep -q LISTEN; then
        echo "[OK] $name started on port $port"
    else
        echo "[ERROR] $name failed to start"
        echo "Check log: $LOG_DIR/$logfile"
        return 1
    fi
}

# 1. 成熟度辨識：使用昨天驗證的正式版
start_service \
    "Ripeness Detector" \
    5051 \
    "$HOME/pineapple" \
    "ripeness.log" \
    "$HOME/pineapple/.venv/bin/python" \
    -c 'from app_local import app; app.run(host="0.0.0.0", port=5051, debug=False, use_reloader=False)'

# 2. 照片辨識 Gateway：維持原本的 app_gateway.py
if [ -x "$HOME/pineapple_app_gateway/.venv/bin/python" ]; then
    GATEWAY_PYTHON="$HOME/pineapple_app_gateway/.venv/bin/python"
else
    GATEWAY_PYTHON="python3"
fi

start_service \
    "Photo Gateway" \
    5002 \
    "$HOME/pineapple_app_gateway" \
    "photo_gateway.log" \
    "$GATEWAY_PYTHON" \
    -c 'from app_gateway import app; app.run(host="0.0.0.0", port=5002, debug=False, use_reloader=False)'

# 3. 整合網頁：維持原本 app.py 與歷史紀錄功能
start_service \
    "Unified Web" \
    8000 \
    "$HOME/pineapple_unified_web" \
    "unified_web.log" \
    "$HOME/pineapple_unified_web/.venv/bin/python" \
    -c 'from app import app; app.run(host="0.0.0.0", port=8000, debug=False, use_reloader=False)'

echo
echo "========================================"
echo "PineNose service status:"
ss -ltn | grep -E ':(5002|5051|8000)\b' || true

echo
echo "Ripeness: http://172.20.10.3:5051"
echo "Photo:    http://172.20.10.3:5002"
echo "Unified:  http://172.20.10.3:8000"
echo "========================================"
