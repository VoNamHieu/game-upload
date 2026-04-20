#!/usr/bin/env python3
"""
audio_merge.py — Merge truncated audio-injected HTML with original full HTML.

Usage:
    python3 audio_merge.py --games games/ --output output/ --merged merged/ --debug
    python3 audio_merge.py --original game.html --truncated truncated.html -o merged.html
"""

import sys
import os
import re
import difflib
import argparse
import zipfile
import tempfile
import shutil
import json
import csv
from pathlib import Path
from datetime import datetime


# ─────────────────────── AUDIO DETECTION ───────────────────────

# All known audio manager names the injector might use
AUDIO_MANAGER_NAMES = [
    'AudioManager', 'AudioMgr', 'GameAudio', 'SoundManager',
    'SFXManager', 'SoundEngine', 'AudioEngine', 'Audio',
]

# Regex to find any playSFX call: <Name>.playSFX(...)
RE_PLAY_SFX = re.compile(
    r'\b(' + '|'.join(AUDIO_MANAGER_NAMES) + r')\.playSFX\s*\(',
    re.IGNORECASE
)

# Regex for standalone playSFX('...') calls (no object prefix)
RE_PLAY_SFX_STANDALONE = re.compile(r'(?<!\w)playSFX\s*\(')

# Regex to find audio manager definition: var <Name> = (function(){ or function <Name>
RE_AUDIO_DEF = re.compile(
    r'(?:var|let|const)\s+(' + '|'.join(AUDIO_MANAGER_NAMES) + r')\s*=',
    re.IGNORECASE
)

# Broader audio indicators
AUDIO_INDICATORS = [
    'createBufferSource', 'decodeAudioData', 'AudioContext',
    'webkitAudioContext', 'sfx_', 'playSFX', 'playBGM', 'stopBGM',
]


def detect_audio_system(text):
    """Detect which audio system name is used in the code."""
    info = {
        'manager_name': None,
        'sfx_calls': 0,
        'sfx_call_details': [],
        'has_audio_code': False,
        'indicators_found': [],
    }

    # Find the audio manager name
    m = RE_AUDIO_DEF.search(text)
    if m:
        info['manager_name'] = m.group(1)

    # Count SFX calls (with object prefix)
    for match in RE_PLAY_SFX.finditer(text):
        info['sfx_calls'] += 1
        if not info['manager_name']:
            info['manager_name'] = match.group(1)

    # Also count standalone playSFX calls
    standalone = len(RE_PLAY_SFX_STANDALONE.findall(text)) - info['sfx_calls']
    if standalone > 0:
        info['sfx_calls'] += standalone

    # Check broader indicators
    for ind in AUDIO_INDICATORS:
        if ind in text:
            info['indicators_found'].append(ind)

    info['has_audio_code'] = bool(info['manager_name'] or info['indicators_found'])

    return info


def find_audio_block(lines, text):
    """Find the audio manager block boundaries (any naming convention)."""
    # Try standard markers first
    start = end = -1
    for i, line in enumerate(lines):
        if '// ==================== AUDIO' in line and 'MANAGER' in line:
            if 'END' not in line:
                start = i
            else:
                end = i
    if start >= 0 and end > start:
        return start, end + 1, 'markers'

    # Try to find "var <AudioName> = (function(){" ... "})();"
    for name in AUDIO_MANAGER_NAMES:
        pattern_start = re.compile(
            r'(?:var|let|const)\s+' + re.escape(name) + r'\s*=\s*\(?function',
            re.IGNORECASE
        )
        for i, line in enumerate(lines):
            if pattern_start.search(line):
                # Find the closing "})();" or "return {...}" block
                brace_depth = 0
                found_start = False
                for j in range(i, min(i + 300, len(lines))):
                    brace_depth += lines[j].count('{') - lines[j].count('}')
                    if brace_depth > 0:
                        found_start = True
                    if found_start and brace_depth <= 0:
                        return i, j + 1, name
                # If we didn't find closing, block is incomplete
                return i, -1, name + ' (incomplete)'

    return -1, -1, None


# ─────────────────────── CORE MERGE ───────────────────────

