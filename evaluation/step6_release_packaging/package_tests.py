"""
Step 6A：封裝後獨立驗收（解壓到全新資料夾後，以套件自己的腳本與工具執行）

群組：
  P  套件：SHA-256、可重現建置、內容（不含模型／原始資料／憑證）、解壓獨立性
  S  啟動／停止：正常、重複、埠被占用、設定缺失、健康檢查、停止、重複停止、異常結束、過期 PID、PID 重用、外部同名程序、
     強制停止只影響本套件、錯誤 Gateway 無法啟動、區網規則
  F  正式模式：未核准模型時拒絕成熟度推論；非模型服務仍可用
  E  工程（TEST）：模型 SHA／唯讀／登記檢查、99 天歷史重播（經實際 HTTP 服務入口）、網頁路徑、TEST 隔離、
     無效 AIR／ADC／header／資料不足／取消／逾時／模型錯誤、跨程序感測器互斥
  D  資料完整性：只追加、正式與 TEST 分開、失敗不入結果歷史、重啟後保留

測試替身：假序列埠（PYTHONPATH 注入，套件外）；所有網路只用 127.0.0.1。
"""
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "test_support"))
from common import (ART, BASH, EVAL, HERE, RELEASE_PY, REPO, RESULTS, RUN_ROOT, WT, base_env, check, http, install,  # noqa: E402
                    kill_tree, mgr, package, pid_alive, port_open, rec, run, sh, sha256, site_config, start_external_dummy,
                    tree_hashes, wait_terminal, write_json)

T0 = time.time()
STAGE_ZH = {0: "未熟", 1: "初熟", 2: "成熟", 3: "過熟"}
SENS = ["MQ2", "MQ3", "MQ9", "MQ135", "TGS2602"]
HEADER = ["timestamp_ms", "timestamp_s", "MQ2_raw", "MQ3_raw", "MQ9_raw", "MQ135_raw", "TGS2602_raw", "Temp_C", "Humidity_pct", "Pressure_hPa"]
FINAL = WT / "pineapple_final"
DEPLOY_PKL = FINAL / "deploy_student.pkl"
DEPLOY_SHA = "a57dbbbf3a3dd7f27d59c3006d8319faf7e16431d6c06eaa3a55ec84d26f16a1"
FEATS = json.loads((FINAL / "feature_columns.json").read_text(encoding="utf-8"))
N_REPLAY = int(os.environ.get("S6A_REPLAY_DAYS", "99"))
EXTERNALS = []

