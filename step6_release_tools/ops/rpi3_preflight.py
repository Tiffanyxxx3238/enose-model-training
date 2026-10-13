#!/usr/bin/env python3
"""
PineNose 部署前唯讀預檢（Step 6A）— 在目標機器（Raspberry Pi 3）上執行

只讀取資訊並回報：作業系統、CPU 架構、Python、已安裝套件版本、記憶體、磁碟、必要檔案、套件完整性、設定齊全與否、
序列埠權限。不安裝套件、不修改系統設定、不開啟序列埠、不連線任何網路或 SSH、不輸出任何密碼或設定內容中的秘密。

用法：python3 ops/rpi3_preflight.py [--profile-file <site>/site/profile.json] [--json out.json]
結束碼：0 沒有 FAIL；1 有 FAIL；（WARN／UNVERIFIED 不影響結束碼）
"""
import sys
sys.dont_write_bytecode = True          # 不在發布目錄寫入 __pycache__（套件目錄保持唯讀、與 SHA256SUMS 一致）
import argparse
import glob
import importlib.metadata as md
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parent
ROOT = OPS.parent
CHECKS = []
MIN_FREE_MB_DATA = 500
MIN_MEM_AVAILABLE_MB = 350        # 依 x86 代理量測：Gateway＋模型約 170 MB、web 子程序推論約同量（見 runtime_requirements.md）


def add(item, status, detail):
    CHECKS.append({"item": item, "status": status, "detail": str(detail)})


def os_release():
    p = Path("/etc/os-release")
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v.strip('"')
    return out