def merge_audio(orig_lines, trunc_lines, verbose=False):
    sm = difflib.SequenceMatcher(None, orig_lines, trunc_lines, autojunk=False)
    opcodes = sm.get_opcodes()

    truncation_idx = None
    for idx, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == 'replace' and (i2 - i1) > 50 and (j2 - j1) <= 5:
            truncation_idx = idx
            break

    stats = {
        'inserts': 0, 'insert_lines': 0, 'replaces': 0,
        'truncation_recovered': 0,
    }

    result = []
    for idx, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if idx == truncation_idx:
            result.extend(orig_lines[i1:i2])
            stats['truncation_recovered'] = i2 - i1
            if verbose:
                print(f"    [TRUNCATION] Kept original L{i1+1}-{i2} ({i2-i1} lines)")
        elif tag == 'equal':
            result.extend(orig_lines[i1:i2])
        elif tag == 'insert':
            added = trunc_lines[j1:j2]
            result.extend(added)
            stats['inserts'] += 1
            stats['insert_lines'] += len(added)
            if verbose:
                print(f"    [INSERT] {len(added)} lines after orig L{i1}: {added[0].strip()[:80]}")
        elif tag == 'replace':
            result.extend(trunc_lines[j1:j2])
            stats['replaces'] += 1
            if verbose:
                print(f"    [REPLACE] orig L{i1+1}-{i2} -> trunc L{j1+1}-{j2}")
        elif tag == 'delete':
            result.extend(orig_lines[i1:i2])

    merged = ''.join(result)
    audio_info = detect_audio_system(merged)
    stats['sfx_calls'] = audio_info['sfx_calls']
    stats['manager_name'] = audio_info['manager_name']
    stats['has_audio_code'] = audio_info['has_audio_code']

    return merged, stats


def validate(merged, orig_text):
    checks = []
    checks.append(('</html> present', '</html>' in merged))
    checks.append(('</body> present', '</body>' in merged))

    audio_info = detect_audio_system(merged)
    has_audio = audio_info['has_audio_code']
    mgr = audio_info['manager_name'] or 'none'
    checks.append((f'Audio system present ({mgr})', has_audio))

    merged_lines = merged.count('\n')
    orig_lines = orig_text.count('\n')
    checks.append((f'Lines {merged_lines} >= orig {orig_lines}', merged_lines >= orig_lines))

    sfx = audio_info['sfx_calls']
    checks.append((f'SFX calls: {sfx}', sfx > 0))

    opens = merged.count('<script')
    closes = merged.count('</script>')
    checks.append((f'Scripts balanced: {opens}/{closes}', opens == closes))

    return checks


# ─────────────────────── DEBUG / DIAGNOSTICS ───────────────────────

def diagnose_truncated(orig_text, trunc_text, zip_name):
    orig_lines = orig_text.splitlines(True)
    trunc_lines = trunc_text.splitlines(True)

    diag = {
        'zip': zip_name,
        'orig_lines': len(orig_lines),
        'orig_bytes': len(orig_text),
        'trunc_lines': len(trunc_lines),
        'trunc_bytes': len(trunc_text),
        'trunc_ratio': round(len(trunc_text) / max(len(orig_text), 1) * 100, 1),
    }

    # Audio detection (multi-name)
    audio_info = detect_audio_system(trunc_text)
    diag['manager_name'] = audio_info['manager_name']
    diag['has_audio_code'] = audio_info['has_audio_code']
    diag['indicators_found'] = audio_info['indicators_found']
    diag['sfx_calls'] = audio_info['sfx_calls']

    # Audio block detection
    blk_start, blk_end, blk_name = find_audio_block(trunc_lines, trunc_text)
    diag['am_block_start'] = blk_start + 1 if blk_start >= 0 else None
    diag['am_block_end'] = blk_end if blk_end >= 0 else None
    diag['am_block_name'] = blk_name
    diag['am_block_complete'] = blk_start >= 0 and blk_end > blk_start

    # Closing tags
    diag['has_close_html'] = '</html>' in trunc_text
    diag['has_close_body'] = '</body>' in trunc_text
    diag['script_opens'] = trunc_text.count('<script')
    diag['script_closes'] = trunc_text.count('</script>')

    # Last lines
    diag['last_5_lines'] = [l.rstrip() for l in trunc_lines[-5:]]

    # Coverage
    sm = difflib.SequenceMatcher(None, orig_lines, trunc_lines, autojunk=False)
    last_orig = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ('equal', 'replace', 'delete'):
            last_orig = max(last_orig, i2)
    diag['orig_coverage'] = last_orig
    diag['orig_coverage_pct'] = round(last_orig / max(len(orig_lines), 1) * 100, 1)

    # Token estimate
    diag['est_output_tokens'] = round(len(trunc_text) / 3.5)

    # Category
    if not diag['has_close_html'] and diag['trunc_lines'] < diag['orig_lines'] * 0.5:
        diag['category'] = 'SEVERE_TRUNCATION'
        diag['diagnosis'] = (
            f"Severely truncated ({diag['trunc_ratio']}%). "
            f"Lost {diag['orig_lines'] - diag['trunc_lines']} lines."
        )
    elif diag['has_audio_code'] and diag['am_block_complete'] and diag['sfx_calls'] == 0:
        diag['category'] = 'AM_BLOCK_OK_NO_SFX'
        diag['diagnosis'] = (
            f"Audio block complete ({diag['am_block_name']}) "
            f"but no inline SFX calls added yet."
        )
    elif diag['has_audio_code'] and not diag['am_block_complete'] and blk_start >= 0:
        diag['category'] = 'AM_BLOCK_INCOMPLETE'
        diag['diagnosis'] = (
            f"Audio block ({diag['am_block_name']}) started L{diag['am_block_start']} "
            f"but truncated before closing."
        )
    elif not diag['has_audio_code']:
        diag['category'] = 'NO_AUDIO_INJECTED'
        diag['diagnosis'] = "No audio code detected at all."
    elif diag['sfx_calls'] > 0:
        diag['category'] = 'PARTIAL_OK'
        diag['diagnosis'] = (
            f"Audio present ({diag['manager_name']}) with {diag['sfx_calls']} SFX calls."
        )
    else:
        diag['category'] = 'UNKNOWN'
        diag['diagnosis'] = "Could not determine failure cause."

    return diag


