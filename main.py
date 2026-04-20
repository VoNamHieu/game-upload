"""
Auto SFX/BGM Tool — Main Pipeline

Usage:
    python main.py                           # process all, skip already done, 5 parallel
    python main.py -j 3                      # 3 parallel workers
    python main.py -j 1                      # sequential (for debugging)
    python main.py --force                   # reprocess everything
    python main.py --rerun merged/_rerun_list.txt  # only process failed files
    python main.py game1.zip game2.zip       # process specific files
    python main.py --dry-run game1.zip       # analyze only, don't modify
"""
import os
import sys
import re
import glob
import json
import shutil
import zipfile
import tempfile
import threading
import io
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    GAMES_DIR,
    SOUNDS_BGM_DIR,
    SOUNDS_SFX_DIR,
    SOUND_INDEX_PATH,
    OUTPUT_DIR,
    AUDIO_SUBFOLDER,
)
from catalog import load_index
from analyzer import analyze_game
from matcher import match_events
from injector import inject_audio

# Default parallel workers
DEFAULT_WORKERS = 5

# Thread-safe print lock
_print_lock = threading.Lock()


def tprint(*args, **kwargs):
    """Thread-safe print."""
    with _print_lock:
        print(*args, **kwargs)


def find_html_in_dir(directory: str) -> str | None:
    """Find the single .html file in a directory."""
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".html"):
                return os.path.join(root, f)
    return None


def resolve_sound_path(entry: dict) -> str | None:
    """Find the actual sound file on disk from a catalog entry."""
    for base in [SOUNDS_BGM_DIR, SOUNDS_SFX_DIR]:
        path = os.path.join(base, entry["relative_path"])
        if os.path.isfile(path):
            return path
        final_path = os.path.join(base, entry["sub_folder"], entry["final_name"])
        if os.path.isfile(final_path):
            return final_path
    return None


def check_output_valid(zip_path: str) -> dict:
    """
    Check if an output zip already has valid audio injection.
    Returns {"valid": bool, "reason": str, "sfx_calls": int}
    """
    result = {"valid": False, "reason": "", "sfx_calls": 0}

    if not os.path.isfile(zip_path):
        result["reason"] = "not found"
        return result

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            html_names = [n for n in zf.namelist() if n.endswith(".html")]
            if not html_names:
                result["reason"] = "no HTML in zip"
                return result

            html_content = zf.read(html_names[0]).decode("utf-8", errors="replace")

            has_am = "AudioManager" in html_content
            if not has_am:
                alt_names = ["GameAudio", "AudioMgr", "SoundManager"]
                has_am = any(name in html_content for name in alt_names)

            if not has_am:
                result["reason"] = "no audio manager"
                return result

            sfx_pattern = re.compile(
                r'\b(?:AudioManager|GameAudio|AudioMgr|SoundManager)\.playSFX\s*\('
            )
            sfx_calls = len(sfx_pattern.findall(html_content))
            result["sfx_calls"] = sfx_calls

            if sfx_calls == 0:
                result["reason"] = "audio manager present but 0 SFX calls"
                return result

            if "</html>" not in html_content:
                result["reason"] = "missing </html> (truncated)"
                return result

            if "</body>" not in html_content:
                result["reason"] = "missing </body> (truncated)"
                return result

            audio_files = [
                n for n in zf.namelist()
                if n.startswith(AUDIO_SUBFOLDER)
                and (n.endswith(".mp3") or n.endswith(".wav") or n.endswith(".ogg"))
            ]

            if not audio_files:
                result["reason"] = "no audio files in zip"
                return result

            result["valid"] = True
            result["reason"] = f"{sfx_calls} SFX, {len(audio_files)} audio files"
            return result

    except Exception as e:
        result["reason"] = f"error: {e}"
        return result


def validate_modified_html(html_content: str, original_lines: int) -> dict:
    """Validate the modified HTML before re-zipping."""
    result = {"ok": True, "warnings": []}

    if "AudioManager" not in html_content:
        result["ok"] = False
        result["warnings"].append("No AudioManager found")

    if "</html>" not in html_content:
        result["ok"] = False
        result["warnings"].append("Missing </html>")

    if "</body>" not in html_content:
        result["ok"] = False
        result["warnings"].append("Missing </body>")

    modified_lines = html_content.count("\n")
    if modified_lines < original_lines:
        result["ok"] = False
        result["warnings"].append(
            f"Modified ({modified_lines} lines) shorter than original ({original_lines} lines)"
        )

    sfx_count = html_content.count("AudioManager.playSFX")
    bgm_count = html_content.count("AudioManager.playBGM")
    if sfx_count == 0 and bgm_count == 0:
        result["warnings"].append("No playSFX or playBGM calls found")

    open_scripts = html_content.count("<script")
    close_scripts = html_content.count("</script>")
    if open_scripts != close_scripts:
        result["ok"] = False
        result["warnings"].append(
            f"Script tags unbalanced: {open_scripts} open, {close_scripts} close"
        )

    return result