def mem_available_mb():
    p = Path("/proc/meminfo")
    if p.exists():
        m = re.search(r"MemAvailable:\s+(\d+) kB", p.read_text())
        t = re.search(r"MemTotal:\s+(\d+) kB", p.read_text())
        return (int(m.group(1)) / 1024 if m else None), (int(t.group(1)) / 1024 if t else None)
    if os.name == "nt":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong),
                        ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        s = MS()
        s.dwLength = ctypes.sizeof(s)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        return s.ullAvailPhys / 2**20, s.ullTotalPhys / 2**20
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile-file", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    # 1. 作業系統與架構
    osr = os_release()
    machine = platform.machine()
    add("os", "INFO", f"{platform.system()} {platform.release()} {osr.get('PRETTY_NAME', '')}".strip())
    if machine == "aarch64":
        add("cpu_arch", "PASS", "aarch64（64-bit）：PyPI 有全部釘選套件的 manylinux aarch64 wheel（見 rpi3_compatibility_matrix.csv）")
    elif machine in ("armv7l", "armv6l"):
        add("cpu_arch", "WARN", f"{machine}（32-bit）：科學套件只能用 piwheels 社群建置；64-bit 建立的模型 pickle 在 32-bit 載入未經驗證 — UNVERIFIED — REQUIRES TARGET ENVIRONMENT CHECK")
    else:
        add("cpu_arch", "INFO", f"{machine}：不是 Raspberry Pi 的架構（這次執行不是在目標機器上）")
    try:
        model = Path("/proc/device-tree/model").read_bytes().decode("utf-8", "replace").strip("\x00")
        add("board", "INFO", model)
    except OSError:
        add("board", "INFO", "無法讀取 /proc/device-tree/model（非 Raspberry Pi 或沒有權限）")
    libc = platform.libc_ver()
    add("glibc", "INFO", f"{libc[0]} {libc[1]}" if libc[0] else "unknown")
    if libc[0] == "glibc" and libc[1]:
        maj, mn = (int(x) for x in libc[1].split(".")[:2])
        add("glibc_for_wheels", "PASS" if (maj, mn) >= (2, 28) else "FAIL",
            f"glibc {libc[1]}；aarch64 wheel 需要 manylinux_2_27/2_28" + ("" if (maj, mn) >= (2, 28) else " — 不足"))

    # 2. Python 與套件
    pv = sys.version_info
    add("python", "PASS" if pv >= (3, 11) else "FAIL", f"{platform.python_version()}（numpy 2.4.3、pandas 3.0.1、scikit-learn 1.8.0、scipy 1.17.1 需要 ≥ 3.11）")
    req = ROOT / "requirements/requirements_release.txt"
    if req.exists():
        pins = dict(re.findall(r"^([A-Za-z0-9_.\-]+)==(\S+)", req.read_text(encoding="utf-8"), re.M))
        bad = []
        for pkg, ver in pins.items():
            try:
                got = md.version(pkg)
            except md.PackageNotFoundError:
                got = None
            if got != ver:
                bad.append(f"{pkg} {got or 'missing'}≠{ver}")
        add("python_packages", "PASS" if not bad else "FAIL", "全部符合 requirements_release.txt" if not bad else "; ".join(bad))
    else:
        add("python_packages", "FAIL", f"找不到 {req}")

    # 3. 資源
    avail, total = mem_available_mb()
    if avail is not None:
        add("memory", "PASS" if avail >= MIN_MEM_AVAILABLE_MB else "WARN", f"可用 {avail:.0f} MB／總計 {total:.0f} MB（建議可用 ≥ {MIN_MEM_AVAILABLE_MB} MB）")
    du = shutil.disk_usage(ROOT)
    add("disk_release", "PASS" if du.free / 2**20 >= MIN_FREE_MB_DATA else "WARN", f"{ROOT} 可用 {du.free / 2**20:.0f} MB")

    # 4. 套件檔案與設定
    sys.path.insert(0, str(OPS))
    import pinenose_service as svc
    try:
        n = svc.verify_release_integrity()
        add("release_integrity", "PASS", f"{n} 個檔案 SHA-256 相符（release {svc.load_layout()['release_id']}）")
    except svc.ConfigError as e:
        add("release_integrity", "FAIL", f"{e.code}: {e.detail}")
    if a.profile_file:
        try:
            prof = svc.load_profile(a.profile_file)
            ok, note = svc.check_runtime(prof)
            add("profile", "PASS", f"profile={prof['profile']} services={sorted(prof['services'])} lan_access={prof['lan_access']}")
            add("scan_readiness", "PASS" if ok else "WARN", note or "runtime 設定完整（掃描仍需核准模型與有效 AIR）")
            existing = prof["data_root"]
            while not existing.exists() and existing != existing.parent:     # 新站點：資料夾尚未建立 → 用最近的既有上層（唯讀，不建立）
                existing = existing.parent
            du = shutil.disk_usage(existing)
            add("disk_data", "PASS" if du.free / 2**20 >= MIN_FREE_MB_DATA else "WARN", f"資料資料夾可用 {du.free / 2**20:.0f} MB")
            for s, e in prof["services"].items():
                add(f"port_{s}", "FAIL" if svc.port_in_use(e["host"], e["port"]) and not (prof["data_root"] / "run" / f"{s}.pid.json").exists() else "PASS",
                    f"{e['host']}:{e['port']}")
        except svc.ConfigError as e:
            add("profile", "FAIL", f"{e.code}: {e.detail}")
    else:
        add("profile", "INFO", "未指定 --profile-file，略過設定檢查")

    # 5. 序列埠（只列出裝置與權限，不開啟）
    ports = sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*"))
    add("serial_devices", "INFO", ports or "沒有偵測到 /dev/ttyACM*、/dev/ttyUSB*（Arduino 未接上或不是 Linux）")
    if os.name != "nt":
        try:
            import grp
            dialout = grp.getgrnam("dialout").gr_gid
            in_group = dialout in os.getgroups()
            add("serial_permission", "PASS" if in_group else "WARN", "目前使用者在 dialout 群組" if in_group else "目前使用者不在 dialout 群組（無法開啟序列埠；需由管理者處理）")
        except KeyError:
            add("serial_permission", "INFO", "系統沒有 dialout 群組")

    worst = "FAIL" if any(c["status"] == "FAIL" for c in CHECKS) else "OK"
    for c in CHECKS:
        print(f"[{c['status']:4s}] {c['item']}: {c['detail']}")
    print(f"PREFLIGHT {worst}（唯讀；未安裝、未修改、未開啟序列埠）")
    if a.json:
        Path(a.json).write_text(json.dumps({"result": worst, "checks": CHECKS}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if worst == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
