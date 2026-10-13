#!/bin/bash
# 這個檔案是用來一次啟動鳳梨智慧系統的三個主要網頁服務

# 顯示啟動提示，讓使用者知道系統開始啟動
echo "🍍 Starting Pineapple Smart System..."

# 先建立 logs 資料夾，方便之後查看每個服務的執行紀錄或錯誤訊息
mkdir -p ~/pineapple_logs

# 啟動第一個服務：鳳梨氣味成熟度辨識系統
echo "1. Starting ripeness detector..."

# 進入成熟度辨識系統所在的資料夾
cd ~/pineapple

# 啟動這個資料夾裡的 Python 虛擬環境
source .venv/bin/activate

# 用 nohup 在背景執行 app_local.py
# 執行輸出和錯誤訊息都會寫到 ripeness.log
nohup python app_local.py > ~/pineapple_logs/ripeness.log 2>&1 &

# 離開虛擬環境，避免影響後面其他服務
deactivate

# 等 2 秒，讓上一個服務有時間啟動
sleep 2

# 啟動第二個服務：照片辨識 gateway
echo "2. Starting photo gateway..."

# 進入照片 gateway 的資料夾
cd ~/pineapple_app_gateway

# 如果這個資料夾裡面有 .venv，就使用它自己的虛擬環境
if [ -d ".venv" ]; then
    # 啟動照片 gateway 的虛擬環境
    source .venv/bin/activate

    # 在背景執行 app_gateway.py
    # 輸出和錯誤訊息會寫到 photo_gateway.log
    nohup python app_gateway.py > ~/pineapple_logs/photo_gateway.log 2>&1 &

    # 執行完後離開虛擬環境
    deactivate
else
    # 如果沒有 .venv，就直接用系統的 python3 執行
    nohup python3 app_gateway.py > ~/pineapple_logs/photo_gateway.log 2>&1 &
fi

# 等 2 秒，讓照片 gateway 有時間啟動
sleep 2

# 啟動第三個服務：整合主網頁
echo "3. Starting unified web..."

# 進入整合網頁資料夾
cd ~/pineapple_unified_web

# 啟動整合網頁自己的 Python 虛擬環境
source .venv/bin/activate

# 在背景執行 app.py
# 輸出和錯誤訊息會寫到 unified_web.log
nohup python app.py > ~/pineapple_logs/unified_web.log 2>&1 &

# 離開虛擬環境
deactivate

# 等 2 秒，讓整合網頁完成啟動
sleep 2

# 顯示分隔線，讓終端機畫面比較清楚
echo "========================================"

# 顯示所有服務已經啟動完成
echo "All Raspberry Pi services started!"

# 空一行，讓網址比較好看
echo ""

# 顯示成熟度辨識頁網址
echo "成熟度辨識頁： http://192.168.0.152:5000"

# 顯示照片呈現頁網址
echo "照片呈現頁：   http://192.168.0.152:5002"

# 顯示整合主網頁網址
echo "整合主網頁：   http://192.168.0.152:8000"

# 顯示結尾分隔線
echo "========================================"