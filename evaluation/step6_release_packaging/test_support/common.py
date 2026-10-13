"""Step 6A 測試共用工具：一律對「解壓後的發布套件」操作；工作目錄與 repo／worktree 無關。"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]               # evaluation/step6_release_packaging
EVAL = HERE.parent
WT = EVAL.parent
REPO = WT.parent
ART = REPO / "release_artifacts"
RUN_ROOT = Path(os.environ.get("S6A_RUN_ROOT", "C:/Users/user/AppData/Local/Temp/s6a"))
RELEASE_PY = os.environ.get("S6A_RELEASE_PYTHON", "C:/Users/user/AppData/Local/Temp/s6v/Scripts/python.exe")
BASH = os.environ.get("S6A_BASH", shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe")
FAKE_SITE = HERE / "test_support" / "fake_serial_site"
NEUTRAL_CWD = RUN_ROOT / "_neutral_cwd"                  # 不在 worktree、也不在套件內的工作目錄
RESULTS = []
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0     # 測試程序一律不顯示主控台視窗


def rec(group, tid, name, ok, evidence, kind="RUNTIME (extracted package; fake serial / loopback only)"):
    v = ok if isinstance(ok, str) else ("PASS" if ok else "FAIL")
    RESULTS.append({"group": group, "id": tid, "test": name, "verdict": v, "kind": kind, "evidence": str(evidence)[:700]})
    print(f"[{v}] {tid} {name} — {str(evidence)[:200]}", flush=True)


def check(group, tid, name, fn, kind=None):
    try:
        ok, ev = fn()
    except Exception as e:  # noqa: BLE001
        import traceback
        ok, ev = False, f"TEST ERROR {e!r} :: {traceback.format_exc().splitlines()[-3:]}"
    rec(group, tid, name, ok, ev, **({"kind": kind} if kind else {}))


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def package():
    pid = os.environ.get("S6A_PACKAGE_ID")
    cands = sorted(ART.glob(f"{pid}.tar.gz" if pid else "pinenose-rc-6a-*.tar.gz"), key=lambda p: p.stat().st_mtime)
    assert cands, f"no package in {ART}"
    return cands[-1]


def base_env(extra=None, fake_serial=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PINENOSE_", "FAKE_SERIAL")) and k not in ("PYTHONPATH", "ARDUINO_PORT")}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PINENOSE_PYTHON"] = RELEASE_PY
    if fake_serial:
        env["PYTHONPATH"] = str(FAKE_SITE)
    env.update(extra or {})
    return env


def run(cmd, env=None, cwd=None, timeout=300):
    NEUTRAL_CWD.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    p = subprocess.run([str(c) for c in cmd], env=env or base_env(), cwd=str(cwd or NEUTRAL_CWD), capture_output=True, timeout=timeout,
                       creationflags=NO_WINDOW)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    return p.returncode, out, round(time.time() - t0, 1)


def sh(rdir, script, profile, env=None, args=(), timeout=300):
    e = dict(env or base_env())
    e["PINENOSE_PROFILE"] = str(profile)
    return run([BASH, str(Path(rdir) / script), *args], env=e, timeout=timeout)


def mgr(rdir, command, profile, env=None, args=(), timeout=300):
    return run([RELEASE_PY, str(Path(rdir) / "ops/pinenose_service.py"), command, "--profile-file", str(profile), *args], env=env, timeout=timeout)


def install(site, pkg):
    """操作人員流程：先從套件取出 ops/pinenose_backup.py，再用它驗證並安裝整個套件。"""
    site.mkdir(parents=True, exist_ok=True)
    with tarfile.open(pkg, "r:gz") as tf:
        top = tf.getnames()[0].split("/")[0]
        m = tf.getmember(f"{top}/ops/pinenose_backup.py")
        tool = site / "_bootstrap_pinenose_backup.py"
        tool.write_bytes(tf.extractfile(m).read())
    code, out, _ = run([RELEASE_PY, tool, "install", "--site", site, "--package", pkg, "--execute"])
    assert code == 0, out
    code2, out2, _ = run([RELEASE_PY, tool, "switch", "--site", site, "--release", top, "--execute"])
    assert code2 == 0, out2
    tool.unlink()
    return site / "releases" / top, out + out2


def write_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def site_config(site, rdir, profile="formal", ports=(5000, 5001, 8000), max_age=None, registry=None, model=None, lan=False,
                hosts=None, smell_url=None, serial_port=None, unified=True, data_root=None, name="profile.json", runtime_name=None):
    """從套件內的範本產生站點設定（與操作說明相同的流程），再套用測試需要的欄位。"""
    cfg = Path(rdir) / "config"
    sd = site / "site"
    prof = json.loads((cfg / f"profile.{profile}.template.json").read_text(encoding="utf-8"))
    rt = json.loads((cfg / f"runtime.{profile}.template.json").read_text(encoding="utf-8"))
    reg = json.loads((cfg / f"model_registry.{profile}.template.json").read_text(encoding="utf-8"))
    web, gw, uni = ports
    h = hosts or "127.0.0.1"
    prof["services"]["web"].update(host=h, port=web)
    prof["services"]["gateway"].update(host=h, port=gw)
    prof["services"]["unified"].update(host=h, port=uni, enabled=unified, smell_url=smell_url)
    prof["lan_access"] = lan
    prof["serial_port"] = serial_port
    runtime_name = runtime_name or f"runtime.{profile}.json"
    prof["runtime_config"] = runtime_name
    if data_root:
        prof["data_root"] = data_root
    if profile == "engineering":
        prof["engineering_model"] = model
    else:
        prof["formal_model"] = model
    rt["model_registry"] = f"model_registry.{profile}.json"
    rt[profile]["air_max_age_sec"] = max_age
    if registry is not None:
        reg["models"] = registry
    write_json(sd / runtime_name, rt)
    write_json(sd / f"model_registry.{profile}.json", reg)
    return write_json(sd / name, prof)


def http(method, url, body=None, timeout=15, data=None):
    headers = {"Content-Type": "application/json"} if body is not None else {}
    payload = json.dumps(body).encode() if body is not None else (data.encode() if isinstance(data, str) else data)
    if data is not None and body is None:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
    req = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            st = r.status
    except urllib.error.HTTPError as e:
        raw, st = e.read(), e.code
    try:
        return st, json.loads(raw)
    except Exception:  # noqa: BLE001
        return st, raw.decode("utf-8", "replace")


def wait_terminal(base, sid, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        st, js = http("GET", f"{base}/status?scan_id={sid}")
        if st == 200 and js.get("status") in ("done", "failed", "cancelled", "timed_out"):
            return js
        time.sleep(0.2)
    raise TimeoutError(sid)


def port_open(port, host="127.0.0.1"):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def pid_alive(pid):
    """以 Windows API 查詢程序是否存活（不呼叫 tasklist，不會跳出視窗）。"""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == 259
    finally:
        k32.CloseHandle(h)


def kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)


def start_external_dummy(name, port):
    """模擬「外部同名程序」：一個與本套件無關、檔名為 app.py／app_gateway_v2.py 等的 Python 服務。"""
    d = RUN_ROOT / "external" / f"{name}_{port}"
    d.mkdir(parents=True, exist_ok=True)
    script = d / name
    script.write_text("import http.server,socketserver,sys\n"
                      "class H(http.server.BaseHTTPRequestHandler):\n"
                      "    def do_GET(self):\n        self.send_response(200); self.end_headers(); self.wfile.write(b'external')\n"
                      "    def log_message(self,*a): pass\n"
                      f"socketserver.TCPServer(('127.0.0.1',{port}),H).serve_forever()\n", encoding="utf-8")
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | NO_WINDOW) if os.name == "nt" else 0
    p = subprocess.Popen([sys.executable, str(script)], cwd=str(d), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    for _ in range(50):
        if port_open(port):
            break
        time.sleep(0.1)
    return p


def tree_hashes(root):
    root = Path(root)
    return {f.relative_to(root).as_posix(): sha256(f) for f in sorted(root.rglob("*")) if f.is_file()}