def print_diagnosis(diag, detail=True):
    icons = {
        'SEVERE_TRUNCATION': '💀', 'NO_AUDIO_INJECTED': '🔇',
        'DIFFERENT_AUDIO_PATTERN': '🔀', 'AM_BLOCK_INCOMPLETE': '✂️',
        'AM_BLOCK_OK_NO_SFX': '📦', 'PARTIAL_OK': '⚠️', 'UNKNOWN': '❓',
    }
    cat = diag['category']
    icon = icons.get(cat, '❓')
    print(f"  {icon} [{cat}] {diag['diagnosis']}")

    if detail:
        print(f"     Original: {diag['orig_lines']} lines / {diag['orig_bytes']} bytes")
        print(f"     Truncated: {diag['trunc_lines']} lines / {diag['trunc_bytes']} bytes ({diag['trunc_ratio']}%)")
        print(f"     Est. output tokens: ~{diag['est_output_tokens']}")
        print(f"     Original coverage: L1-{diag['orig_coverage']} ({diag['orig_coverage_pct']}%)")

        if diag.get('am_block_start'):
            status = "complete" if diag['am_block_complete'] else "INCOMPLETE"
            name = diag.get('am_block_name', '?')
            print(f"     Audio block: {name} L{diag['am_block_start']}-{diag.get('am_block_end', '???')} ({status})")
        elif diag.get('manager_name'):
            print(f"     Audio manager: {diag['manager_name']} (block not found)")
        else:
            print(f"     Audio block: NOT FOUND")

        if diag.get('indicators_found'):
            print(f"     Audio indicators: {diag['indicators_found']}")

        print(f"     SFX calls: {diag['sfx_calls']}")
        print(f"     Last lines:")
        for line in diag['last_5_lines']:
            print(f"       | {line[:120]}")


# ─────────────────────── ZIP HELPERS ───────────────────────

def extract_html_from_zip(zip_path, tmp_dir):
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(tmp_dir)
    html_path = os.path.join(tmp_dir, 'index.html')
    if os.path.exists(html_path):
        return html_path
    for root, dirs, files in os.walk(tmp_dir):
        for f in files:
            if f.endswith('.html'):
                return os.path.join(root, f)
    return None


