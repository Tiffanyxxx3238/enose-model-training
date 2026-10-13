#!/usr/bin/env python3
"""
PineNose 服務管理程式（Step 6A）

只管理「本發布套件」內經 Step 5 驗收的三個服務：
  gateway  ＝ app/pineapple_app_gateway/app_gateway_v2.py（App API；舊 Gateway v1 不在套件內，也不會被啟動）
  web      ＝ app/pineapple_final/app_local.py（氣味成熟度網頁；本機模式執行同一支 CLI）
  unified  ＝ app/unified_web/app.py（整合網頁，iframe 容器）

指令：
  start  --profile-file P [--services gateway,web,unified]
  stop   --profile-file P [--timeout 15]
  status --profile-file P
  health --profile-file P
  check  --profile-file P          只驗證設定與套件完整性，不啟動
  run    --service S --profile-file P   （內部使用：由 start 以子程序啟動）

安全原則：
  - 模式（formal／engineering）只由後端的 profile 與 runtime 設定檔決定。
  - 預設只綁 127.0.0.1；區網位址需 profile 明確設定 lan_access=true 且為私有 IPv4；不接受 0.0.0.0。
  - 工程（TEST）profile 只能綁本機，必須指定 SHA-256 相符且唯讀的工程模型，資料夾與正式資料分開。
  - 停止只處理本套件 PID 檔記錄、且建立時間與身分都相符的程序；不使用 pkill 之類的廣泛比對。
  - 不讀寫任何憑證；不安裝套件；不修改系統設定；正常啟動不開序列埠（掃描才會開）。

結束碼：0 成功／2 設定錯誤／3 服務埠被占用／4 啟動或健康檢查失敗／5 程序身分或停止問題
"""
import sys
sys.dont_write_bytecode = True          # 不在發布目錄寫入 __pycache__（套件目錄保持唯讀、與 SHA256SUMS 一致）
import argparse
import hashlib
import importlib.util
import ipaddress
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OPS_DIR = Path(__file__).resolve().parent
RELEASE_ROOT = OPS_DIR.parent
SERVICES = ("gateway", "web", "unified")
EXIT_OK, EXIT_CONFIG, EXIT_PORT, EXIT_START, EXIT_PROC = 0, 2, 3, 4, 5
INFERENCE_UNAVAILABLE = {"MODEL_NOT_APPROVED", "MODEL_MISSING", "MODEL_REGISTRY_MISSING", "MODEL_REGISTRY_INVALID"}


class ConfigError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def log(msg):
    print(msg, flush=True)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────
# 發布套件
# ─────────────────────────────────────────
def load_layout(root=RELEASE_ROOT):
    lp = root / "release_layout.json"
    if not lp.exists():
        raise ConfigError("NOT_A_RELEASE", f"{root} 沒有 release_layout.json；請在解壓後的 PineNose 發布套件內執行")
    return json.loads(lp.read_text(encoding="utf-8"))


def verify_release_integrity(root=RELEASE_ROOT):
    """SHA256SUMS 列出的每個檔案都必須存在且雜湊相符（防止被替換成舊 Gateway 或被修改的程式）。"""
    sums = root / "SHA256SUMS"
    if not sums.exists():
        raise ConfigError("RELEASE_CHECKSUMS_MISSING", str(sums))
    bad = []
    n = 0
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split(None, 1)
        rel = rel.lstrip("*").strip()
        n += 1
        f = root / rel
        if not f.exists():
            bad.append(f"missing {rel}")
        elif sha256(f) != digest:
            bad.append(f"modified {rel}")
    if bad:
        raise ConfigError("RELEASE_INTEGRITY_FAILED", "; ".join(bad[:5]))
    return n


# ─────────────────────────────────────────
# Profile 驗證
# ─────────────────────────────────────────
def _resolve(base, p):
    p = Path(p)
    return p if p.is_absolute() else (base / p).resolve()


