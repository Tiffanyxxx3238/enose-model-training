#!/bin/bash
# PineNose Raspberry Pi 一鍵停止腳本
# 僅停止本專題的三個 Flask 服務，不刪除資料或模型

echo "Stopping PineNose System..."

stop_service() {
    local name="$1"
    local port="$2"
    local workdir="$3"
    local module="$4"
    local pids pid cmd cwd

    echo
    echo "[$name] Checking port $port..."

    pids=$(sudo ss -ltnpH "( sport = :$port )" 2>/dev/null \
        | grep -oE 'pid=[0-9]+' \
        | cut -d= -f2 \
        | sort -u)

    if [ -z "$pids" ]; then
        echo "[OK] $name is already stopped"
        return 0
    fi

    for pid in $pids; do
        if [ ! -d "/proc/$pid" ]; then
            continue
        fi

        cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
        cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null)

        if [ "$cwd" != "$workdir" ]; then
            echo "[SKIP] PID $pid is not running from $workdir"
            continue
        fi

        if [[ "$cmd" != *"$module"* ]]; then
            echo "[SKIP] PID $pid does not match $module"
            continue
        fi

        echo "[STOP] $name (PID $pid)"
        kill -TERM "$pid" 2>/dev/null || {
            echo "[ERROR] Unable to stop PID $pid"
            continue
        }
    done

    for i in 1 2 3 4 5; do
        if ! ss -ltnH "( sport = :$port )" | grep -q LISTEN; then
            echo "[OK] $name stopped"
            return 0
        fi
        sleep 1
    done

    echo "[WARN] Port $port is still listening"
    return 1
}

stop_service \
    "Ripeness Detector" \
    5051 \
    "$HOME/pineapple" \
    "app_local"

stop_service \
    "Photo Gateway" \
    5002 \
    "$HOME/pineapple_app_gateway" \
    "app_gateway"

stop_service \
    "Unified Web" \
    8000 \
    "$HOME/pineapple_unified_web" \
    "from app import app"

echo
echo "========================================"
echo "Remaining PineNose ports:"
ss -ltn | grep -E ':(5002|5051|8000)\b' || echo "No PineNose ports listening"
echo "========================================"
