#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
  Game Upload Pipeline — Operation Web (Rezona Create Pro)
═══════════════════════════════════════════════════════════════

Folder structure:
  upload-pipeline/
  ├── games.csv
  ├── games/               ← ZIPs to upload (drop here, filename = key)
  ├── fixed games/         ← fixed ZIPs (<name>_fixed.zip)
  ├── covers/              ← cover images (<name>.jpg, cùng tên zip)
  ├── results.csv          ← output with Share URL + Reupload URL
  └── upload_games.py

Usage:
  # First upload
  python3 upload_games.py --dry-run
  python3 upload_games.py --workers 5

  # Reupload fixed games
  python3 upload_games.py --reupload --dry-run
  python3 upload_games.py --reupload --workers 5

  # Resume either mode
  python3 upload_games.py --resume
  python3 upload_games.py --reupload --resume

Requirements:
  pip install requests
"""

import argparse
import csv
import mimetypes
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock

try:
    import requests
except ImportError:
    print("ERROR: pip install requests")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════

DEFAULT_HOST     = "http://34.149.226.142"
DEFAULT_PASSWORD = "rezona666"
DEFAULT_CSV      = "games.csv"
DEFAULT_ZIPS     = "./games"
DEFAULT_FIXED    = "./fixed games"
DEFAULT_COVERS   = "./covers"
DEFAULT_OUTPUT   = "results.csv"
POLL_INTERVAL    = 2
POLL_TIMEOUT     = 300
MAX_RETRIES      = 2
RETRY_DELAY      = 3

# ═══════════════════════════════════════════════════════════
#  GLOBALS
# ═══════════════════════════════════════════════════════════

HOST = DEFAULT_HOST
PASSWORD = DEFAULT_PASSWORD
_lock = Lock()
_stats = {"ok": 0, "fail": 0, "skip": 0}


def log(tag, msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    sym = {"INFO": " ", "OK": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "→"}.get(level, " ")
    with _lock:
        print(f"  {ts} {sym} [{tag:>20s}] {msg}", flush=True)


# ═══════════════════════════════════════════════════════════
#  HTTP
# ═══════════════════════════════════════════════════════════

def _headers(extra=None):
    h = {"x-operation-web-password": PASSWORD}
    if extra:
        h.update(extra)
    return h


def _api(method, path, retries=MAX_RETRIES, **kwargs):
    url = f"{HOST}{path}"
    kwargs.setdefault("timeout", 30)
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, url, **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last_err = e
            if attempt < retries:
                time.sleep(RETRY_DELAY * (attempt + 1))
    raise last_err


# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def extract_title(zip_path):
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for n in zf.namelist():
                if n.endswith("index.html"):
                    html = zf.read(n).decode("utf-8", errors="replace")
                    m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
                    if m:
                        return m.group(1).strip()
                    break
    except Exception:
        pass
    return "Untitled Game"


def find_cover(game_uuid, covers_dir):
    covers_path = Path(covers_dir)
    if not covers_path.is_dir():
        return None, None
    uuid_lower = game_uuid.lower()
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        candidate = covers_path / f"{game_uuid}{ext}"
        if candidate.exists():
            return str(candidate), mimetypes.guess_type(str(candidate))[0] or "image/jpeg"
    for f in covers_path.iterdir():
        if f.stem.lower() == uuid_lower and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            return str(f), mimetypes.guess_type(str(f))[0] or "image/jpeg"
    return None, None


# ═══════════════════════════════════════════════════════════
#  API CALLS
# ═══════════════════════════════════════════════════════════

def api_check_auth():
    r = _api("GET", "/operation/auth/status", headers=_headers())
    return r.json().get("authenticated", False)


def api_upload_zip(zip_path, filename):
    with open(zip_path, "rb") as f:
        r = _api("POST", "/operation/workspace-uploads",
                 headers=_headers({
                     "Content-Type": "application/zip",
                     "x-operation-upload-filename": filename,
                 }),
                 data=f, timeout=120)
    d = r.json().get("data", {})
    if isinstance(d, dict):
        return d.get("upload_id") or d.get("id") or ""
    return str(d) if d else ""


def api_create_build(upload_id, user_id):
    r = _api("POST", "/operation/workspace-jobs",
             headers=_headers({"Content-Type": "application/json"}),
             json={"upload_id": upload_id, "user_id": user_id, "mode": "html_direct"})
    d = r.json().get("data", {})
    return d.get("game_id"), d.get("version_id")


def api_poll_build(game_id, version_id, tag):
    start = time.time()
    prev = ""
    while time.time() - start < POLL_TIMEOUT:
        r = _api("GET", f"/operation/workspace-jobs/{game_id}/{version_id}",
                 headers=_headers(), retries=1)
        d = r.json().get("data", {})
        stage = d.get("build_stage", "")
        status = d.get("job_status", "")
        if stage != prev:
            log(tag, f"build → {stage}")
            prev = stage
        if status == "done":
            return True
        if status == "failed":
            log(tag, f"build failed: {d.get('error_message', '?')}", "FAIL")
            return False
        time.sleep(POLL_INTERVAL)
    log(tag, "build timeout", "FAIL")
    return False


def api_upload_cover(cover_path, cover_mime):
    filename = os.path.basename(cover_path)
    with open(cover_path, "rb") as f:
        r = _api("POST", "/operation/cover-uploads",
                 headers=_headers({
                     "Content-Type": cover_mime,
                     "x-operation-upload-filename": filename,
                 }),
                 data=f, timeout=60)
    return r.json().get("data", {}).get("url", "")


def api_publish(game_id, version_id, user_id, name, cover_url):
    r = _api("POST", f"/operation/workspace-jobs/{game_id}/{version_id}/publish",
             headers=_headers({
                 "Content-Type": "application/json",
                 "x-user-id": str(user_id),
             }),
             json={
                 "name": name,
                 "is_public": True,
                 "cover_url": cover_url or "",
                 "dynamic_cover_url": "",
             })
    return r.json().get("data", {}).get("share_url", "")


# ═══════════════════════════════════════════════════════════
#  PIPELINE (one game)
# ═══════════════════════════════════════════════════════════

def process_one(user_id, game_uuid, zip_path, covers_dir):
    tag = game_uuid[:16]
    try:
        title = extract_title(zip_path)
        cover_path, cover_mime = find_cover(game_uuid, covers_dir)
        log(tag, f"'{title}' | cover={'✓' if cover_path else '✗'}")

        log(tag, "uploading zip...")
        upload_id = api_upload_zip(zip_path, os.path.basename(zip_path))
        if not upload_id:
            log(tag, "no upload_id", "FAIL")
            return game_uuid, "", "upload: no upload_id"
        log(tag, f"upload_id={upload_id[:16]}...")

        log(tag, "creating build...")
        game_id, version_id = api_create_build(upload_id, user_id)
        if not game_id:
            log(tag, "build create failed", "FAIL")
            return game_uuid, "", "build create failed"
        log(tag, f"game={game_id} ver={version_id}")

        if not api_poll_build(game_id, version_id, tag):
            return game_uuid, "", "build failed"
        log(tag, "build done!", "OK")

        cover_url = ""
        if cover_path:
            log(tag, "uploading cover...")
            cover_url = api_upload_cover(cover_path, cover_mime)

        log(tag, f"publishing '{title}'...")
        share_url = api_publish(game_id, version_id, user_id, title, cover_url)
        if share_url:
            log(tag, share_url, "OK")
            with _lock:
                _stats["ok"] += 1
            return game_uuid, share_url, ""
        else:
            log(tag, "no share_url", "FAIL")
            with _lock:
                _stats["fail"] += 1
            return game_uuid, "", "publish: no share_url"

    except Exception as e:
        log(tag, str(e), "FAIL")
        with _lock:
            _stats["fail"] += 1
        return game_uuid, "", str(e)


# ═══════════════════════════════════════════════════════════
#  RESULTS CSV (with both Share URL and Reupload URL)
# ═══════════════════════════════════════════════════════════

COLUMNS = ["User ID", "Game UUID", "Source", "Share URL", "Error", "Reupload URL", "Reupload Error"]


def load_results(path):
    """Load existing results.csv → dict keyed by UUID."""
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return rows
        for row in reader:
            if len(row) >= 2:
                uuid = row[1]
                rows[uuid] = {
                    "uid": row[0] if len(row) > 0 else "",
                    "src": row[2] if len(row) > 2 else "",
                    "share": row[3] if len(row) > 3 else "",
                    "error": row[4] if len(row) > 4 else "",
                    "reupload": row[5] if len(row) > 5 else "",
                    "reup_error": row[6] if len(row) > 6 else "",
                }
    return rows


class ResultWriter:
    def __init__(self, path, all_tasks, mode="normal"):
        self.path = path
        self.all_tasks = all_tasks  # [(uid, uuid, src), ...]
        self.mode = mode  # "normal" or "reupload"
        self._lock = Lock()

        # Load existing data
        self.data = load_results(path)

        # Ensure all tasks have an entry
        for uid, uuid, src in all_tasks:
            if uuid not in self.data:
                self.data[uuid] = {"uid": str(uid), "src": src, "share": "", "error": "", "reupload": "", "reup_error": ""}

    def add(self, uuid, share_url, error):
        with self._lock:
            if uuid not in self.data:
                self.data[uuid] = {"uid": "", "src": "", "share": "", "error": "", "reupload": "", "reup_error": ""}
            if self.mode == "normal":
                if share_url:
                    self.data[uuid]["share"] = share_url
                if error:
                    self.data[uuid]["error"] = error
            else:  # reupload
                if share_url:
                    self.data[uuid]["reupload"] = share_url
                if error:
                    self.data[uuid]["reup_error"] = error

    def get_errors(self):
        with self._lock:
            if self.mode == "normal":
                return {uuid: d["error"] for uuid, d in self.data.items() if d["error"]}
            else:
                return {uuid: d["reup_error"] for uuid, d in self.data.items() if d["reup_error"]}

    def write(self):
        with self._lock:
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(COLUMNS)
                for uid, uuid, src in self.all_tasks:
                    d = self.data.get(uuid, {})
                    w.writerow([
                        uid,
                        uuid,
                        src,
                        d.get("share", ""),
                        d.get("error", ""),
                        d.get("reupload", ""),
                        d.get("reup_error", ""),
                    ])


# ═══════════════════════════════════════════════════════════
#  BUILD ZIP LOOKUP
# ═══════════════════════════════════════════════════════════

def build_zip_lookup(zips_dir, fixed=False):
    """Build UUID → Path lookup.
    If fixed=True, strips '_fixed' from stem to get UUID.
    """
    lookup = {}
    d = Path(zips_dir)
    if not d.is_dir():
        return lookup
    for f in d.iterdir():
        if f.suffix.lower() != ".zip":
            continue
        stem = f.stem.lower()
        if fixed:
            # "uuid_fixed" → "uuid"
            stem = stem.replace("_fixed", "")
        lookup[stem] = f
    return lookup


def build_cover_lookup(covers_dir):
    s = set()
    d = Path(covers_dir)
    if not d.is_dir():
        return s
    for f in d.iterdir():
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            s.add(f.stem.lower())
    return s


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Upload game ZIPs to Operation Web",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--csv", default=DEFAULT_CSV)
    parser.add_argument("--zips", default=DEFAULT_ZIPS, help=f"ZIP folder (default: {DEFAULT_ZIPS})")
    parser.add_argument("--fixed", default=DEFAULT_FIXED, help=f"Fixed ZIPs folder (default: {DEFAULT_FIXED})")
    parser.add_argument("--covers", default=DEFAULT_COVERS, help=f"Covers folder (default: {DEFAULT_COVERS})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Skip already-done")
    parser.add_argument("--reupload", action="store_true", help="Upload from 'fixed games' folder, write to Reupload URL column")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    args = parser.parse_args()

    global HOST, PASSWORD
    HOST = args.host.rstrip("/")
    PASSWORD = args.password

    mode = "reupload" if args.reupload else "normal"
    zips_folder = args.fixed if args.reupload else args.zips

    print("═" * 60)
    print(f"  Game Upload Pipeline {'(REUPLOAD)' if args.reupload else ''}")
    print("═" * 60)
    print(f"  Host:    {HOST}")
    print(f"  CSV:     {args.csv}")
    print(f"  ZIPs:    {zips_folder}")
    print(f"  Covers:  {args.covers}")
    print(f"  Workers: {args.workers}")
    print(f"  Mode:    {mode}")
    print()

    # ── Read CSV ─────────────────────────────────────────
    tasks = []
    with open(args.csv, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) < 2:
                continue
            tasks.append((int(row[0].strip()), row[1].strip(), row[2].strip() if len(row) > 2 else ""))
    print(f"  CSV:    {len(tasks)} games")

    # ── Find ZIPs ────────────────────────────────────────
    zip_lookup = build_zip_lookup(zips_folder, fixed=args.reupload)
    cover_lookup = build_cover_lookup(args.covers)

    ready, no_zip, no_cover = [], [], 0
    for uid, uuid, src in tasks:
        zp = zip_lookup.get(uuid.lower())
        if not zp:
            no_zip.append(uuid)
            continue
        ready.append((uid, uuid, src, str(zp)))
        if uuid.lower() not in cover_lookup:
            no_cover += 1

    print(f"  ZIPs:   {len(ready)} found, {len(no_zip)} not in folder")
    print(f"  Covers: {len(ready) - no_cover} found, {no_cover} missing")

    if no_zip and not args.reupload:
        for u in no_zip[:5]:
            print(f"    MISSING: {u}")
        if len(no_zip) > 5:
            print(f"    ... +{len(no_zip)-5} more")

    # ── Resume ───────────────────────────────────────────
    previous_done = set()
    if args.resume:
        prev_data = load_results(args.output)
        for uuid, d in prev_data.items():
            if mode == "normal" and d.get("share", "").startswith("https://"):
                previous_done.add(uuid)
            elif mode == "reupload" and d.get("reupload", "").startswith("https://"):
                previous_done.add(uuid)
        if previous_done:
            print(f"  Resume: {len(previous_done)} already done")

    # ── Dry run ──────────────────────────────────────────
    if args.dry_run:
        col = "Reupload URL" if args.reupload else "Share URL"
        print(f"\n{'─'*60}")
        print(f"  DRY RUN — {len(ready)} games → {col}")
        print(f"{'─'*60}\n")
        for uid, uuid, _, zp in ready:
            done = uuid in previous_done
            title = extract_title(zp)
            has_cover = uuid.lower() in cover_lookup
            size_kb = os.path.getsize(zp) // 1024
            if done:
                status = "DONE"
            elif has_cover:
                status = "ready"
            else:
                status = "no cover"
            sym = "✓" if (done or has_cover) else "⚠"
            print(f"  {sym} user={uid:>8} | {uuid[:20]}... | {size_kb:>5}KB | {status:>9} | {title}")
        return

    # ── Auth ─────────────────────────────────────────────
    print("\n  Auth...", end=" ", flush=True)
    if not api_check_auth():
        print("FAILED")
        sys.exit(1)
    print("OK")

    # ── Filter ───────────────────────────────────────────
    to_process = [(uid, uuid, src, zp) for uid, uuid, src, zp in ready if uuid not in previous_done]
    skipped = len(ready) - len(to_process)

    if not to_process:
        print("\n  Nothing to do!")
        return

    # ── Run ──────────────────────────────────────────────
    writer = ResultWriter(args.output, tasks, mode=mode)
    _stats["skip"] = skipped

    print(f"\n{'═'*60}")
    print(f"  Uploading {len(to_process)} games ({skipped} skipped)")
    print(f"{'═'*60}\n")

    t0 = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {
            pool.submit(process_one, uid, uuid, zp, args.covers): (uid, uuid, src)
            for uid, uuid, src, zp in to_process
        }

        done_count = 0
        total = len(to_process)

        for fut in as_completed(futs):
            uid, uuid, src = futs[fut]
            done_count += 1
            try:
                _, url, err = fut.result()
                writer.add(uuid, url, err)
            except Exception as e:
                writer.add(uuid, "", str(e))
                with _lock:
                    _stats["fail"] += 1

            if done_count % 3 == 0 or done_count == total:
                writer.write()
                elapsed = time.time() - t0
                rate = done_count / elapsed * 60 if elapsed > 0 else 0
                with _lock:
                    print(f"\n  ── {done_count}/{total} "
                          f"({_stats['ok']}✓ {_stats['fail']}✗) "
                          f"[{rate:.1f}/min] ──\n", flush=True)

    writer.write()
    elapsed = time.time() - t0

    errors = writer.get_errors()

    print(f"\n{'═'*60}")
    print(f"  DONE {'(REUPLOAD)' if args.reupload else ''}")
    print(f"{'═'*60}")
    print(f"  Published:  {_stats['ok']}")
    print(f"  Failed:     {_stats['fail']}")
    print(f"  Skipped:    {_stats['skip']}")
    print(f"  Time:       {elapsed/60:.1f} min")
    print(f"  Output:     {args.output}")
    print(f"{'═'*60}")

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for uuid, err in list(errors.items())[:20]:
            print(f"    {uuid[:24]}: {err[:80]}")


if __name__ == "__main__":
    main()