def _host_ok(host, lan_access):
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False, "主機必須是 IP 位址（不接受名稱）"
    if ip.is_unspecified:
        return False, "不接受 0.0.0.0／::（會綁定所有介面）"
    if ip.is_loopback:
        return True, ""
    if not lan_access:
        return False, "非本機位址需要 profile 明確設定 lan_access=true"
    if ip.version == 4 and ip.is_private and not ip.is_link_local:
        return True, ""
    return False, "只接受私有網段 IPv4（不對公網開放）"


def load_profile(profile_file):
    pf = Path(profile_file).resolve()
    if not pf.exists():
        raise ConfigError("PROFILE_MISSING", f"{pf} 不存在")
    try:
        prof = json.loads(pf.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise ConfigError("PROFILE_INVALID", repr(e))
    base = pf.parent
    name = prof.get("profile")
    if name not in ("formal", "engineering"):
        raise ConfigError("PROFILE_INVALID", "profile 必須是 formal 或 engineering")
    for k in ("runtime_config", "data_root", "services"):
        if not prof.get(k):
            raise ConfigError("PROFILE_INCOMPLETE", f"缺少 {k}")
    lan = prof.get("lan_access", False)
    if not isinstance(lan, bool):
        raise ConfigError("PROFILE_INVALID", "lan_access 必須是 true／false")
    if name == "engineering" and lan:
        raise ConfigError("ENGINEERING_LAN_FORBIDDEN", "工程（TEST）profile 只能在本機使用")
    out = {"file": str(pf), "profile": name, "lan_access": lan, "runtime_config": _resolve(base, prof["runtime_config"]),
           "data_root": _resolve(base, prof["data_root"]), "services": {}, "model_path": None, "model_sha256": None,
           "serial_port": prof.get("serial_port") or None}
    ports = {}
    for svc in SERVICES:
        s = prof["services"].get(svc)
        if s is None or not s.get("enabled", False):
            continue
        host, port = s.get("host"), s.get("port")
        ok, why = _host_ok(str(host), lan)
        if not ok:
            raise ConfigError("HOST_NOT_ALLOWED", f"{svc}: {host} — {why}")
        if name == "engineering" and not ipaddress.ip_address(host).is_loopback:
            raise ConfigError("ENGINEERING_LAN_FORBIDDEN", f"{svc}: {host}")
        if not isinstance(port, int) or not (1024 <= port <= 65535):
            raise ConfigError("PORT_INVALID", f"{svc}: {port}")
        if port in ports.values():
            raise ConfigError("PORT_CONFLICT_IN_PROFILE", f"{svc} 與 {[k for k, v in ports.items() if v == port]} 都使用 {port}")
        ports[svc] = port
        entry = {"host": host, "port": port}
        if svc == "unified":
            for key in ("smell_url", "photo_url"):
                url = s.get(key)
                if url and lan and any(t in url for t in ("://127.", "://localhost", "://[::1]")):
                    raise ConfigError("URL_LOCALHOST_FOR_LAN", f"{key}={url}：遠端瀏覽器無法以 localhost 連到 Pi，請填 Pi 的區網位址")
                entry[key] = url or None
        out["services"][svc] = entry
    if not out["services"]:
        raise ConfigError("PROFILE_INCOMPLETE", "沒有啟用任何服務")
    # 模型
    m = prof.get("engineering_model") if name == "engineering" else prof.get("formal_model")
    if name == "engineering" and not m:
        raise ConfigError("ENGINEERING_MODEL_REQUIRED", "工程 profile 必須以 engineering_model.path／sha256 明確指定模型")
    if m:
        mp = _resolve(base, m.get("path", ""))
        if not mp.exists():
            raise ConfigError("MODEL_FILE_MISSING", str(mp))
        want = str(m.get("sha256", "")).lower()
        got = sha256(mp)
        if got != want:
            raise ConfigError("MODEL_SHA256_MISMATCH", f"{mp.name}: 檔案 {got[:12]}… ≠ profile {want[:12]}…")
        if name == "engineering" and os.access(mp, os.W_OK):
            raise ConfigError("ENGINEERING_MODEL_NOT_READONLY", f"{mp} 必須是唯讀檔（chmod 444）")
        out["model_path"], out["model_sha256"] = mp, got
    return out


def check_runtime(prof):
    """執行設定：模式必須與 profile 相同；核准清單不得混入非核准項目（正式）；工程模型必須登記為 engineering。
    回傳 (runtime_ok, scan_note)。正式模式缺少 AIR 期限 → 服務仍可啟動，但掃描停用（明確標示）。"""
    rc = prof["runtime_config"]
    if not rc.exists():
        raise ConfigError("RUNTIME_CONFIG_MISSING", str(rc))
    try:
        raw = json.loads(rc.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise ConfigError("RUNTIME_CONFIG_INVALID", repr(e))
    if raw.get("mode") != prof["profile"]:
        raise ConfigError("RUNTIME_MODE_MISMATCH", f"profile={prof['profile']}，runtime mode={raw.get('mode')!r}")
    reg_rel = raw.get("model_registry")
    if not reg_rel:
        raise ConfigError("RUNTIME_CONFIG_INCOMPLETE", "缺少 model_registry")
    reg_path = _resolve(rc.parent, reg_rel)
    if not reg_path.exists():
        raise ConfigError("MODEL_REGISTRY_MISSING", str(reg_path))
    try:
        models = json.loads(reg_path.read_text(encoding="utf-8"))["models"]
        assert isinstance(models, dict)
    except Exception as e:  # noqa: BLE001
        raise ConfigError("MODEL_REGISTRY_INVALID", repr(e))
    if prof["profile"] == "formal":
        bad = [k[:12] for k, v in models.items() if not isinstance(v, dict) or v.get("status") != "approved"]
        if bad:
            raise ConfigError("FORMAL_REGISTRY_HAS_UNAPPROVED_ENTRY", f"正式核准清單只能有 approved：{bad}")
        if prof["model_path"] is not None and prof["model_sha256"] not in models:
            raise ConfigError("FORMAL_MODEL_NOT_IN_REGISTRY", prof["model_sha256"][:12])
    else:
        e = models.get(prof["model_sha256"])
        if not isinstance(e, dict) or e.get("status") != "engineering":
            raise ConfigError("ENGINEERING_MODEL_NOT_REGISTERED", "工程模型必須在核准清單登記為 status=engineering")
        hosts = (raw.get("engineering") or {}).get("allowed_client_hosts") or []
        if not hosts or any(not ipaddress.ip_address(h).is_loopback for h in hosts):
            raise ConfigError("ENGINEERING_LAN_FORBIDDEN", f"allowed_client_hosts 只能是本機：{hosts}")
    # 用套件內的安全層做完整驗證（與 Gateway 相同的規則）
    safety = _import_safety()
    old = os.environ.get("PINENOSE_RUNTIME_CONFIG")
    os.environ["PINENOSE_RUNTIME_CONFIG"] = str(rc)
    try:
        safety.load_runtime_config(rc.parent)
        return True, None
    except safety.SafetyError as e:
        if prof["profile"] == "formal" and e.code == "AIR_MAX_AGE_NOT_CONFIGURED":
            return False, "SCAN DISABLED: AIR_MAX_AGE_NOT_CONFIGURED（尚未設定經核准的 AIR 有效期限）"
        raise ConfigError(e.code, e.detail)
    finally:
        if old is None:
            os.environ.pop("PINENOSE_RUNTIME_CONFIG", None)
        else:
            os.environ["PINENOSE_RUNTIME_CONFIG"] = old


def _import_safety():
    layout = load_layout()
    p = RELEASE_ROOT / layout["safety"]
    spec = importlib.util.spec_from_file_location("pinenose_safety_mgr", str(p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def prepare_data_root(prof):
    """資料夾與 profile 綁定：第一次使用時寫入標記；之後若 profile 不同就拒絕（TEST 資料不會寫進正式資料夾）。"""
    d = prof["data_root"]
    for sub in ("run", "logs", "air", "scan_history"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    marker = d / ".pinenose_profile"
    if marker.exists():
        got = marker.read_text(encoding="utf-8").strip()
        if got != prof["profile"]:
            raise ConfigError("DATA_ROOT_PROFILE_MISMATCH", f"{d} 屬於 {got} profile，不能用於 {prof['profile']}")
    else:
        marker.write_text(prof["profile"] + "\n", encoding="utf-8")


# ─────────────────────────────────────────
# 程序身分（不依賴第三方套件）
# ─────────────────────────────────────────
PROC_ROOT = Path(os.environ.get("PINENOSE_PROC_ROOT", "/proc"))


def proc_info(pid):
    """回傳 {'alive': bool, 'create': str|None, 'ident': str|None}。create 用來判斷 PID 是否被重複使用。"""
    if os.name == "nt":
        return _proc_info_windows(pid)
    return _proc_info_linux(pid)


def _proc_info_linux(pid):
    stat = PROC_ROOT / str(pid) / "stat"
    try:
        s = stat.read_text()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return {"alive": False, "create": None, "ident": None}
    fields = s[s.rindex(")") + 2:].split()
    state, start = fields[0], fields[19]       # 欄位 3（state）與欄位 22（starttime）
    if state == "Z":
        return {"alive": False, "create": start, "ident": None}
    try:
        cmd = (PROC_ROOT / str(pid) / "cmdline").read_bytes().split(b"\0")
        ident = " ".join(x.decode("utf-8", "replace") for x in cmd if x)
    except OSError:
        ident = None
    return {"alive": True, "create": start, "ident": ident}


def _proc_info_windows(pid):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return {"alive": False, "create": None, "ident": None}
    try:
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        ft = [wintypes.FILETIME() for _ in range(4)]
        k32.GetProcessTimes(h, *[ctypes.byref(x) for x in ft])
        create = str((ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime)
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return {"alive": code.value == 259, "create": create, "ident": buf.value}     # 259 = STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def force_kill(pid):
    """只在 owned() 確認後呼叫。Windows 的 venv python.exe 是啟動器（會再產生子程序），所以結束整個程序樹；
    Linux 沒有啟動器，只結束該 PID。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        os.kill(pid, signal.SIGKILL)


def owned(rec):
    """PID 檔記錄的程序是否仍是「本套件啟動的那一個」：存活、建立時間相同、身分相符。"""
    info = proc_info(rec["pid"])
    if not info["alive"]:
        return "dead", info
    if info["create"] != rec["create"]:
        return "pid_reused", info
    ident = info["ident"] or ""
    if os.name == "nt":
        same = os.path.normcase(ident) == os.path.normcase(rec["python"])
    else:
        same = rec["runner"] in ident and f"--service {rec['service']}" in ident
    return ("owned" if same else "pid_reused"), info


# ─────────────────────────────────────────
# 服務埠
# ─────────────────────────────────────────
def port_in_use(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind((host, port))
    except OSError:
        return True
    finally:
        s.close()
    for h in {host, "127.0.0.1"}:                          # 另一個程序可能綁在 0.0.0.0
        c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        c.settimeout(0.3)
        try:
            if c.connect_ex((h, port)) == 0:
                return True
        finally:
            c.close()
    return False


# ─────────────────────────────────────────
# 啟動／停止
# ─────────────────────────────────────────
def pidfile(prof, svc):
    return prof["data_root"] / "run" / f"{svc}.pid.json"


def stopfile(prof, svc):
    return prof["data_root"] / "run" / f"{svc}.stop"


class ManagerLock:
    """同一個資料夾同時只允許一個 start／stop 操作。"""

    def __init__(self, prof):
        self.path = prof["data_root"] / "run" / "manager.lock"
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            raise ConfigError("MANAGER_BUSY", "另一個 start／stop 正在執行")
        return self

    def __exit__(self, *a):
        self.fh.close()


def health_url(svc, entry):
    return f"http://{entry['host']}:{entry['port']}" + ("/health" if svc == "gateway" else "/")


def http_get(url, timeout=3):
    req = urllib.request.Request(url, headers={"User-Agent": "pinenose-service/6A"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def service_env(prof, svc, layout):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PINENOSE_")}   # 不沿用 shell 裡的 PINENOSE_* 設定
    e = prof["services"][svc]
    env.update({"PINENOSE_RUNTIME_CONFIG": str(prof["runtime_config"]), "PINENOSE_DATA_DIR": str(prof["data_root"]),
                "PINENOSE_RELEASE_ID": layout["release_id"], "PINENOSE_PROFILE": prof["profile"], "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
                # 單執行緒 BLAS：x86 實測已提交記憶體由約 1386 MB 降到約 164 MB（Pi 3 只有 1 GB）；樹模型推論不使用 BLAS，結果不變
                "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "PYTHONFAULTHANDLER": "1"})        # 原生層錯誤時把堆疊寫入服務記錄檔，便於事後診斷
    if prof["model_path"]:
        env["PINENOSE_MODEL_PATH"] = str(prof["model_path"])
    else:
        env["PINENOSE_MODEL_PATH"] = str(prof["data_root"] / "run" / "NO_MODEL_CONFIGURED.pkl")   # 不回退到任何舊模型
    env.pop("ARDUINO_PORT", None)                 # 序列埠只由 profile 決定（沒有設定就由程式自動偵測）
    if prof["serial_port"]:
        env["ARDUINO_PORT"] = prof["serial_port"]
    if svc == "web":
        env["PINENOSE_WEB_EXEC"] = "local"
    if svc == "unified":
        if e.get("smell_url"):
            env["PINENOSE_SMELL_URL"] = e["smell_url"]
        if e.get("photo_url"):
            env["PINENOSE_PHOTO_URL"] = e["photo_url"]
    return env


def start(prof, only=None):
    layout = load_layout()
    n = verify_release_integrity()
    log(f"[OK] 套件完整性：{n} 個檔案 SHA-256 相符（release {layout['release_id']}）")
    runtime_ok, note = check_runtime(prof)
    prepare_data_root(prof)
    if note:
        log(f"[NOTE] {note}")
    targets = [s for s in SERVICES if s in prof["services"] and (not only or s in only)]
    with ManagerLock(prof):
        to_start = []
        for svc in targets:
            pf = pidfile(prof, svc)
            if pf.exists():
                rec = json.loads(pf.read_text(encoding="utf-8"))
                state, _ = owned(rec)
                if state == "owned":
                    log(f"[SKIP] {svc} 已在執行（PID {rec['pid']}），不重複啟動")
                    continue
                pf.unlink()
                log(f"[CLEAN] {svc} 的 PID 檔已過期（{state}），已移除；不會終止任何程序")
            to_start.append(svc)
        busy = [(s, prof["services"][s]["host"], prof["services"][s]["port"]) for s in to_start
                if port_in_use(prof["services"][s]["host"], prof["services"][s]["port"])]
        if busy:
            for s, h, p in busy:
                log(f"[FAIL] PORT_IN_USE：{s} 需要 {h}:{p}，但已被其他程序使用；未啟動任何服務")
            return EXIT_PORT
        started = []
        for svc in to_start:
            e = prof["services"][svc]
            run_dir, log_dir = prof["data_root"] / "run", prof["data_root"] / "logs"
            stopfile(prof, svc).unlink(missing_ok=True)
            out = open(log_dir / f"{svc}.log", "ab")
            out.write(f"\n===== start {datetime.now(timezone.utc).isoformat()} release {layout['release_id']} =====\n".encode())
            out.flush()
            cmd = [sys.executable, str(Path(__file__).resolve()), "run", "--service", svc, "--profile-file", prof["file"]]
            kw = {"cwd": str(run_dir), "env": service_env(prof, svc, layout), "stdout": out, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
            if os.name == "nt":
                # 背景服務：不顯示主控台視窗（CREATE_NO_WINDOW；子程序沿用同一個隱藏主控台，也不會跳出視窗）
                kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            else:
                kw["start_new_session"] = True
            p = subprocess.Popen(cmd, **kw)
            out.close()
            info = proc_info(p.pid)
            rec = {"pid": p.pid, "create": info["create"], "service": svc, "release_id": layout["release_id"], "release_root": str(RELEASE_ROOT),
                   "python": sys.executable, "runner": str(Path(__file__).resolve()), "host": e["host"], "port": e["port"],
                   "started_at": datetime.now(timezone.utc).isoformat()}
            pidfile(prof, svc).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            ok, why = wait_ready(svc, e, p)
            if not ok:
                log(f"[FAIL] {svc} 啟動失敗：{why}（記錄：{log_dir / (svc + '.log')}）")
                _stop_one(prof, svc, timeout=10)
                for s in started:                              # 不留下半套服務
                    _stop_one(prof, s, timeout=10)
                return EXIT_START
            started.append(svc)
            log(f"[OK] {svc} 已啟動：PID {p.pid}，http://{e['host']}:{e['port']}")
    if "gateway" in prof["services"]:
        return health(prof, quiet_ok=False)
    return EXIT_OK


def wait_ready(svc, entry, popen, timeout=90):
    end = time.time() + timeout
    url = health_url(svc, entry)
    while time.time() < end:
        if popen.poll() is not None:
            return False, f"程序已結束（exit {popen.returncode}）"
        try:
            st, _ = http_get(url, timeout=2)
            if st == 200:
                return True, ""
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.3)
    return False, f"{timeout} 秒內 {url} 沒有回應"


def _stop_one(prof, svc, timeout=15):
    pf = pidfile(prof, svc)
    if not pf.exists():
        return "not_running"
    rec = json.loads(pf.read_text(encoding="utf-8"))
    state, info = owned(rec)
    if state == "dead":
        pf.unlink()
        stopfile(prof, svc).unlink(missing_ok=True)
        return "stale_pidfile_removed"
    if state == "pid_reused":
        pf.unlink()
        return "pid_reused_not_killed"
    stopfile(prof, svc).write_text("stop\n", encoding="utf-8")     # 優雅停止：服務自己關閉
    if os.name != "nt":
        try:
            os.kill(rec["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
    end = time.time() + timeout
    while time.time() < end:
        if owned(rec)[0] != "owned":
            break
        time.sleep(0.2)
    forced = False
    if owned(rec)[0] == "owned":                                    # 只對確認屬於本套件的程序強制結束
        force_kill(rec["pid"])
        forced = True
        end = time.time() + 5
        while time.time() < end and owned(rec)[0] == "owned":
            time.sleep(0.1)
    if owned(rec)[0] == "owned":
        return "stop_failed"
    pf.unlink(missing_ok=True)
    stopfile(prof, svc).unlink(missing_ok=True)
    return "forced" if forced else "stopped"


def stop(prof, timeout=15):
    rc = EXIT_OK
    with ManagerLock(prof):
        for svc in reversed(SERVICES):
            r = _stop_one(prof, svc, timeout)
            log(f"[{'OK' if r != 'stop_failed' else 'FAIL'}] {svc}: {r}")
            if r == "stop_failed":
                rc = EXIT_PROC
    return rc


def status(prof):
    for svc in SERVICES:
        if svc not in prof["services"]:
            log(f"{svc}: disabled")
            continue
        pf = pidfile(prof, svc)
        if not pf.exists():
            log(f"{svc}: stopped")
            continue
        rec = json.loads(pf.read_text(encoding="utf-8"))
        state, _ = owned(rec)
        log(f"{svc}: {'running' if state == 'owned' else 'stale (' + state + ')'} PID {rec['pid']} http://{rec['host']}:{rec['port']} release {rec['release_id']}")
    return EXIT_OK


def classify_gateway_health(h):
    """模型未核准／AIR 期限未設定是「依設計停用掃描」，不是軟體故障。"""
    if h.get("config_error"):
        c = h["config_error"]["code"]
        return f"RUNNING — SCAN DISABLED BY CONFIGURATION ({c})"
    me = (h.get("model_error") or {}).get("code")
    if me in INFERENCE_UNAVAILABLE:
        return f"RUNNING — MATURITY INFERENCE NOT APPROVED ({me}); non-model functions available"
    if me:
        return f"RUNNING — MODEL ERROR ({me})"
    air = h.get("air") or {}
    if not air.get("ok"):
        return f"RUNNING — {h.get('result_kind')} MODEL READY, AIR NOT READY ({air.get('error')})"
    return f"RUNNING — READY ({h.get('mode')}, result kind {h.get('result_kind')})"


def health(prof, quiet_ok=False):
    rc = EXIT_OK
    for svc, e in prof["services"].items():
        try:
            st, body = http_get(health_url(svc, e), timeout=5)
        except (urllib.error.URLError, OSError) as ex:
            log(f"[FAIL] {svc}: 無法連線 {health_url(svc, e)}（{ex}）")
            rc = EXIT_START
            continue
        if svc == "gateway":
            h = json.loads(body)
            log(f"[OK] gateway HTTP {st}: {classify_gateway_health(h)}; api_version={h.get('api_version')} release={h.get('release_id')}")
        else:
            log(f"[OK] {svc} HTTP {st}")
    return rc


# ─────────────────────────────────────────
# 服務本體（子程序）
# ─────────────────────────────────────────
def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def run_service(prof, svc):
    layout = load_layout()
    e = prof["services"][svc]
    path = RELEASE_ROOT / layout[svc]
    sys.path.insert(0, str(path.parent))
    if svc == "gateway":
        mod = _load_module("app_gateway_v2", path)
        mod._init_runtime()
    elif svc == "web":
        mod = _load_module("app_local", path)
    else:
        mod = _load_module("pinenose_unified_app", path)
    from werkzeug.serving import make_server
    server = make_server(e["host"], e["port"], mod.app, threaded=True)
    stop_evt = threading.Event()

    def request_stop(*_):
        stop_evt.set()

    def watcher():
        sf = stopfile(prof, svc)
        while not stop_evt.is_set():
            if sf.exists():
                stop_evt.set()
                break
            time.sleep(0.3)
        if svc == "gateway":
            try:                                       # 進行中的掃描先取消（關閉序列埠、不寫入歷史）
                cur = mod._registry.get()
                if cur and cur["status"] in ("scanning", "calibrating"):
                    mod._registry.cancel(cur["scan_id"])
            except Exception:  # noqa: BLE001
                pass
        server.shutdown()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, request_stop)
        except (ValueError, OSError):
            pass
    threading.Thread(target=watcher, daemon=True).start()
    print(f"[run] {svc} serving on http://{e['host']}:{e['port']} (release {layout['release_id']}, profile {prof['profile']}) module={path}", flush=True)
    server.serve_forever()
    print(f"[run] {svc} stopped gracefully", flush=True)
    return EXIT_OK


def main(argv=None):
    ap = argparse.ArgumentParser(description="PineNose service manager (Step 6A)")
    ap.add_argument("command", choices=["start", "stop", "status", "health", "check", "run"])
    ap.add_argument("--profile-file", required=True)
    ap.add_argument("--services", default=None)
    ap.add_argument("--service", default=None)
    ap.add_argument("--timeout", type=float, default=15)
    a = ap.parse_args(argv)
    try:
        prof = load_profile(a.profile_file)
        if a.command == "run":
            return run_service(prof, a.service)
        if a.command == "check":
            n = verify_release_integrity()
            ok, note = check_runtime(prof)
            log(f"[OK] profile={prof['profile']} services={sorted(prof['services'])} release files={n}" + (f"; {note}" if note else ""))
            return EXIT_OK
        if a.command == "start":
            return start(prof, a.services.split(",") if a.services else None)
        if a.command == "stop":
            return stop(prof, a.timeout)
        if a.command == "status":
            return status(prof)
        return health(prof)
    except ConfigError as e:
        log(f"[FAIL] {e.code}: {e.detail}")
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