if RUN_ROOT.exists():
    for f in RUN_ROOT.rglob("*"):                               # 解除唯讀（取代 cmd /c attrib，不跳視窗）
        try:
            os.chmod(f, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass
    shutil.rmtree(RUN_ROOT, ignore_errors=True)
RUN_ROOT.mkdir(parents=True, exist_ok=True)
assert not any(RUN_ROOT.iterdir()), f"{RUN_ROOT} could not be cleaned (a previous test process may still hold files)"
PKG = package()
RID = PKG.name[:-len(".tar.gz")]
print(f"package {PKG} ({PKG.stat().st_size} bytes)")

# ═══ P. 套件 ═══
def t_p01():
    want = Path(str(PKG) + ".sha256").read_text(encoding="utf-8").split()[0]
    return sha256(PKG) == want, f"sha256 {sha256(PKG)} == .sha256 file: {sha256(PKG) == want}"


check("P", "P01-PACKAGE-SHA256", "套件 SHA-256 與外部 .sha256 相符", t_p01)


def t_p02():
    out = RUN_ROOT / "_rebuild"
    v = json.loads(tarfile.open(PKG).extractfile(f"{RID}/VERSION.json").read())
    code, txt, _ = run([sys.executable, WT / "pinenose_release/build_release.py", "--commit", v["source_commit"], "--out-dir", out, "--repo", REPO])
    again = out / PKG.name
    return code == 0 and sha256(again) == sha256(PKG), f"rebuild from {v['source_commit'][:10]} → identical bytes: {code == 0 and sha256(again) == sha256(PKG)}"


check("P", "P02-REPRODUCIBLE-BUILD", "以相同 commit 重新建置得到逐位元相同的套件", t_p02)

FORBIDDEN = re.compile(r"(\.pkl$|\.pickle$|\.joblib$|\.xlsx?$|\.csv$|/air_base[^/]*\.json$|scan_history|/\.env|pinenose_runtime\.json$|demo_data|"
                       r"__pycache__|\.pyc$|/app_gateway\.py$|node_modules|/\.git)", re.I)
SECRET = re.compile(r"((password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*['\"][^'\"<>{}\s]{4,}['\"])|BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20}|"
                    r"sk-[A-Za-z0-9]{20}|AKIA[0-9A-Z]{16}", re.I)


def t_p03():
    with tarfile.open(PKG) as tf:
        names = tf.getnames()
        bad = [n for n in names if FORBIDDEN.search(n)]
        secrets = []
        abs_paths = []
        for m in tf.getmembers():
            if m.isfile():
                t = tf.extractfile(m).read().decode("utf-8", "replace")
                secrets += [m.name for line in t.splitlines() if SECRET.search(line) and "os.environ.get(" not in line]
                if re.search(r"enose-step6|C:[/\\]Users[/\\]user", t):
                    abs_paths.append(m.name)
        size = sum(m.size for m in tf.getmembers())
    return (not bad and not secrets and not abs_paths), f"{len(names)} entries, {size} bytes uncompressed; forbidden={bad}; secret-pattern hits={secrets}; local absolute paths={abs_paths}"


check("P", "P03-NO-MODEL-DATA-SECRETS", "套件不含模型、原始資料、AIR／歷史、Gateway v1、憑證或本機路徑", t_p03)


def t_p04():
    with tarfile.open(PKG) as tf:
        v = json.loads(tf.extractfile(f"{RID}/VERSION.json").read())
        notice = tf.extractfile(f"{RID}/RELEASE_NOTICE.txt").read().decode("utf-8")
        reg = json.loads(tf.extractfile(f"{RID}/app/pineapple_final/model_registry.json").read())
        man = json.loads(tf.extractfile(f"{RID}/manifests/release_manifest.json").read())
    ok = (v["status"] == "SOFTWARE RELEASE CANDIDATE — MATURITY INFERENCE NOT APPROVED" and notice.startswith(v["status"]) and reg["models"] == {}
          and v["step5_acceptance_commit"].startswith("2b4a1df2") and man["api_contract_version"] == "2.1")
    return ok, f"status={v['status']!r}; source_commit={v['source_commit'][:10]}; registry models={reg['models']}; api={man['api_contract_version']}"


check("P", "P04-RC-LABEL", "套件標示 SOFTWARE RELEASE CANDIDATE — MATURITY INFERENCE NOT APPROVED，核准清單為空", t_p04)

# 安裝到全新站點（只用套件內的工具）
SITE = RUN_ROOT / "site_formal"
RDIR, inst_out = install(SITE, PKG)
rec("P", "P05-INSTALL", "以套件內 pinenose_backup.py 驗證 SHA-256 後安裝並切換 current_release", "[OK] installed" in inst_out,
    inst_out.strip().splitlines()[-2:])


def t_p06():
    n = len((RDIR / "SHA256SUMS").read_text(encoding="utf-8").splitlines())
    code, out, _ = mgr(RDIR, "check", SITE / "site/missing.json")
    return code == 2 and "PROFILE_MISSING" in out, f"SHA256SUMS {n} entries; check without profile → exit {code}: {out.strip()[:120]}"


check("P", "P06-NO-HIDDEN-CONFIG", "解壓後沒有隱藏設定：沒有 profile 時明確失敗（不讀 worktree 或環境中的設定）", t_p06)

def t_p07():
    before = sorted(p.relative_to(SITE).as_posix() for p in SITE.rglob("*"))
    prof = site_config(SITE, RDIR, "formal", (5000, 5001, 8000))
    before = sorted(p.relative_to(SITE).as_posix() for p in SITE.rglob("*"))
    code, out, _ = run([RELEASE_PY, RDIR / "ops/rpi3_preflight.py", "--profile-file", prof])
    after = sorted(p.relative_to(SITE).as_posix() for p in SITE.rglob("*"))
    (HERE / "logs/rpi3_preflight_smoke.txt").write_text("# rpi3_preflight.py on the Windows x86_64 test host (NOT a Raspberry Pi), fresh site; exit "
                                                         + str(code) + "\n" + out, encoding="utf-8")
    secrets = bool(SECRET.search(out))
    return ("Traceback" not in out and "PREFLIGHT" in out and "release_integrity: " in out and before == after and not secrets and "python_packages" in out),         f"exit {code} (FAIL lines expected off-target: {[l[:70] for l in out.splitlines() if l.startswith('[FAIL')]}); read-only (no files created)={before == after}"


check("P", "P07-PREFLIGHT-READONLY", "rpi3_preflight.py 在全新站點可執行、唯讀（不建立任何檔案）、不輸出秘密（非 Pi 主機的 FAIL 項目為預期）", t_p07)

# ═══ S. 啟動／停止 ═══
FORMAL_PORTS = (5000, 5001, 8000)
busy = [p for p in FORMAL_PORTS if port_open(p)]
assert not busy, f"template ports busy on this machine: {busy}"
PROF = site_config(SITE, RDIR, "formal", FORMAL_PORTS)
EXTERNALS += [start_external_dummy("app.py", 15901), start_external_dummy("app_gateway_v2.py", 15902), start_external_dummy("app_local.py", 15903)]
ENV = base_env()


def pids(site, svcs=("gateway", "web", "unified")):
    out = {}
    for s in svcs:
        p = site / "data/formal/run" / f"{s}.pid.json"
        if p.exists():
            out[s] = json.loads(p.read_text(encoding="utf-8"))["pid"]
    return out


def t_s01():
    code, out, dt = sh(RDIR, "start_pineapple_system.sh", PROF, ENV)
    p = pids(SITE)
    st, h = http("GET", "http://127.0.0.1:5001/health")
    logs = (SITE / "data/formal/logs/gateway.log").read_text(encoding="utf-8", errors="replace")
    module_in_site = re.search(r"module=(.+app_gateway_v2\.py)", logs)
    ok = (code == 0 and len(p) == 3 and all(pid_alive(x) for x in p.values()) and st == 200 and h["release_id"] == RID and h["api_version"] == "2.1"
          and "SCAN DISABLED BY CONFIGURATION (AIR_MAX_AGE_NOT_CONFIGURED)" in out and module_in_site
          and str(SITE.resolve()).lower() in module_in_site.group(1).lower())
    return ok, f"exit {code} in {dt}s; pids={p}; health release={h.get('release_id')} api={h.get('api_version')}; module={module_in_site.group(1) if module_in_site else None}; tail={out.strip().splitlines()[-1][:150]}"


check("S", "S01-NORMAL-START", "正常啟動（套件 start 腳本）：3 個服務、PID 檔、健康檢查；正式範本 → 掃描依設計停用", t_s01)
FIRST = pids(SITE)


def t_s02():
    code, out, _ = sh(RDIR, "start_pineapple_system.sh", PROF, ENV)
    return code == 0 and pids(SITE) == FIRST and out.count("[SKIP]") == 3, f"exit {code}; same PIDs={pids(SITE) == FIRST}; skips={out.count('[SKIP]')}"


check("S", "S02-REPEATED-START", "重複啟動：不產生第二組程序（SKIP），PID 不變", t_s02)


def t_s03():
    st1, h = http("GET", "http://127.0.0.1:5001/health")
    st2, s = http("POST", "http://127.0.0.1:5001/scan", {})
    st3, page = http("GET", "http://127.0.0.1:5000/")
    st4, uni = http("GET", "http://127.0.0.1:8000/")
    ok = (st1 == 200 and h["config_error"]["code"] == "AIR_MAX_AGE_NOT_CONFIGURED" and st2 == 503 and s.get("error") == "AIR_MAX_AGE_NOT_CONFIGURED"
          and st3 == 200 and st4 == 200 and "未設定（部署設定未提供網址）" in uni and "192.168.0.152" not in uni)
    return ok, f"/health {st1} config_error={h.get('config_error', {}).get('code')}; /scan {st2} {s.get('error')}; web / {st3}; unified / {st4} (iframe not configured, no hard-coded IP)"


check("F", "F01-FORMAL-TEMPLATE-SCAN-DISABLED", "正式範本（AIR 期限未設定）：服務在線、掃描以 AIR_MAX_AGE_NOT_CONFIGURED 拒絕，網頁可用", t_s03)


def t_s04():
    code, out, _ = mgr(RDIR, "health", PROF)
    return code == 0 and "RUNNING — SCAN DISABLED BY CONFIGURATION" in out and "[FAIL]" not in out, out.strip().replace("\n", " | ")[:300]


check("S", "S04-HEALTH-NOT-A-FAULT", "健康檢查：設定性停用（未核准／未設定期限）回報為 RUNNING，不誤稱軟體故障（exit 0）", t_s04)


def t_s05():
    code, out, dt = sh(RDIR, "stop_pineapple_system.sh", PROF, ENV)
    gone = all(not pid_alive(x) for x in FIRST.values())
    log = (SITE / "data/formal/logs/gateway.log").read_text(encoding="utf-8", errors="replace")
    ext = all(e.poll() is None for e in EXTERNALS) and all(port_open(p) for p in (15901, 15902, 15903))
    ok = code == 0 and gone and not pids(SITE) and not any(port_open(p) for p in FORMAL_PORTS) and "stopped gracefully" in log and "forced" not in out and ext
    return ok, f"exit {code} in {dt}s; processes gone={gone}; pidfiles left={pids(SITE)}; graceful={'stopped gracefully' in log}; external same-name processes alive={ext}"


check("S", "S05-NORMAL-STOP", "正常停止：優雅結束、PID 檔移除、服務埠釋放；外部同名程序（app.py 等）不受影響", t_s05)


def t_s06():
    code, out, _ = sh(RDIR, "stop_pineapple_system.sh", PROF, ENV)
    return code == 0 and out.count("not_running") == 3, f"exit {code}: {out.strip().replace(chr(10), ' | ')}"


check("S", "S06-REPEATED-STOP", "重複停止：安全（not_running），exit 0", t_s06)


def t_s07():
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 5001))
    blocker.listen(1)
    try:
        code, out, _ = sh(RDIR, "start_pineapple_system.sh", PROF, ENV)
        none_started = not pids(SITE) and not port_open(5000) and not port_open(8000)
    finally:
        blocker.close()
    return code == 3 and "PORT_IN_USE" in out and none_started, f"exit {code}; started nothing={none_started}; {out.strip().splitlines()[-1][:160]}"