def process_game(zip_path: str, index: list[dict], dry_run: bool = False) -> dict:
    """
    Process a single game zip. Returns a result dict.
    All output goes to a buffer, flushed at the end (thread-safe).
    """
    zip_name = os.path.basename(zip_path)
    buf = io.StringIO()

    def log(msg=""):
        buf.write(msg + "\n")

    result = {"zip": zip_name, "success": False, "error": None}

    try:
        log(f"\n{'='*60}")
        log(f"Processing: {zip_name}")
        log(f"{'='*60}")

        with tempfile.TemporaryDirectory(prefix="game_") as tmpdir:
            # ── Step 0: Unzip ──
            log("\n[Step 0] Unzipping...")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmpdir)

            html_path = find_html_in_dir(tmpdir)
            if not html_path:
                log("  ERROR: No .html file found in zip!")
                result["error"] = "no HTML"
                tprint(buf.getvalue(), end="")
                return result

            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            original_lines = html_content.count("\n")
            log(f"  Size: {len(html_content):,} bytes ({original_lines} lines)")

            # ── Step 1: Analyze ──
            log("\n[Step 1] Analyzing game code...")
            events = analyze_game(html_content)

            if not events:
                log("  No audio events identified. Skipping.")
                result["error"] = "no events"
                tprint(buf.getvalue(), end="")
                return result

            events_path = os.path.join(tmpdir, "_audio_events.json")
            with open(events_path, "w") as f:
                json.dump(events, f, indent=2)

            if dry_run:
                log(f"\n[DRY RUN] {len(events)} events found:")
                for e in events:
                    log(f"  {e['event_id']} ({e['type']}): {e['description'][:80]}")
                result["success"] = True
                tprint(buf.getvalue(), end="")
                return result

            # ── Step 2-3: Match ──
            log("\n[Step 2-3] Matching sounds...")
            mapping = match_events(events, index)

            matched_count = sum(1 for v in mapping.values() if v is not None)
            log(f"  Matched: {matched_count}/{len(events)} events")

            if matched_count == 0:
                log("  No matches found. Skipping.")
                result["error"] = "no matches"
                tprint(buf.getvalue(), end="")
                return result

            # ── Step 4: Inject ──
            log("\n[Step 4] Injecting audio code...")
            modified_html = inject_audio(html_content, events, mapping)

            # ── Step 4.5: Validate ──
            validation = validate_modified_html(modified_html, original_lines)
            if validation["warnings"]:
                for w in validation["warnings"]:
                    log(f"  WARNING: {w}")
            if not validation["ok"]:
                log("  VALIDATION FAILED — saving anyway")

            with open(html_path, "w", encoding="utf-8") as f:
                f.write(modified_html)
            log(f"  Modified HTML: {len(modified_html):,} bytes")

            # ── Step 5: Copy sound files ──
            log("\n[Step 5] Copying sound files...")
            audio_dir = os.path.join(os.path.dirname(html_path), AUDIO_SUBFOLDER)
            os.makedirs(audio_dir, exist_ok=True)

            copied = 0
            for eid, entry in mapping.items():
                if entry is None:
                    continue
                src_path = resolve_sound_path(entry)
                if src_path:
                    dst_path = os.path.join(audio_dir, entry["original_name"])
                    shutil.copy2(src_path, dst_path)
                    copied += 1

            log(f"  Copied {copied} audio files")

            # ── Step 6: Re-zip ──
            log("\n[Step 6] Re-zipping...")
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            output_path = os.path.join(OUTPUT_DIR, zip_name)

            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(tmpdir):
                    for file in files:
                        if file.startswith("_audio_"):
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, tmpdir)
                        zf.write(file_path, arcname)

            final_size = os.path.getsize(output_path)
            log(f"  Output: {output_path} ({final_size:,} bytes)")

        log(f"\n✓ Done: {zip_name}")
        result["success"] = True

    except Exception as e:
        import traceback
        log(f"\nERROR processing {zip_name}: {e}")
        log(traceback.format_exc())
        result["error"] = str(e)

    # Flush buffered output
    tprint(buf.getvalue(), end="")
    return result