def repack_zip(truncated_zip, merged_html, output_zip):
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(truncated_zip, 'r') as zf:
            zf.extractall(tmp)
        html_path = os.path.join(tmp, 'index.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(merged_html)
        with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(tmp):
                for file in files:
                    fp = os.path.join(root, file)
                    zf.write(fp, os.path.relpath(fp, tmp))


# ─────────────────────── BATCH ───────────────────────

def batch_process(games_dir, output_dir, merged_dir, verbose=False, debug=False):
    os.makedirs(merged_dir, exist_ok=True)

    truncated_zips = sorted([f for f in os.listdir(output_dir) if f.endswith('.zip')])
    total = len(truncated_zips)

    counts = {'ok': 0, 'not_truncated': 0, 'failed': 0, 'skipped': 0}
    diagnostics = []
    failures_by_category = {}

    print(f"Found {total} zips in {output_dir}/")
    print(f"Originals in {games_dir}/")
    print(f"Output to {merged_dir}/")
    if debug:
        print("DEBUG MODE enabled")
    print("=" * 60)

    for i, zip_name in enumerate(truncated_zips, 1):
        original_zip = os.path.join(games_dir, zip_name)
        truncated_zip = os.path.join(output_dir, zip_name)
        merged_zip = os.path.join(merged_dir, zip_name)

        print(f"\n[{i}/{total}] {zip_name}")

        if not os.path.exists(original_zip):
            print(f"  SKIP: original not found")
            counts['skipped'] += 1
            continue

        try:
            with tempfile.TemporaryDirectory() as tmp_orig, \
                 tempfile.TemporaryDirectory() as tmp_trunc:

                orig_html = extract_html_from_zip(original_zip, tmp_orig)
                trunc_html = extract_html_from_zip(truncated_zip, tmp_trunc)

                if not orig_html or not trunc_html:
                    print(f"  SKIP: no index.html")
                    counts['skipped'] += 1
                    continue

                with open(orig_html, 'r', encoding='utf-8') as f:
                    orig_text = f.read()
                    orig_lines = orig_text.splitlines(True)
                with open(trunc_html, 'r', encoding='utf-8') as f:
                    trunc_text = f.read()
                    trunc_lines = trunc_text.splitlines(True)

                if len(trunc_lines) >= len(orig_lines):
                    shutil.copy2(truncated_zip, merged_zip)
                    # Validate even non-truncated
                    audio = detect_audio_system(trunc_text)
                    mgr = audio['manager_name'] or '?'
                    sfx = audio['sfx_calls']
                    print(f"  OK (not truncated, {mgr}: {sfx} SFX)")
                    counts['not_truncated'] += 1
                    counts['ok'] += 1
                    continue

                merged_text, stats = merge_audio(orig_lines, trunc_lines, verbose=verbose)
                checks = validate(merged_text, orig_text)
                all_ok = all(ok for _, ok in checks)

                if not all_ok:
                    for desc, ok in checks:
                        if not ok:
                            print(f"    [FAIL] {desc}")

                repack_zip(truncated_zip, merged_text, merged_zip)

                merged_lc = merged_text.count('\n')
                sfx = stats['sfx_calls']
                mgr = stats.get('manager_name', '?')
                recovered = stats['truncation_recovered']

                if all_ok:
                    print(f"  OK: {len(orig_lines)} + {mgr} -> {merged_lc} lines, "
                          f"{sfx} SFX, {recovered} recovered")
                    counts['ok'] += 1
                else:
                    diag = diagnose_truncated(orig_text, trunc_text, zip_name)
                    diag['merged_lines'] = merged_lc
                    diag['merge_sfx'] = sfx
                    diag['merge_recovered'] = recovered
                    diagnostics.append(diag)

                    cat = diag['category']
                    failures_by_category[cat] = failures_by_category.get(cat, 0) + 1

                    if debug:
                        print_diagnosis(diag, detail=True)
                    else:
                        print_diagnosis(diag, detail=False)

                    counts['failed'] += 1

        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            if debug:
                traceback.print_exc()
            counts['failed'] += 1

    # Summary
    print("\n" + "=" * 60)
    print(f"RESULTS: {counts['ok']} OK / {counts['failed']} failed / {counts['skipped']} skipped")
    print(f"  ({counts['not_truncated']} not truncated)")

    if failures_by_category:
        print(f"\nFAILURES BY CATEGORY:")
        icons = {
            'SEVERE_TRUNCATION': '💀', 'NO_AUDIO_INJECTED': '🔇',
            'AM_BLOCK_INCOMPLETE': '✂️', 'AM_BLOCK_OK_NO_SFX': '📦',
            'PARTIAL_OK': '⚠️',
        }
        for cat, count in sorted(failures_by_category.items(), key=lambda x: -x[1]):
            print(f"  {icons.get(cat, '❓')} {cat}: {count}")

    if debug and diagnostics:
        report_path = os.path.join(merged_dir, '_debug_report.json')
        csv_path = os.path.join(merged_dir, '_debug_report.csv')
        rerun_path = os.path.join(merged_dir, '_rerun_list.txt')

        with open(report_path, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'total': total, 'ok': counts['ok'],
                'failed': counts['failed'], 'skipped': counts['skipped'],
                'failures_by_category': failures_by_category,
                'diagnostics': diagnostics,
            }, f, indent=2, default=str)

        with open(csv_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['zip', 'category', 'orig_lines', 'trunc_lines', 'trunc_ratio%',
                         'est_tokens', 'audio_name', 'sfx_calls', 'orig_coverage%',
                         'last_line', 'diagnosis'])
            for d in diagnostics:
                last = d['last_5_lines'][-1] if d['last_5_lines'] else ''
                w.writerow([
                    d['zip'], d['category'], d['orig_lines'], d['trunc_lines'],
                    d['trunc_ratio'], d['est_output_tokens'],
                    d.get('manager_name') or d.get('am_block_name') or 'none',
                    d['sfx_calls'], d['orig_coverage_pct'],
                    last[:120], d['diagnosis']
                ])

        rerun_zips = [d['zip'] for d in diagnostics]
        with open(rerun_path, 'w') as f:
            for z in rerun_zips:
                f.write(z + '\n')

        print(f"\nDebug report: {report_path}")
        print(f"CSV report:   {csv_path}")
        print(f"Rerun list:   {rerun_path} ({len(rerun_zips)} files)")

    print(f"\nOutput: {merged_dir}/")