check("S", "S07-PORT-IN-USE", "服務埠被占用：明確失敗（exit 3, PORT_IN_USE），不啟動任何服務", t_s07)


def t_s08():
    rows = []
    for label, mutate in (("profile missing", lambda d: (d / "profile.json").rename(d / "profile.json.bak")),
                          ("runtime config missing", lambda d: (d / "runtime.formal.json").rename(d / "runtime.formal.json.bak")),
                          ("model registry missing", lambda d: (d / "model_registry.formal.json").rename(d / "model_registry.formal.json.bak")),
                          ("runtime mode mismatch", lambda d: write_json(d / "runtime.formal.json", {**json.loads((d / "runtime.formal.json").read_text(encoding="utf-8")), "mode": "engineering"})),
                          ("engineering entry in formal registry", lambda d: write_json(d / "model_registry.formal.json", {"models": {DEPLOY_SHA: {"status": "engineering", "feature_columns": FEATS}}}))):
        d = SITE / "site"
        snap = {f.name: f.read_bytes() for f in d.iterdir() if f.is_file()}
        mutate(d)
        code, out, _ = sh(RDIR, "start_pineapple_system.sh", PROF, ENV)
        rows.append((label, code, (re.search(r"\[FAIL\] (\w+)", out) or [None, "?"])[1], bool(pids(SITE))))
        for f in d.iterdir():
            f.unlink()
        for n, b in snap.items():
            (d / n).write_bytes(b)
    ok = all(c == 2 and not started for _, c, _, started in rows)
    return ok, f"{rows}"


check("S", "S08-CONFIG-MISSING", "設定缺失或錯誤（profile／runtime／核准清單／模式不符／正式清單混入工程模型）→ exit 2，不啟動", t_s08)


def t_s09():
    code, out, _ = sh(RDIR, "start_pineapple_system.sh", PROF, ENV)
    p = pids(SITE)
    kill_tree(p["gateway"])                                    # 模擬 Gateway 異常結束
    time.sleep(1)
    code_s, st_out, _ = mgr(RDIR, "status", PROF)
    code2, out2, _ = sh(RDIR, "start_pineapple_system.sh", PROF, ENV)
    p2 = pids(SITE)
    ok = (code == 0 and "gateway: stale (dead)" in st_out and code2 == 0 and "[CLEAN] gateway" in out2 and p2["web"] == p["web"]
          and p2["gateway"] != p["gateway"] and pid_alive(p2["gateway"]))
    return ok, f"after crash status: {[l for l in st_out.splitlines() if l.startswith('gateway')]}; restart exit {code2}: cleaned stale pidfile, web kept PID {p['web']}, new gateway PID {p2.get('gateway')}"


check("S", "S09-ABNORMAL-EXIT", "異常結束：狀態顯示 stale；再次啟動清除過期 PID 檔並只重啟該服務", t_s09)


