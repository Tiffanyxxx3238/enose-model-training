#!/usr/bin/env python3
"""
PineNose 安裝／備份／回復工具（Step 6A）。預設 dry-run：只列出將執行的動作；加上 --execute 才會修改檔案。

站點目錄（site root）布局：
  <S>/releases/<release_id>/   解壓後的發布套件（程式；唯讀使用）
  <S>/current_release          目前使用的 release_id（一行文字）
  <S>/site/                    站點設定：profile.json、runtime*.json、model_registry*.json
  <S>/data/<profile>/          使用者資料：air/、scan_history/（logs/、run/ 不備份）
  <S>/backups/<backup_id>/     備份

指令：
  install  --site S --package X.tar.gz [--execute]   驗證套件 SHA-256（X.tar.gz.sha256）→ 解壓到 releases/<id> → 驗證 SHA256SUMS
  backup   --site S [--execute]                      程式（目前 release）＋設定＋AIR＋掃描歷史 → backups/<id>/，產生 SHA-256 清單
  verify   --backup B                                重新計算備份內每個檔案的 SHA-256
  switch   --site S --release ID [--execute]         切換 current_release（服務的停止／啟動由操作人員以套件腳本執行）
  rollback --site S --backup B [--execute]           驗證備份 → 回復程式版本（必要時從備份還原 release 目錄）→ 切換 current_release
                                                     → 使用者資料「不覆寫」：只補回遺失的檔案；較新的歷史／AIR 一律保留；
                                                       不一致時把備份版本另存為 *.from_backup_<id> 並明確回報
                                                     → 不回復模型核准清單（不會把舊版模型自動變成已核准）

結束碼：0 成功／2 參數或狀態錯誤／3 完整性驗證失敗／4 回復時有需要人工處理的資料衝突（已保留雙方，未覆寫）
"""
import sys
sys.dont_write_bytecode = True          # 不在發布目錄寫入 __pycache__（套件目錄保持唯讀、與 SHA256SUMS 一致）
import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import time
from pathlib import Path

DATA_CATEGORIES = {"air": "air", "scan_history": "history"}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def say(dry, msg):
    print(("[DRY-RUN] " if dry else "[DO] ") + msg, flush=True)


def current_release(site):
    p = site / "current_release"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def write_atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def verify_release_dir(rdir):
    sums = rdir / "SHA256SUMS"
    if not sums.exists():
        return [f"{rdir.name}: SHA256SUMS missing"]
    bad = []
    for line in sums.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d, rel = line.split(None, 1)
            f = rdir / rel.strip().lstrip("*")
            if not f.exists() or sha256(f) != d:
                bad.append(rel.strip())
    return bad


# ── install ──
def cmd_install(a):
    site, pkg = Path(a.site), Path(a.package)
    dry = not a.execute
    side = Path(str(pkg) + ".sha256")
    if not side.exists():
        print(f"[FAIL] PACKAGE_CHECKSUM_MISSING: {side}")
        return 3
    want = side.read_text(encoding="utf-8").split()[0]
    got = sha256(pkg)
    if want != got:
        print(f"[FAIL] PACKAGE_CHECKSUM_MISMATCH: {got[:16]}… ≠ {want[:16]}…")
        return 3
    print(f"[OK] package sha256 {got}")
    with tarfile.open(pkg, "r:gz") as tf:
        names = tf.getnames()
        top = {n.split("/")[0] for n in names}
        if len(top) != 1:
            print(f"[FAIL] PACKAGE_LAYOUT_INVALID: {sorted(top)[:3]}")
            return 3
        rid = top.pop()
        if any(n.startswith("/") or ".." in Path(n).parts for n in names):
            print("[FAIL] PACKAGE_UNSAFE_PATHS")
            return 3
        dest = site / "releases" / rid
        if dest.exists():
            print(f"[FAIL] RELEASE_ALREADY_INSTALLED: {dest}（不覆寫既有 release）")
            return 2
        say(dry, f"extract {pkg.name} → {dest}")
        if not dry:
            (site / "releases").mkdir(parents=True, exist_ok=True)
            try:
                tf.extractall(site / "releases", filter="data")
            except TypeError:                     # Python 3.11.2（Bookworm）沒有 filter 參數；路徑已在上面檢查過
                tf.extractall(site / "releases")
    if not dry:
        bad = verify_release_dir(dest)
        if bad:
            print(f"[FAIL] RELEASE_INTEGRITY_FAILED: {bad[:5]}")
            return 3
        print(f"[OK] installed {rid}；SHA256SUMS 全部相符（尚未切換 current_release）")
    return 0


