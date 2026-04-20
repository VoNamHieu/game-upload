#!/usr/bin/env python3
"""
Scan a folder of game ZIPs and generate/update games.csv.

Columns: User ID, Game UUID, Source
  - Game UUID = zip filename stem (tên gốc, không có .zip)
  - Source    = full zip filename (<stem>.zip)
  - User ID   = để trống, paste tay sau khi chạy

Append-only: nếu games.csv đã có, chỉ thêm dòng mới cho zip chưa có trong CSV
(giữ nguyên User ID đã paste).

Usage:
    python3 prepare_csv.py                    # scan ./games
    python3 prepare_csv.py --zips ./other     # scan folder khác
    python3 prepare_csv.py --csv games.csv
"""
import argparse
import csv
import sys
from pathlib import Path


COLUMNS = ["User ID", "Game UUID", "Source"]


def load_existing(csv_path: Path) -> tuple[list[list[str]], set[str]]:
    """Return (rows, set of existing Game UUIDs)."""
    if not csv_path.exists():
        return [], set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        rows = [r for r in reader if r]
    uuids = {r[1].strip() for r in rows if len(r) >= 2}
    return rows, uuids


def scan_zips(zips_dir: Path) -> list[tuple[str, str]]:
    """Return list of (stem, filename) sorted by filename."""
    if not zips_dir.is_dir():
        print(f"ERROR: folder not found: {zips_dir}")
        sys.exit(1)
    items = []
    for f in sorted(zips_dir.iterdir()):
        if f.suffix.lower() == ".zip":
            items.append((f.stem, f.name))
    return items


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zips", default="./games", help="folder chứa .zip (default: ./games)")
    ap.add_argument("--csv", default="games.csv", help="CSV path (default: games.csv)")
    args = ap.parse_args()

    zips_dir = Path(args.zips)
    csv_path = Path(args.csv)

    existing_rows, existing_uuids = load_existing(csv_path)
    zips = scan_zips(zips_dir)

    new_rows = []
    for stem, filename in zips:
        if stem in existing_uuids:
            continue
        new_rows.append(["", stem, filename])

    all_rows = existing_rows + new_rows

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(all_rows)

    print(f"  Scanned: {len(zips)} zip(s) in {zips_dir}")
    print(f"  CSV:     {csv_path}")
    print(f"  Existing rows: {len(existing_rows)}")
    print(f"  New rows:      {len(new_rows)}")
    if new_rows:
        print(f"\n  → Mở {csv_path} và paste User ID vào cột 1 cho {len(new_rows)} dòng mới.")


if __name__ == "__main__":
    main()