def t_s10():
    p = pids(SITE)
    pf = SITE / "data/formal/run/gateway.pid.json"
    real = json.loads(pf.read_text(encoding="utf-8"))
    victim = EXTERNALS[1]                                      # 外部 app_gateway_v2.py（同名、不屬於本套件）
    fake = {**real, "pid": victim.pid}                         # PID 指向別人的程序（建立時間不同 → PID 重用）
    pf.write_text(json.dumps(fake), encoding="utf-8")
    code, out, _ = sh(RDIR, "stop_pineapple_system.sh", PROF, ENV)
    alive_victim = victim.poll() is None and port_open(15902)
    still_ours = pid_alive(real["pid"])                         # 原本的 Gateway 失去 PID 檔 → 不會被停止
    if still_ours:
        kill_tree(real["pid"])                                 # 測試清理（不是被測工具做的）
    return ("gateway: pid_reused_not_killed" in out and alive_victim and code == 0), \
        f"stop with PID file pointing at external app_gateway_v2.py → {[l for l in out.splitlines() if 'gateway' in l]}; external alive={alive_victim}"


check("S", "S10-PID-REUSE", "PID 檔指向外部同名程序（PID 重用）：停止工具辨識身分不符，不終止外部程序", t_s10)


def t_s11():
    pf = SITE / "data/formal/run/web.pid.json"
    code, out, _ = sh(RDIR, "start_pineapple_system.sh", PROF, ENV)
    rec_ = json.loads(pf.read_text(encoding="utf-8"))
    for s in ("web", "unified", "gateway"):
        q = SITE / "data/formal/run" / f"{s}.pid.json"
        if q.exists():
            kill_tree(json.loads(q.read_text(encoding="utf-8"))["pid"])
    time.sleep(1)
    dead = {**rec_, "pid": 999999}
    pf.write_text(json.dumps(dead), encoding="utf-8")
    code2, out2, _ = sh(RDIR, "stop_pineapple_system.sh", PROF, ENV)
    return code2 == 0 and "web: stale_pidfile_removed" in out2 and not pf.exists(), f"{[l for l in out2.splitlines() if l.strip()]}"


check("S", "S11-STALE-PID", "過期 PID（程序已不存在）：移除 PID 檔，不終止任何程序", t_s11)


def t_s12():
    code, out, _ = sh(RDIR, "start_pineapple_system.sh", PROF, ENV)
    p = pids(SITE)
    code2, out2, _ = mgr(RDIR, "stop", PROF, args=("--timeout", "0"))   # 立即走強制路徑
    ext = all(e.poll() is None for e in EXTERNALS)
    gone = all(not pid_alive(x) for x in p.values())
    return code2 == 0 and out2.count("forced") == 3 and gone and ext, f"forced stop: {out2.strip().replace(chr(10), ' | ')}; own processes gone={gone}; external alive={ext}"


check("S", "S12-FORCED-STOP-OWNED-ONLY", "強制停止（逾時 0）：只結束本套件擁有的程序樹，外部同名程序存活", t_s12)


def t_s13():
    rows = []
    target = RDIR / "app/pineapple_app_gateway/app_gateway_v2.py"
    orig = target.read_bytes()
    v1 = (WT / "pineapple_app_gateway/app_gateway.py").read_bytes()
    target.write_bytes(v1)                                     # 有人把舊 Gateway v1 放到 v2 的位置
    code, out, _ = sh(RDIR, "start_pineapple_system.sh", PROF, ENV)
    rows.append(("v1 copied over v2", code, "RELEASE_INTEGRITY_FAILED" in out, bool(pids(SITE))))
    target.write_bytes(orig)
    code2, out2, _ = run([BASH, WT / "pineapple_app_gateway/start_server.sh"], env=ENV)
    rows.append(("legacy start_server.sh (ngrok)", code2, "REFUSED" in out2, port_open(5000)))
    names = tarfile.open(PKG).getnames()
    no_v1 = not any(n.endswith("app_gateway.py") for n in names)
    layout = json.loads((RDIR / "release_layout.json").read_text(encoding="utf-8"))
    ok = rows[0][1] == 2 and rows[0][2] and not rows[0][3] and rows[1][1] == 1 and rows[1][2] and not rows[1][3] and no_v1 and layout["gateway"].endswith("app_gateway_v2.py")
    return ok, f"{rows}; package contains app_gateway.py={not no_v1}; layout gateway={layout['gateway']}"


check("S", "S13-WRONG-GATEWAY-BLOCKED", "無法啟動錯誤 Gateway：v1 被放到 v2 位置 → 完整性失敗；舊 start_server.sh 拒絕執行；套件不含 v1", t_s13)


def t_s14():
    rows = []
    base = json.loads(PROF.read_text(encoding="utf-8"))
    cases = [("0.0.0.0", {"lan_access": True, "host": "0.0.0.0"}, "HOST_NOT_ALLOWED"),
             ("public IP", {"lan_access": True, "host": "8.8.8.8"}, "HOST_NOT_ALLOWED"),
             ("LAN IP without lan_access", {"lan_access": False, "host": "192.168.1.20"}, "HOST_NOT_ALLOWED"),
             ("hostname", {"lan_access": True, "host": "raspberrypi.local"}, "HOST_NOT_ALLOWED"),
             ("localhost iframe for LAN", {"lan_access": True, "host": "192.168.1.20", "smell": "http://127.0.0.1:5000"}, "URL_LOCALHOST_FOR_LAN"),
             ("duplicate ports", {"dup": True}, "PORT_CONFLICT_IN_PROFILE")]
    for label, c, want in cases:
        p = json.loads(json.dumps(base))
        p["lan_access"] = c.get("lan_access", False)
        if "host" in c:
            for s in p["services"].values():
                s["host"] = c["host"]
        if "smell" in c:
            p["services"]["unified"]["smell_url"] = c["smell"]
        if c.get("dup"):
            p["services"]["web"]["port"] = p["services"]["gateway"]["port"]
        f = write_json(SITE / "site" / "profile.case.json", p)
        code, out, _ = mgr(RDIR, "check", f)
        rows.append((label, code, want in out))
    f.unlink()
    lan = json.loads(json.dumps(base))
    lan["lan_access"] = True
    for s in lan["services"].values():
        s["host"] = "192.168.1.20"
    lan["services"]["unified"]["smell_url"] = "http://192.168.1.20:5000"
    f = write_json(SITE / "site" / "profile.lan.json", lan)
    code, out, _ = mgr(RDIR, "check", f)
    f.unlink()
    ok = all(c == 2 and hit for _, c, hit in rows) and code == 0
    return ok, f"rejected: {rows}; explicit private LAN profile (check only, not started) → exit {code}"


