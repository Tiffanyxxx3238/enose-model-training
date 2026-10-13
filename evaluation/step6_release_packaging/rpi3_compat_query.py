"""
Step 6A：Raspberry Pi 3 相容性離線預檢（只讀取公開發行檔 metadata；不連 Pi、不安裝任何套件）

資料來源：
  - PyPI JSON API：https://pypi.org/pypi/<pkg>/<ver>/json（wheel 檔名的平台標籤與 requires_python）
  - piwheels JSON API：https://www.piwheels.org/project/<pkg>/json/（Raspberry Pi OS 32-bit armv7l／armv6l 的社群建置）
對照目標：
  - Raspberry Pi 3：Cortex-A53（ARMv8）。可跑 64-bit Raspberry Pi OS（aarch64）或 32-bit（armhf → armv7l）。
  - Raspberry Pi OS Bookworm：Python 3.11、glibc 2.36；Bullseye：Python 3.9、glibc 2.31；Trixie：Python 3.13、glibc 2.41。
結論只依可核對的 metadata；沒有在 Pi 上安裝或執行，所以「有 wheel」≠「已驗證可執行」。
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REQ = HERE.parents[1] / "pinenose_release/requirements_release.txt"
TARGETS = [("RPiOS Bookworm 64-bit", "aarch64", "cp311", (2, 36)), ("RPiOS Trixie 64-bit", "aarch64", "cp313", (2, 41)),
           ("RPiOS Bullseye 64-bit", "aarch64", "cp39", (2, 31)),
           ("RPiOS Bookworm 32-bit", "armv7l", "cp311", (2, 36)), ("RPiOS Trixie 32-bit", "armv7l", "cp313", (2, 41)),
           ("RPiOS Bullseye 32-bit", "armv7l", "cp39", (2, 31))]


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pinenose-step6a-compat-check"}), timeout=40) as r:
        return json.load(r)


def parse_wheel(fn):
    """name-ver(-build)?-pytag-abitag-plat.whl → (pytags, abi, plats)"""
    parts = fn[:-4].split("-")
    py, abi, plat = parts[-3], parts[-2], parts[-1]
    return py.split("."), abi, plat.split(".")


def py_ok(requires_python, cp):
    if not requires_python:
        return True
    v = (int(cp[2]), int(cp[3:]))
    for spec in requires_python.split(","):
        spec = spec.strip()
        m = re.match(r"(>=|<=|>|<|==|!=|~=)\s*(\d+)\.(\d+)", spec)
        if not m:
            continue
        op, a, b = m.group(1), int(m.group(2)), int(m.group(3))
        t = (a, b)
        if (op == ">=" and v < t) or (op == ">" and v <= t) or (op == "<" and v >= t) or (op == "<=" and v > t):
            return False
    return True


def wheel_matches(fn, arch, cp, glibc):
    pys, abi, plats = parse_wheel(fn)
    if not any(p in ("py3", "py2.py3", cp) or p == cp for p in pys):
        if not (abi == "abi3" and any(p.startswith("cp3") and int(p[3:]) <= int(cp[3:]) for p in pys)):
            return False
    if abi not in ("none", "abi3", cp) and not (abi == cp):
        return False
    for pl in plats:
        if pl == "any":
            return True
        m = re.match(r"manylinux_(\d+)_(\d+)_(\w+)", pl)
        if m and m.group(3) == arch and (int(m.group(1)), int(m.group(2))) <= glibc:
            return True
        if pl == f"manylinux2014_{arch}" and (2, 17) <= glibc:
            return True
        if pl == f"linux_{arch}":
            return True
    return False


reqs = dict(re.findall(r"^([A-Za-z0-9_.\-]+)==(\S+)", REQ.read_text(encoding="utf-8"), re.M))
rows = []
for pkg, ver in reqs.items():
    d = get(f"https://pypi.org/pypi/{pkg}/{ver}/json")
    files = [u["filename"] for u in d["urls"]]
    rp = d["info"].get("requires_python")
    whl = [f for f in files if f.endswith(".whl")]
    try:
        pw = get(f"https://www.piwheels.org/project/{pkg.lower().replace('_', '-')}/json/")
        pw_rel = pw.get("releases", {}).get(ver, {})
        pw_files = list((pw_rel.get("files") or {}).keys())
        pw_note = "listed" if pw_rel else "version not on piwheels"
    except Exception as e:  # noqa: BLE001
        pw_files, pw_note = [], f"piwheels query failed: {type(e).__name__}"
    for tname, arch, cp, glibc in TARGETS:
        pyver_ok = py_ok(rp, cp)
        pypi = [f for f in whl if wheel_matches(f, arch, cp, glibc)]
        piw = [f for f in pw_files if f.endswith(".whl") and wheel_matches(f, arch, cp, glibc)] if arch == "armv7l" else []
        if not pyver_ok:
            status, evidence = "BLOCKER", f"requires_python {rp} excludes {cp}"
        elif pypi:
            status, evidence = "WHEEL AVAILABLE (PyPI) — UNVERIFIED ON TARGET", pypi[0]
        elif piw:
            status, evidence = "WHEEL AVAILABLE (piwheels) — UNVERIFIED ON TARGET", piw[0]
        elif any(f.endswith(".tar.gz") for f in files):
            status, evidence = "NO WHEEL — SOURCE BUILD REQUIRED (UNVERIFIED — REQUIRES TARGET ENVIRONMENT CHECK)", f"piwheels: {pw_note}"
        else:
            status, evidence = "BLOCKER", "no wheel and no sdist"
        rows.append({"package": pkg, "version": ver, "requires_python": rp, "target": tname, "arch": arch, "python_abi": cp,
                     "glibc": ".".join(map(str, glibc)), "status": status, "evidence": evidence, "piwheels": pw_note})
    print(pkg, ver, "done", flush=True)

df = pd.DataFrame(rows)
df.to_csv(HERE / "rpi3_compatibility_matrix.csv", index=False, encoding="utf-8-sig")
summary = df.assign(blocker=df.status.str.startswith("BLOCKER"), wheel=df.status.str.startswith("WHEEL"),
                    source=df.status.str.startswith("NO WHEEL")).groupby("target")[["wheel", "source", "blocker"]].sum()
print(summary.to_string())
summary.to_csv(HERE / "logs/rpi3_compatibility_summary.csv", encoding="utf-8-sig")