# ── backup ──
def cmd_backup(a):
    site = Path(a.site)
    dry = not a.execute
    rid = current_release(site)
    if not rid or not (site / "releases" / rid).exists():
        print(f"[FAIL] NO_CURRENT_RELEASE: {site / 'current_release'}")
        return 2
    bid = time.strftime("%Y%m%dT%H%M%S") + f"_{rid}"
    dest = site / "backups" / bid
    plan = [("program", site / "releases" / rid, dest / "program" / rid), ("config", site / "site", dest / "config")]
    for prof_dir in sorted((site / "data").glob("*")) if (site / "data").exists() else []:
        for sub, cat in DATA_CATEGORIES.items():
            if (prof_dir / sub).exists():
                plan.append((cat, prof_dir / sub, dest / "data" / prof_dir.name / sub))
    for cat, src, dst in plan:
        say(dry, f"copy [{cat}] {src} → {dst}")
    if dry:
        return 0
    files = []
    for cat, src, dst in plan:
        if not src.exists():
            continue
        shutil.copytree(src, dst)
        for f in sorted(dst.rglob("*")):
            if f.is_file():
                files.append({"path": f.relative_to(dest).as_posix(), "category": cat, "size": f.stat().st_size, "sha256": sha256(f)})
    man = {"backup_id": bid, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "site": str(site), "current_release": rid, "files": files}
    (dest / "backup_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    (dest / "BACKUP_SHA256SUMS").write_text("".join(f"{x['sha256']}  {x['path']}\n" for x in files), encoding="utf-8")
    cats = {}
    for x in files:
        cats[x["category"]] = cats.get(x["category"], 0) + 1
    print(f"[OK] backup {dest}：{len(files)} files {cats}")
    return 0


def verify_backup(bdir):
    mp = bdir / "backup_manifest.json"
    if not mp.exists():
        return None, ["backup_manifest.json missing"]
    man = json.loads(mp.read_text(encoding="utf-8"))
    bad = []
    for x in man["files"]:
        f = bdir / x["path"]
        if not f.exists():
            bad.append(f"missing {x['path']}")
        elif sha256(f) != x["sha256"]:
            bad.append(f"modified {x['path']}")
    return man, bad


def cmd_verify(a):
    man, bad = verify_backup(Path(a.backup))
    if bad:
        print(f"[FAIL] BACKUP_INTEGRITY_FAILED: {bad[:5]}")
        return 3
    print(f"[OK] backup {man['backup_id']}：{len(man['files'])} files verified")
    return 0


# ── switch ──
def cmd_switch(a):
    site = Path(a.site)
    dry = not a.execute
    rdir = site / "releases" / a.release
    if not rdir.exists():
        print(f"[FAIL] RELEASE_NOT_INSTALLED: {rdir}")
        return 2
    bad = verify_release_dir(rdir)
    if bad:
        print(f"[FAIL] RELEASE_INTEGRITY_FAILED: {bad[:5]}")
        return 3
    say(dry, f"current_release: {current_release(site)} → {a.release}")
    if not dry:
        write_atomic(site / "current_release", a.release + "\n")
    return 0


# ── rollback ──
def cmd_rollback(a):
    site, bdir = Path(a.site), Path(a.backup)
    dry = not a.execute
    man, bad = verify_backup(bdir)
    if bad:
        print(f"[FAIL] BACKUP_INTEGRITY_FAILED: {bad[:5]}（不做任何回復）")
        return 3
    rid = man["current_release"]
    rdir = site / "releases" / rid
    # 1) 程式
    if rdir.exists():
        if verify_release_dir(rdir):
            print(f"[FAIL] RELEASE_DIR_MODIFIED: {rdir} 與其 SHA256SUMS 不符；不覆寫，請人工檢查")
            return 3
        say(dry, f"program {rid} 已安裝且完整，直接使用")
    else:
        say(dry, f"restore program {bdir / 'program' / rid} → {rdir}")
        if not dry:
            shutil.copytree(bdir / "program" / rid, rdir)
            if verify_release_dir(rdir):
                print("[FAIL] RESTORED_RELEASE_INTEGRITY_FAILED")
                return 3
    say(dry, f"current_release: {current_release(site)} → {rid}")
    if not dry:
        write_atomic(site / "current_release", rid + "\n")
    # 2) 設定：不回復（模型核准清單尤其不回復，避免舊版／未核准模型被自動核准）；只回報差異
    for x in man["files"]:
        if x["category"] != "config":
            continue
        rel = Path(x["path"]).relative_to("config")
        cur = site / "site" / rel
        if not cur.exists():
            say(dry, f"config {rel} 目前不存在 → 從備份補回")
            if not dry and "model_registry" not in rel.name:
                cur.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bdir / x["path"], cur)
        elif sha256(cur) != x["sha256"]:
            print(f"[KEEP] config {rel}：保留目前版本（與備份不同；設定與核准清單不會被回復）")
    # 3) 使用者資料：只補回遺失檔；不覆寫較新的資料
    conflicts = 0
    for x in man["files"]:
        if x["category"] not in ("air", "history"):
            continue
        rel = Path(x["path"]).relative_to("data")
        cur = site / "data" / rel
        src = bdir / x["path"]
        if not cur.exists():
            say(dry, f"data {rel} 遺失 → 從備份補回")
            if not dry:
                cur.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, cur)
            continue
        if sha256(cur) == x["sha256"]:
            continue
        if x["category"] == "air":
            print(f"[KEEP] {rel}：保留目前的 AIR 校正（較新；不以舊校正覆寫）")
            continue
        if x["category"] == "history" and cur.read_bytes().startswith(src.read_bytes()):
            print(f"[KEEP] {rel}：目前的歷史是備份的延伸（較新紀錄），保留目前版本")
            continue
        conflicts += 1
        side = cur.with_name(cur.name + f".from_backup_{man['backup_id']}")
        print(f"[CONFLICT] {rel}：目前版本與備份不同且不是延伸；保留目前版本，備份版本另存 {side.name}（需人工確認）")
        if not dry:
            shutil.copy2(src, side)
    print(f"[{'DRY-RUN' if dry else 'OK'}] rollback to {rid}（資料衝突 {conflicts}）；請以套件的 stop／start 腳本重新啟動服務")
    return 4 if conflicts else 0


def main():
    ap = argparse.ArgumentParser(description="PineNose install / backup / rollback (dry-run by default)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, args in (("install", ["--site", "--package"]), ("backup", ["--site"]), ("verify", ["--backup"]),
                       ("switch", ["--site", "--release"]), ("rollback", ["--site", "--backup"])):
        p = sub.add_parser(name)
        for x in args:
            p.add_argument(x, required=True)
        if name != "verify":
            p.add_argument("--execute", action="store_true", help="實際執行（預設只 dry-run）")
    a = ap.parse_args()
    return {"install": cmd_install, "backup": cmd_backup, "verify": cmd_verify, "switch": cmd_switch, "rollback": cmd_rollback}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