check("S", "S14-NETWORK-RULES", "網路規則：拒絕 0.0.0.0、公網 IP、主機名稱、未授權區網、區網用 localhost iframe、重複埠；明確的私有區網設定可通過檢查（不實際綁定）", t_s14)

# ═══ F. 正式模式＋測試專用 AIR 期限：模型閘門 ═══
SITE_F = RUN_ROOT / "site_formal_gate"
RDIR_F, _ = install(SITE_F, PKG)
PROF_F = site_config(SITE_F, RDIR_F, "formal", (15000, 15001, 18000), max_age=3600, serial_port="FAKE0")
CTL = RUN_ROOT / "fake_serial_control.json"
FLOG = RUN_ROOT / "fake_serial_events.jsonl"
ENV_FAKE = base_env({"FAKE_SERIAL_CONTROL": str(CTL), "FAKE_SERIAL_LOG": str(FLOG)}, fake_serial=True)

sys.path.insert(0, str(EVAL / "r1_controlled_retraining"))
from repaired_parser import read_raw_xlsx_fixed  # noqa: E402
RAW = WT / "enose_model_training/orkspace/data/raw"
PB = pd.read_csv(EVAL / "r1_controlled_retraining/pipeline_b_corrected_training.csv", encoding="utf-8-sig")
S99 = PB[PB.in_S99].reset_index(drop=True)
STEP5 = pd.read_csv(EVAL / "step5_offline_acceptance/full_replay_results.csv", encoding="utf-8-sig").set_index("fruit_day")


def lines_of(xlsx, n=None):
    df = read_raw_xlsx_fixed(str(RAW / xlsx))
    df = df[df[[f"{s}_raw" for s in SENS]].notna().all(axis=1)].reset_index(drop=True)
    if n:
        df = df.iloc[:n]
    return [",".join("" if pd.isna(r.get(c)) else str(r.get(c)) for c in HEADER) for _, r in df.iterrows()]


def serial(lines, **kw):
    write_json(CTL, {"lines": lines, "header": kw.get("header", True), "hang_after": kw.get("hang_after"), "raise_on_open": kw.get("raise_on_open", False)})


DAY0 = S99.iloc[0]
AIR0, FRUIT0 = lines_of(DAY0.air_file), lines_of(DAY0.fruit_file, 50)


def t_f02():
    code, out, _ = sh(RDIR_F, "start_pineapple_system.sh", PROF_F, ENV_FAKE)
    serial(AIR0)
    st, js = http("POST", "http://127.0.0.1:15001/calibrate", {})
    cal = wait_terminal("http://127.0.0.1:15001", js["scan_id"])
    air = json.loads((SITE_F / "data/formal/air/air_base.json").read_text(encoding="utf-8"))
    st2, s = http("POST", "http://127.0.0.1:15001/scan", {})
    st3, s3 = http("POST", "http://127.0.0.1:15001/scan", {"mode": "engineering"})
    hist = list((SITE_F / "data/formal/scan_history").glob("history_*.jsonl"))
    ok = (code == 0 and "MATURITY INFERENCE NOT APPROVED (MODEL_NOT_APPROVED)" in out and cal["status"] == "done" and air["_meta"]["mode"] == "formal"
          and st2 == 503 and s.get("error") == "MODEL_NOT_APPROVED" and st3 == 400 and s3.get("error") == "MODE_MISMATCH")
    return ok and not hist, (f"start exit {code}: {[l for l in out.splitlines() if 'gateway HTTP' in l]}; calibrate (non-model function) → {cal['status']} "
                             f"AIR mode={air['_meta']['mode']}; /scan → {st2} {s.get('error')}; client asks engineering → {st3} {s3.get('error')}; result history files={hist}")


check("F", "F02-FORMAL-MODEL-BLOCKING", "正式模式（核准清單空、測試專用 AIR 期限）：校正可用；成熟度推論 503 MODEL_NOT_APPROVED；前端不能切換到工程", t_f02)


def t_f03():
    st, h = http("GET", "http://127.0.0.1:15001/health")
    code, out, _ = sh(RDIR_F, "stop_pineapple_system.sh", PROF_F, ENV_FAKE)
    return (h["model_loaded"] is False and h["model_sha256"] is None and h["model_error"]["code"] == "MODEL_NOT_APPROVED" and code == 0),         f"formal /health: model_loaded={h['model_loaded']} model_sha256={h['model_sha256']} model_error={h['model_error']['code']} (no fallback to any old model)"


check("F", "F03-NO-FALLBACK-MODEL", "正式模式沒有載入任何模型（無舊模型 fallback）", t_f03)

# ═══ E. 工程（TEST）profile ═══
SITE_E = RUN_ROOT / "site_engineering"
RDIR_E, _ = install(SITE_E, PKG)
MODEL_DIR = RUN_ROOT / "engineering_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
ENG_MODEL = MODEL_DIR / "deploy_student.engineering.pkl"
shutil.copy2(DEPLOY_PKL, ENG_MODEL)
REG_E = {DEPLOY_SHA: {"status": "engineering", "feature_columns": FEATS}}
E_PORTS = (15100, 15101, 18100)


