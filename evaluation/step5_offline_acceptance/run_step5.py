"""
Step 5 驗收總執行器：依序執行所有實際測試，記錄指令、結束碼、耗時與輸出 → logs/、test_commands_and_logs.md、彙整 CSV。

需要的外部工具（以參數指定，不修改系統設定）：
  --pinned-python  釘選版本 venv（Python 3.12.7＋requirements_rpi.txt：sklearn 1.8.0、numpy 2.4.3、pandas 3.0.1）
  --local-python   本機 Python 3.10（sklearn 1.7.1，交叉環境）
  --node-bin       含 node／npm shim 的資料夾（VS Code Electron 以 ELECTRON_RUN_AS_NODE 作為 Node v24）
  --testdeps       react-test-renderer@19.1.0 所在資料夾（只供測試）
  --mirror-root    ASCII 路徑的鏡像資料夾（eslint 的 TS 解析器無法處理含中文與空白的路徑；鏡像內容逐檔 SHA-256 驗證）
"""
import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
WT = EVAL.parent
REPO = WT.parent
LOGS = HERE / "logs"
APPS = {"consumer": WT / "app/Consumer_pineapple-ripeness-main/expo", "farmer": WT / "app/Farmer_pineapple-ripeness-main"}
RUNS = []


def run(step, cmd, cwd, env=None, timeout=3600, log=None, show=None):
    t0 = time.time()
    log = log or f"{step}.log"
    with open(LOGS / log, "w", encoding="utf-8", errors="replace") as fh:
        fh.write(f"$ {' '.join(str(c) for c in cmd)}\n# cwd: {cwd}\n\n")
        fh.flush()
        try:
            p = subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
            code = p.returncode
        except subprocess.TimeoutExpired:
            code = "TIMEOUT"
    dt = round(time.time() - t0, 1)
    RUNS.append({"step": step, "command": " ".join(str(c) for c in (show or cmd)), "cwd": str(Path(cwd).relative_to(REPO)) if str(cwd).startswith(str(REPO)) else str(cwd),
                 "exit_code": code, "seconds": dt, "log": f"logs/{log}"})
    print(f"[{step}] exit={code} {dt}s → logs/{log}", flush=True)
    return code


def tail(log, n=6):
    lines = (LOGS / log).read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])


