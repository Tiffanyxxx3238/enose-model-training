#!/bin/bash
# 這個檔案是用來停止鳳梨智慧系統相關網頁服務的 shell script

# 顯示提示文字，讓使用者知道目前正在停止系統
echo "Stopping Pineapple Smart System..."

# 停止成熟度辨識的 Flask / 本機測試程式
pkill -f "app_local.py"

# 停止 Raspberry Pi gateway 程式，通常負責和 App 或其他服務溝通
pkill -f "app_gateway.py"

# 停止整合網頁相關的 process
pkill -f "pineapple_unified_web"

# 停止名稱為 app.py 的 Flask 主程式
pkill -f "app.py"

# 顯示完成訊息，代表相關 Python 服務已經送出停止指令
echo "All related Python services stopped."