def eng_profile(model=None, registry=None, writable=False, name="profile.json"):
    os.chmod(ENG_MODEL, stat.S_IREAD | stat.S_IWRITE if writable else stat.S_IREAD)
    return site_config(SITE_E, RDIR_E, "engineering", E_PORTS, max_age=3600, registry=REG_E if registry is None else registry,
                       model=model or {"path": str(ENG_MODEL), "sha256": DEPLOY_SHA}, serial_port="FAKE0", unified=False, name=name)


def t_e01():
    rows = []
    for label, kw, want in (("writable model", {"writable": True}, "ENGINEERING_MODEL_NOT_READONLY"),
                            ("wrong sha256", {"model": {"path": str(ENG_MODEL), "sha256": "0" * 64}}, "MODEL_SHA256_MISMATCH"),
                            ("not registered", {"registry": {}}, "ENGINEERING_MODEL_NOT_REGISTERED"),
                            ("registered as approved", {"registry": {DEPLOY_SHA: {"status": "approved", "feature_columns": FEATS}}}, "ENGINEERING_MODEL_NOT_REGISTERED"),
                            ("missing model file", {"model": {"path": str(MODEL_DIR / "nope.pkl"), "sha256": DEPLOY_SHA}}, "MODEL_FILE_MISSING")):
        p = eng_profile(**kw)
        code, out, _ = sh(RDIR_E, "start_pineapple_system.sh", p, ENV_FAKE)
        rows.append((label, code, want in out, port_open(15101)))
    lan = json.loads(eng_profile().read_text(encoding="utf-8"))
    lan["lan_access"] = True
    f = write_json(SITE_E / "site/profile.lan.json", lan)
    code, out, _ = mgr(RDIR_E, "check", f)
    rows.append(("engineering with lan_access", code, "ENGINEERING_LAN_FORBIDDEN" in out, False))
    f.unlink()
    return all(c == 2 and hit and not up for _, c, hit, up in rows), f"{rows}"


check("E", "E01-ENGINEERING-MODEL-CHECKS", "工程模型必須：檔案存在、SHA-256 相符、唯讀、在清單登記為 engineering；工程 profile 不得開放區網", t_e01)

PROF_E = eng_profile()
code, out, _ = sh(RDIR_E, "start_pineapple_system.sh", PROF_E, ENV_FAKE)
rec("E", "E02-ENGINEERING-START", "工程 profile 啟動（唯讀模型、SHA-256 相符、本機）", code == 0 and "RUNNING" in out, out.strip().splitlines()[-1])
GW = "http://127.0.0.1:15101"
WEB = "http://127.0.0.1:15100"


def ref_proba(r):
    import pickle
    if not hasattr(ref_proba, "m"):
        ref_proba.m = pickle.load(open(DEPLOY_PKL, "rb"))
        ref_proba.m.set_params(n_jobs=1)
    return np.round(ref_proba.m.predict_proba(np.array([[float(r[f]) for f in FEATS]]))[0], 6)


replay_rows = []


def t_e03():
    for k, r in S99.head(N_REPLAY).iterrows():
        key = f"{int(r.pineapple_id):02d}/{r.date}"
        serial(lines_of(r.air_file))
        st, js = http("POST", f"{GW}/calibrate", {})
        cal = wait_terminal(GW, js["scan_id"])
        serial(lines_of(r.fruit_file, 50))
        st2, js2 = http("POST", f"{GW}/scan", {})
        res = wait_terminal(GW, js2["scan_id"])
        rr = res.get("result") or {}
        gp = np.array([rr.get("probabilities", {}).get(f"stage{i}", np.nan) for i in range(4)])
        exp_stage = int(STEP5.loc[key, "gateway_stage"])
        d = float(np.abs(gp - ref_proba(r)).max())
        replay_rows.append({"fruit_day": key, "calibration": cal["status"], "status": res["status"], "result_kind": res.get("result_kind"),
                            "stage": rr.get("stage"), "step5_stage": exp_stage, "max_proba_diff_vs_step5_reference": d,
                            "air_calibration_id_matches": rr.get("air_calibration_id") == json.loads((SITE_E / "data/engineering/air/air_base_test.json").read_text(encoding="utf-8"))["_meta"]["calibration_id"],
                            "verdict": "PASS" if (res["status"] == "done" and rr.get("result_kind") == "TEST" and rr.get("stage") == exp_stage and d <= 5e-7) else "FAIL"})
        if (k + 1) % 10 == 0:
            print(f"  replay {k + 1}/{N_REPLAY}", flush=True)
    df = pd.DataFrame(replay_rows)
    df.to_csv(HERE / "package_replay_results.csv", index=False, encoding="utf-8-sig")
    return (len(df) == N_REPLAY and (df.verdict == "PASS").all()), (f"{(df.verdict == 'PASS').sum()}/{len(df)} fruit-days: TEST label, stage == Step 5 accepted stage, "
                                                                    f"max |Δp| vs Step 5 reference = {df.max_proba_diff_vs_step5_reference.max():.1e}")


check("E", "E03-PACKAGE-REPLAY", f"經解壓套件的實際 HTTP 服務入口重播 {N_REPLAY} 個水果日：TEST 標記、Stage 與 Step 5 驗收結果相同、機率 ≤5e-7", t_e03)


def t_e04():
    serial(AIR0)
    st, page = http("POST", f"{WEB}/air", data="")
    air = json.loads((SITE_E / "data/engineering/air/air_base_test.json").read_text(encoding="utf-8"))
    serial(FRUIT0)
    st2, page2 = http("POST", f"{WEB}/infer", data="warmup_sec=0", timeout=300)
    raw = re.search(r"原始模型分類：Stage\s*(\d)", page2)
    exp = int(STEP5.loc[f"{int(DAY0.pineapple_id):02d}/{DAY0.date}", "gateway_stage"])
    ok = (st == 200 and air["_meta"]["source"] == "live" and air["_meta"]["mode"] == "engineering" and st2 == 200 and raw and int(raw.group(1)) == exp
          and "TEST（工程測試結果" in page2 and "結果類型：TEST" in page2)
    return ok, f"web /air → AIR mode={air['_meta']['mode']}; web /infer (local CLI) → Stage {raw.group(1) if raw else None} (Step 5: {exp}); TEST banner={'TEST（工程測試結果' in page2}"