def mirror(src, dst):
    """逐檔複製（不含 node_modules），node_modules 以 junction 連結；回傳驗證過的檔案數。"""
    if dst.exists():
        nm = dst / "node_modules"
        if nm.exists():
            subprocess.run(["cmd", "/c", "rmdir", str(nm)], capture_output=True)
        shutil.rmtree(dst)
    n = 0
    for f in src.rglob("*"):
        rel = f.relative_to(src)
        if rel.parts and rel.parts[0] in ("node_modules", ".expo", "dist"):
            continue
        if f.is_file():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst / rel)
            assert hashlib.sha256(f.read_bytes()).digest() == hashlib.sha256((dst / rel).read_bytes()).digest()
            n += 1
    subprocess.run(["cmd", "/c", "mklink", "/J", str(dst / "node_modules"), str(src / "node_modules")], capture_output=True, check=True)
    return n


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pinned-python", required=True)
    ap.add_argument("--local-python", required=True)
    ap.add_argument("--node-bin", required=True)
    ap.add_argument("--node-exe", required=True)
    ap.add_argument("--testdeps", required=True)
    ap.add_argument("--mirror-root", required=True)
    a = ap.parse_args()
    LOGS.mkdir(exist_ok=True)
    for f in LOGS.glob("*"):
        if not f.name.startswith("manual_"):        # 保留手動保存的修正前證據
            f.unlink()
    PY, PYL = a.pinned_python, a.local_python
    penv = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONWARNINGS": "ignore"}
    # Node：VS Code 內建的 Electron 以 ELECTRON_RUN_AS_NODE=1 當作 Node v24 使用（直接呼叫執行檔，避免 .cmd 對含括號路徑的解析問題）
    nenv = {**penv, "PATH": a.node_bin + os.pathsep + os.environ["PATH"], "EXPO_OFFLINE": "1", "EXPO_NO_TELEMETRY": "1", "CI": "1", "ELECTRON_RUN_AS_NODE": "1"}
    node = a.node_exe

    # ── A. Python 後端 ──
    reg = EVAL / "_step4b_regression_run"
    if reg.exists():
        shutil.rmtree(reg)
    reg.mkdir()
    for f in ("step4b_tests.py", "run_mutations.py"):
        shutil.copy(EVAL / "step4b_safeguards" / f, reg / f)      # 在複本中執行，不覆寫 Step 4B 的既有報告
    run("A1_step4b_regression_pinned", [PY, "-u", reg / "step4b_tests.py"], EVAL, penv)
    run("A2_step4b_mutation_check_pinned", [PY, "-u", reg / "run_mutations.py"], EVAL, penv)
    shutil.copy(reg / "test_results.csv", HERE / "step4b_regression_results.csv")
    shutil.copy(reg / "mutation_check.csv", HERE / "step4b_mutation_check.csv")
    shutil.copy(reg / "run_log.txt", LOGS / "A1_step4b_regression_detail.log")
    shutil.rmtree(reg)
    run("A3_lifecycle_pinned", [PY, "-u", HERE / "lifecycle_tests.py"], HERE, penv)

    # ── C. 完整重播 ──
    run("C1_full_replay_pinned", [PY, "-u", HERE / "full_replay.py"], HERE, {**penv, "REPLAY_TAG": ""})
    run("C2_full_replay_local_py310", [PYL, "-u", HERE / "full_replay.py"], HERE, {**penv, "REPLAY_TAG": "_py310_sklearn171"})

    # ── D. 發布一致性 ──
    run("D1_release_check_pinned", [PY, "-u", HERE / "release_check.py"], HERE, penv)

    # ── B. App 建置 ──
    mroot = Path(a.mirror_root)
    for name, root in APPS.items():
        run(f"B_{name}_tsc", [node, root / "node_modules/typescript/bin/tsc", "--noEmit", "-p", "."], root, nenv,
            show=["node", "node_modules/typescript/bin/tsc", "--noEmit", "-p", "."])
        m = mroot / name
        nfiles = mirror(root, m)
        (LOGS / f"B_{name}_mirror.log").write_text(f"mirror {root} -> {m}: {nfiles} files copied and SHA-256 verified; node_modules junction\n", encoding="utf-8")
        temp_cfg = False
        if not (m / "eslint.config.js").exists():
            shutil.copy(APPS["consumer"] / "eslint.config.js", m / "eslint.config.js")   # Farmer 沒有 lint 設定：暫時套用 Consumer 的 Expo 設定（只在鏡像）
            temp_cfg = True
        run(f"B_{name}_eslint{'_tempconfig' if temp_cfg else ''}", [node, m / "node_modules/eslint/bin/eslint.js", "."], m, nenv,
            show=["node", "node_modules/eslint/bin/eslint.js", "."])
        if temp_cfg:
            (m / "eslint.config.js").unlink()
        for plat in ("web", "android"):
            out = mroot / f"build-{name}-{plat}"
            run(f"B_{name}_export_{plat}", [node, m / "node_modules/expo/bin/cli", "export", "--platform", plat, "--output-dir", out], m, nenv,
                show=["node", "node_modules/expo/bin/cli", "export", "--platform", plat, "--output-dir", f"<mirror>/build-{name}-{plat}"])
        if name == "farmer":
            run("B_farmer_smoke_test", [node, root / "scripts/smoke-test.js"], root, nenv, show=["node", "scripts/smoke-test.js"])

    # ── B. App × Gateway 整合 ──
    gp, cp = free_port(), free_port()
    work = mroot / "backend_tmp"
    bl = open(LOGS / "B_backend_harness.log", "w", encoding="utf-8")
    backend = subprocess.Popen([PY, "-u", str(HERE / "backend_harness.py"), "--port", str(gp), "--ctl-port", str(cp), "--workdir", str(work)],
                               cwd=str(HERE), env=penv, stdout=bl, stderr=subprocess.STDOUT)
    for _ in range(300):
        if "READY" in (LOGS / "B_backend_harness.log").read_text(encoding="utf-8", errors="replace"):
            break
        time.sleep(1)
    try:
        for name, root in APPS.items():
            out = HERE / f"_app_results_{name}.json"
            run(f"B_{name}_app_integration", [node, HERE / "app_integration_tests.js"], HERE,
                {**nenv, "APP": name, "APP_ROOT": str(root), "TESTDEPS": a.testdeps, "GW_URL": f"http://127.0.0.1:{gp}", "CTL_URL": f"http://127.0.0.1:{cp}",
                 "RESULTS_OUT": str(out)}, show=["node", "app_integration_tests.js", f"(APP={name})"])
        out = HERE / "_app_results_payloads.json"
        run("B_consumer_validate_replay_payloads", [node, HERE / "app_integration_tests.js"], HERE,
            {**nenv, "APP": "consumer", "APP_ROOT": str(APPS["consumer"]), "TESTDEPS": a.testdeps, "GW_URL": "", "CTL_URL": "",
             "RESULTS_OUT": str(out), "VALIDATE_PAYLOADS": str(HERE / "_replay_payloads.json")}, show=["node", "app_integration_tests.js", "(VALIDATE_PAYLOADS)"])
    finally:
        backend.terminate()
        backend.wait(30)
        bl.close()
        shutil.rmtree(work, ignore_errors=True)

    # ── 彙整 ──
    app_rows = []
    for f in ("_app_results_consumer.json", "_app_results_farmer.json", "_app_results_payloads.json"):
        p = HERE / f
        if p.exists():
            app_rows += json.loads(p.read_text(encoding="utf-8"))
    gw = json.loads((HERE / "_gateway_contract_rows.json").read_text(encoding="utf-8"))
    contract = [{"layer": r["layer"], "id": "", "endpoint": r["endpoint"], "condition": r["condition"],
                 "expected": f"HTTP {r['expected_http']} {r['expected_error'] or ''}".strip(), "actual": f"HTTP {r['actual_http']} {r['actual_error'] or ''}".strip(),
                 "kind": "RUNTIME (Gateway v2 via Flask test client; fake serial)", "verdict": r["verdict"]} for r in gw]
    STORAGE_IDS = {"APP-C18", "APP-C19", "APP-C20", "APP-C21"}
    contract += [{"layer": f"{r['app']} App API client / screens", "id": r["id"], "endpoint": "", "condition": r["test"], "expected": "", "actual": r["evidence"],
                  "kind": r["kind"], "verdict": r["verdict"]} for r in app_rows if r["id"] not in STORAGE_IDS]
    pd.DataFrame(contract).to_csv(HERE / "api_contract_results.csv", index=False, encoding="utf-8-sig")
    stor = pd.read_csv(HERE / "_storage_python.csv", encoding="utf-8-sig").assign(layer="Gateway / safety layer (Python)")
    stor_app = pd.DataFrame([{"group": "STORAGE", "id": r["id"], "test": r["test"], "entrypoint": "Consumer App HistoryContext/storage/api", "kind": r["kind"],
                              "verdict": r["verdict"], "evidence": r["evidence"], "layer": "Consumer App (TypeScript)"} for r in app_rows if r["id"] in STORAGE_IDS])
    pd.concat([stor, stor_app], ignore_index=True).to_csv(HERE / "storage_integrity_results.csv", index=False, encoding="utf-8-sig")
    (HERE / "_runs.json").write_text(json.dumps(RUNS, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# Step 5 — test commands, exit codes and logs", "",
          "Generated by `run_step5.py`. All tests are offline: fake serial ports, Flask test clients or a loopback-only test backend. No real hardware, no Pi, no SSH.", "",
          "| step | command | cwd | exit | seconds | log |", "|---|---|---|---|---|---|"]
    md += [f"| {r['step']} | `{r['command'][:160]}` | `{r['cwd'][:70]}` | {r['exit_code']} | {r['seconds']} | {r['log']} |" for r in RUNS]
    md += ["", "## Output tails", ""]
    for r in RUNS:
        md += [f"### {r['step']} (exit {r['exit_code']})", "```", tail(Path(r["log"]).name, 8), "```", ""]
    (HERE / "test_commands_and_logs.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps([(r["step"], r["exit_code"]) for r in RUNS], ensure_ascii=False))


if __name__ == "__main__":
    main()