def main():
    args = sys.argv[1:]

    # Parse flags
    dry_run = "--dry-run" in args
    force = "--force" in args
    rerun_file = None
    workers = DEFAULT_WORKERS

    clean_args = []
    i = 0
    while i < len(args):
        if args[i] == "--dry-run":
            i += 1
        elif args[i] == "--force":
            i += 1
        elif args[i] == "--rerun" and i + 1 < len(args):
            rerun_file = args[i + 1]
            i += 2
        elif args[i] == "-j" and i + 1 < len(args):
            workers = int(args[i + 1])
            i += 2
        else:
            clean_args.append(args[i])
            i += 1

    workers = max(1, min(workers, 20))

    # Load sound index
    if not os.path.isfile(SOUND_INDEX_PATH):
        print(f"ERROR: Sound index not found at {SOUND_INDEX_PATH}")
        print("Run build_index.py first.")
        sys.exit(1)

    print("Loading sound index...")
    index = load_index()
    print(f"  {len(index)} entries loaded "
          f"({sum(1 for e in index if e['source']=='bgm')} BGM, "
          f"{sum(1 for e in index if e['source']=='sfx')} SFX)")

    # Determine which zips to process
    if rerun_file:
        if not os.path.isfile(rerun_file):
            print(f"ERROR: Rerun list not found: {rerun_file}")
            sys.exit(1)
        with open(rerun_file) as f:
            names = [line.strip() for line in f if line.strip()]
        zip_files = []
        for name in names:
            path = os.path.join(GAMES_DIR, name)
            if os.path.isfile(path):
                zip_files.append(path)
            else:
                print(f"WARNING: {name} not found in {GAMES_DIR}/")
        print(f"\nLoaded {len(zip_files)} files from {rerun_file}")

    elif clean_args:
        zip_files = []
        for a in clean_args:
            if os.path.isfile(a):
                zip_files.append(a)
            else:
                path = os.path.join(GAMES_DIR, a)
                if os.path.isfile(path):
                    zip_files.append(path)
                else:
                    print(f"WARNING: File not found: {a}")
    else:
        zip_files = sorted(glob.glob(os.path.join(GAMES_DIR, "*.zip")))

    if not zip_files:
        print(f"No zip files found in {GAMES_DIR}/")
        sys.exit(1)

    # ── Skip already-done files ──
    if not force and not dry_run:
        to_process = []
        skipped = 0
        for zp in zip_files:
            zip_name = os.path.basename(zp)
            output_path = os.path.join(OUTPUT_DIR, zip_name)
            check = check_output_valid(output_path)
            if check["valid"]:
                print(f"  SKIP: {zip_name} ({check['reason']})")
                skipped += 1
            else:
                if check["reason"] != "not found":
                    print(f"  REDO: {zip_name} ({check['reason']})")
                to_process.append(zp)

        if skipped > 0:
            print(f"\nSkipped {skipped} already-done files (use --force to reprocess)")
        zip_files = to_process

    if not zip_files:
        print("Nothing to process. All files are done!")
        sys.exit(0)

    total = len(zip_files)
    print(f"\nWill process {total} game(s) with {workers} worker(s)")
    if dry_run:
        print("MODE: dry-run (analyze only)")
    if force:
        print("MODE: force (reprocessing all)")

    # ── Process games ──
    success = 0
    failed = 0

    if workers == 1:
        # Sequential mode (easier to debug)
        for zip_path in zip_files:
            result = process_game(zip_path, index, dry_run)
            if result["success"]:
                success += 1
            else:
                failed += 1
    else:
        # Parallel mode
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(process_game, zp, index, dry_run): zp
                for zp in zip_files
            }
            for future in as_completed(futures):
                result = future.result()
                if result["success"]:
                    success += 1
                else:
                    failed += 1

                # Progress
                done = success + failed
                tprint(f"\n[Progress: {done}/{total}] "
                       f"{success} OK, {failed} failed")

    print(f"\n{'='*60}")
    print(f"COMPLETE: {success} succeeded, {failed} failed out of {total} total")


if __name__ == "__main__":
    main()