check("E", "E04-WEB-PATH", "網頁路徑（本機模式執行同一支 CLI）：校正與推論成功，Stage 與 Step 5 相同，顯示 TEST", t_e04)


def t_e05():
    serial(FRUIT0, hang_after=12)
    st, js = http("POST", f"{GW}/scan", {})
    sid = js["scan_id"]
    time.sleep(1.5)
    serial(FRUIT0)
    st2, page = http("POST", f"{WEB}/infer", data="warmup_sec=0", timeout=120)
    busy = "DEVICE_BUSY" in page and "原始模型分類" not in page
    http("POST", f"{GW}/cancel", {"scan_id": sid})
    res = wait_terminal(GW, sid)
    return busy and res["status"] == "cancelled", f"web CLI while Gateway holds the sensor → DEVICE_BUSY={busy}; gateway scan then cancelled → {res['status']}"


check("E", "E05-CROSS-PROCESS-DEVICE-LOCK", "跨程序感測器互斥：Gateway 掃描中，網頁 CLI 回 DEVICE_BUSY（不同時讀同一個 Arduino）", t_e05)


def scan_case(lines, **kw):
    serial(lines, **kw)
    st, js = http("POST", f"{GW}/scan", {})
    if st != 200:
        return {"status": "rejected", "http": st, **js}
    return wait_terminal(GW, js["scan_id"], timeout=kw.get("timeout", 120))


def t_e06():
    rows = []
    v = list(FRUIT0)
    x = v[5].split(",")
    x[3] = "nan"
    v[5] = ",".join(x)
    for label, kw, want in (("ADC NaN", {"lines": v}, "ADC_INVALID"), ("no CSV header", {"lines": FRUIT0, "header": False}, "SERIAL_HEADER_TIMEOUT"),
                            ("only 20 rows", {"lines": FRUIT0[:20]}, "INSUFFICIENT_ROWS"), ("serial open fails", {"lines": FRUIT0, "raise_on_open": True}, "SCAN_ERROR")):
        lines = kw.pop("lines")
        r = scan_case(lines, **kw)
        rows.append((label, r["status"], r.get("reason_code"), r.get("result")))
    ap = SITE_E / "data/engineering/air/air_base_test.json"
    good = ap.read_bytes()
    a = json.loads(good)
    a["_meta"]["created_at"] = "2020-01-01T00:00:00+00:00"
    ap.write_text(json.dumps(a), encoding="utf-8")
    r = scan_case(FRUIT0)
    rows.append(("stale AIR", r["status"], r.get("reason_code"), r.get("result")))
    ap.write_text("{corrupt", encoding="utf-8")
    r = scan_case(FRUIT0)
    rows.append(("corrupt AIR", r["status"], r.get("reason_code"), r.get("result")))
    a = json.loads(good)
    a["_meta"]["source"] = "demo"
    ap.write_text(json.dumps(a), encoding="utf-8")
    r = scan_case(FRUIT0)
    rows.append(("demo AIR", r["status"], r.get("reason_code"), r.get("result")))
    ap.write_bytes(good)
    want = ["ADC_INVALID", "SERIAL_HEADER_TIMEOUT", "INSUFFICIENT_ROWS", "SCAN_ERROR", "AIR_EXPIRED", "AIR_INVALID_FILE", "AIR_SOURCE_NOT_ALLOWED"]
    ok = [x[2] for x in rows] == want and all(x[1] == "failed" and x[3] is None for x in rows)
    return ok, f"{[(l, s, c) for l, s, c, _ in rows]}"


check("E", "E06-INVALID-SCANS", "無效掃描（ADC NaN、無 header、資料不足、序列埠開啟失敗、過期／損毀／demo AIR）→ failed，沒有成熟度", t_e06)


def t_e07():
    before = sum(1 for _ in open(FLOG, encoding="utf-8")) if FLOG.exists() else 0
    serial(FRUIT0, hang_after=12)
    st, js = http("POST", f"{GW}/scan", {})
    time.sleep(1.5)
    c1 = http("POST", f"{GW}/cancel", {"scan_id": js["scan_id"]})
    c2 = http("POST", f"{GW}/cancel", {"scan_id": js["scan_id"]})
    r = wait_terminal(GW, js["scan_id"])
    time.sleep(0.5)
    ev = [json.loads(l)["event"] for l in open(FLOG, encoding="utf-8")][before:]
    return (r["status"] == "cancelled" and r["result"] is None and c1[0] == 200 and c2[0] == 200 and c2[1].get("already") is True and "close" in ev), \
        f"cancel → {r['status']}; repeated cancel → already={c2[1].get('already')}; serial events after scan start={ev}"


check("E", "E07-CANCEL", "掃描中取消（含重複取消）：cancelled、序列埠被關閉、沒有結果", t_e07)


def t_e08():
    t0 = time.time()
    gpid = json.loads((SITE_E / "data/engineering/run/gateway.pid.json").read_text(encoding="utf-8"))["pid"]
    if not port_open(15101):
        tail = (SITE_E / "data/engineering/logs/gateway.log").read_text(encoding="utf-8", errors="replace").splitlines()[-8:]
        return False, f"gateway not listening before E08 (pid {gpid} alive={pid_alive(gpid)}); log tail={tail}"
    r = scan_case(FRUIT0, hang_after=12, timeout=200)
    return r["status"] == "timed_out" and r["reason_code"] == "SCAN_TIMEOUT" and r["result"] is None, f"stuck serial read → {r['status']}/{r['reason_code']} after {time.time() - t0:.0f}s (real Gateway deadline)"