# ─────────────────────── SINGLE FILE ───────────────────────

def process_single(original_path, truncated_path, output_path=None, verbose=True, debug=False):
    with open(original_path, 'r', encoding='utf-8') as f:
        orig_text = f.read()
        orig_lines = orig_text.splitlines(True)
    with open(truncated_path, 'r', encoding='utf-8') as f:
        trunc_text = f.read()
        trunc_lines = trunc_text.splitlines(True)

    if len(trunc_lines) >= len(orig_lines):
        if verbose:
            print(f"  Not truncated ({len(trunc_lines)} >= {len(orig_lines)})")
        return trunc_text, True

    merged, stats = merge_audio(orig_lines, trunc_lines, verbose=verbose)
    checks = validate(merged, orig_text)
    all_ok = all(ok for _, ok in checks)

    if verbose:
        for desc, ok in checks:
            print(f"    [{'OK' if ok else 'FAIL'}] {desc}")

    if not all_ok and debug:
        diag = diagnose_truncated(orig_text, trunc_text, os.path.basename(truncated_path))
        print_diagnosis(diag, detail=True)

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(merged)

    return merged, all_ok


def main():
    parser = argparse.ArgumentParser(
        description='Merge truncated audio-injected HTML with original full HTML')

    parser.add_argument('--original', help='Single original HTML file')
    parser.add_argument('--truncated', help='Single truncated HTML file')
    parser.add_argument('-o', '--out', help='Output file (single mode)')

    parser.add_argument('--games', help='Folder with original game zips')
    parser.add_argument('--output', help='Folder with truncated output zips')
    parser.add_argument('--merged', help='Folder for merged output zips')

    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('--debug', action='store_true',
                        help='Enable detailed diagnostics + write report files')

    args = parser.parse_args()

    if args.games and args.output:
        batch_process(args.games, args.output, args.merged or 'merged',
                      verbose=args.verbose, debug=args.debug)
        return

    if args.original and args.truncated:
        out = args.out or args.original.replace('.html', '_merged.html')
        print(f"Original:  {args.original}")
        print(f"Truncated: {args.truncated}")
        merged, ok = process_single(args.original, args.truncated, out,
                                    verbose=True, debug=args.debug)
        print(f"\nOutput: {out} ({len(merged)} bytes)")
        if not ok:
            print("WARNING: Some checks failed!")
            sys.exit(1)
        print("All checks passed!")
        return

    parser.print_help()


if __name__ == '__main__':
    main()