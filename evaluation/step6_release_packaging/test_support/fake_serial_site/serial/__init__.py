"""
測試專用的假 pyserial（Step 6A）— 只透過 PYTHONPATH 注入到「解壓後發布套件」的服務程序中；不屬於發布套件。

- 每次 Serial() 開啟時讀取 FAKE_SERIAL_CONTROL 指向的 JSON：
    {"lines": [...CSV 列...], "header": true, "hang_after": null, "raise_on_open": false}
- 虛擬 1 Hz 時鐘：本程序的 time.time() 只在讀到一列時前進 1 秒（讓 30 秒取樣在測試中立即完成）。
- hang_after：讀到第 N 次後阻塞，直到 close()（模擬無法自行返回的序列埠讀取）。
- 每次開啟／關閉都附加一行到 FAKE_SERIAL_LOG（供測試確認序列埠確實被關閉）。
"""
import json
import os
import threading
import time as _time

HEADER = "timestamp_ms,timestamp_s,MQ2_raw,MQ3_raw,MQ9_raw,MQ135_raw,TGS2602_raw,Temp_C,Humidity_pct,Pressure_hPa"
_lock = threading.Lock()
_vt = [_time.time()]


def _virtual_time():
    with _lock:
        return _vt[0]


_time.time = _virtual_time          # 只影響載入本模組的測試程序


def _log(event):
    p = os.environ.get("FAKE_SERIAL_LOG")
    if p:
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"pid": os.getpid(), "event": event}) + "\n")


class SerialException(OSError):
    pass


class Serial:
    def __init__(self, port, baud=115200, timeout=1, **kw):
        with open(os.environ["FAKE_SERIAL_CONTROL"], encoding="utf-8") as fh:
            ctl = json.load(fh)
        if ctl.get("raise_on_open"):
            raise SerialException("could not open port (fake)")
        self.buf = ([HEADER] if ctl.get("header", True) else []) + list(ctl.get("lines", []))
        self.hang_after = ctl.get("hang_after")
        self.calls = 0
        self.closed = threading.Event()
        self.port = port
        _log("open")

    def readline(self):
        self.calls += 1
        if self.closed.is_set():
            raise SerialException("port closed")
        if self.hang_after is not None and self.calls > self.hang_after:
            self.closed.wait(600)
            raise SerialException("read aborted by close()")
        with _lock:
            _vt[0] += 1.0
        return (self.buf.pop(0) + "\n").encode() if self.buf else b""

    def reset_input_buffer(self):
        pass

    def close(self):
        if not self.closed.is_set():
            self.closed.set()
            _log("close")