check("E", "E08-TIMEOUT", "序列埠讀取卡住：Gateway 期限到時 timed_out，結果作廢", t_e08)


def t_e09():
    bad = {DEPLOY_SHA: {"status": "engineering", "feature_columns": list(reversed(FEATS))}}
    sh(RDIR_E, "stop_pineapple_system.sh", PROF_E, ENV_FAKE)
    p = eng_profile(registry=bad)
    code, out, _ = sh(RDIR_E, "start_pineapple_system.sh", p, ENV_FAKE)
    st, s = http("POST", f"{GW}/scan", {})
    code2, out2, _ = sh(RDIR_E, "stop_pineapple_system.sh", p, ENV_FAKE)
    eng_profile()
    code3, out3, _ = sh(RDIR_E, "start_pineapple_system.sh", PROF_E, ENV_FAKE)
    return code == 0 and "MODEL ERROR (MODEL_FEATURE_MISMATCH)" in out and st == 503 and s.get("error") == "MODEL_FEATURE_MISMATCH" and code3 == 0, \
        f"registry feature order wrong → health '{[l for l in out.splitlines() if 'gateway HTTP' in l]}'; /scan {st} {s.get('error')}"


check("E", "E09-MODEL-ERROR", "模型錯誤（核准清單的特徵順序不符）：服務在線但回報 MODEL ERROR，掃描 503", t_e09)

# ═══ D. 資料完整性 ═══
def t_d01():
    eh = SITE_E / "data/engineering/scan_history"
    test_lines = [json.loads(l) for l in (eh / "history_test.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    fails = [json.loads(l) for l in (eh / "scan_failures.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    formal_files = sorted(p.name for p in (SITE_F / "data/formal/scan_history").glob("*")) if (SITE_F / "data/formal/scan_history").exists() else []
    no_formal_in_eng = not (eh / "history_formal.jsonl").exists()
    ok = (all(x["result_kind"] == "TEST" for x in test_lines) and len(test_lines) >= N_REPLAY and all(x.get("stage") is None for x in fails)
          and no_formal_in_eng and "history_formal.jsonl" not in formal_files and "history_test.jsonl" not in formal_files)
    return ok, f"engineering history_test lines={len(test_lines)} (all TEST); failure records={len(fails)} (stage=None); engineering history_formal exists={not no_formal_in_eng}; formal data files={formal_files}"


check("D", "D01-TEST-FORMAL-SEPARATION", "TEST 結果只在工程資料夾；正式資料夾沒有任何結果歷史；失敗只寫入 scan_failures（stage=None）", t_d01)


def t_d02():
    eh = SITE_E / "data/engineering/scan_history/history_test.jsonl"
    before = eh.read_bytes()
    sh(RDIR_E, "stop_pineapple_system.sh", PROF_E, ENV_FAKE)
    code, out, _ = sh(RDIR_E, "start_pineapple_system.sh", PROF_E, ENV_FAKE)
    serial(FRUIT0)
    r = scan_case(FRUIT0)
    after = eh.read_bytes()
    sh(RDIR_E, "stop_pineapple_system.sh", PROF_E, ENV_FAKE)
    return after.startswith(before) and len(after) > len(before) and r["status"] == "done", f"restart then one scan: previous {len(before)} bytes preserved as prefix, appended {len(after) - len(before)} bytes"


check("D", "D02-APPEND-ONLY-ACROSS-RESTART", "重啟後歷史保留：既有內容不變，新紀錄只追加", t_d02)


def t_d03():
    p = json.loads(PROF.read_text(encoding="utf-8"))
    p["data_root"] = str(SITE_E / "data/engineering")
    f = write_json(SITE / "site/profile.cross.json", p)
    code, out, _ = sh(RDIR, "start_pineapple_system.sh", f, ENV)
    f.unlink()
    return code == 2 and "DATA_ROOT_PROFILE_MISMATCH" in out, f"formal profile pointed at the engineering data folder → exit {code} {out.strip().splitlines()[-1][:120]}"


check("D", "D03-DATA-ROOT-BINDING", "資料夾與 profile 綁定：正式 profile 不能使用工程資料夾（反之亦然）", t_d03)


def t_d04():
    left = []
    for site, prof in ((SITE, PROF), (SITE_F, PROF_F), (SITE_E, PROF_E)):
        sh(site / "releases" / RID, "stop_pineapple_system.sh", prof, ENV_FAKE)
        for f in site.rglob("*.pid.json"):
            left.append(str(f))
    ports_free = not any(port_open(p) for p in (5000, 5001, 8000, 15000, 15001, 18000, 15100, 15101))
    ext = all(e.poll() is None for e in EXTERNALS)
    caches = [str(c) for site in (SITE, SITE_F, SITE_E) for c in (site / "releases").rglob("__pycache__")]
    return not left and ports_free and ext and not caches,         f"pid files left={left}; all package ports free={ports_free}; external same-name processes alive={ext}; __pycache__ in release dirs={caches}"


check("S", "S15-NO-LEFTOVER-PROCESSES", "全部停止後：沒有殘留本套件程序或 PID 檔，服務埠全部釋放；外部同名程序仍存活", t_d04)

for e in EXTERNALS:
    kill_tree(e.pid)                 # venv 啟動器會再產生子程序：結束整個測試用程序樹（只限本測試建立的外部模擬程序）
os.chmod(ENG_MODEL, stat.S_IREAD | stat.S_IWRITE)
df = pd.DataFrame(RESULTS)
df[df.group == "S"].to_csv(HERE / "startup_shutdown_test_results.csv", index=False, encoding="utf-8-sig")
df[df.group != "S"].to_csv(HERE / "release_package_test_results.csv", index=False, encoding="utf-8-sig")
n_fail = int((df.verdict != "PASS").sum())
print(f"\npackage tests: {int((df.verdict == 'PASS').sum())}/{len(df)} PASS; {time.time() - T0:.0f}s; package {PKG.name}")
sys.exit(1 if n_fail else 0)
