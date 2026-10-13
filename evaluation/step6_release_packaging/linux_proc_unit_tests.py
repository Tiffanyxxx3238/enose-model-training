"""
Step 6A：服務管理程式 Linux 程序身分判斷的單元測試（合成 /proc 目錄；本機是 Windows，無法執行真正的 Linux 路徑）。
驗證：存活判斷、殭屍程序、starttime（PID 重用）、cmdline 身分比對（runner 路徑＋--service）。
"""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "pinenose_release/ops/pinenose_service.py"
FAKE = HERE / "_tmp_fake_proc"
if FAKE.exists():
    shutil.rmtree(FAKE)


def mkproc(pid, state, start, cmd):
    d = FAKE / str(pid)
    d.mkdir(parents=True)
    fields = [state] + ["0"] * 18 + [str(start)] + ["0"] * 10          # 欄位 3..：state、…、第 22 欄 starttime
    (d / "stat").write_text(f"{pid} (python3 (x)) " + " ".join(fields), encoding="utf-8")   # comm 含括號與空白
    (d / "cmdline").write_bytes(b"\0".join(c.encode() for c in cmd) + b"\0")


spec = importlib.util.spec_from_file_location("mgr", str(SRC))
mgr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mgr)
mgr.PROC_ROOT = FAKE
mgr.proc_info = mgr._proc_info_linux
mgr.os = type("o", (), {**{k: getattr(__import__("os"), k) for k in ("path", "environ", "getpid")}, "name": "posix"})   # 走 Linux 分支

RUNNER = "/opt/pinenose/releases/rc/ops/pinenose_service.py"
mkproc(100, "S", 5000, ["/opt/venv/bin/python", RUNNER, "run", "--service", "gateway", "--profile-file", "/opt/pinenose/site/profile.json"])
mkproc(101, "S", 7000, ["/usr/bin/python3", "/home/x/other/app.py"])                       # 外部同名程序
mkproc(102, "Z", 5100, ["/opt/venv/bin/python", RUNNER, "run", "--service", "web"])          # 殭屍
rec = {"pid": 100, "create": "5000", "service": "gateway", "runner": RUNNER, "python": "/opt/venv/bin/python"}
rows = []


def t(tid, name, got, want):
    rows.append({"id": tid, "test": name, "got": got, "expected": want, "verdict": "PASS" if got == want else "FAIL"})
    print(f"[{'PASS' if got == want else 'FAIL'}] {tid} {name}: {got}")


t("L01", "own runner process, same starttime and cmdline", mgr.owned(rec)[0], "owned")
t("L02", "PID reused by another program (different starttime)", mgr.owned({**rec, "pid": 101, "create": "5000"})[0], "pid_reused")
t("L03", "same starttime but cmdline is a different program", mgr.owned({**rec, "pid": 101, "create": "7000"})[0], "pid_reused")
t("L04", "process gone", mgr.owned({**rec, "pid": 999})[0], "dead")
t("L05", "zombie process treated as not running", mgr.owned({**rec, "pid": 102, "create": "5100", "service": "web"})[0], "dead")
t("L06", "service name must match (--service web vs gateway)", mgr.owned({**rec, "service": "web"})[0], "pid_reused")
shutil.rmtree(FAKE)
pd.DataFrame(rows).to_csv(HERE / "logs/linux_proc_unit_test_results.csv", index=False, encoding="utf-8-sig")
sys.exit(0 if all(r["verdict"] == "PASS" for r in rows) else 1)
