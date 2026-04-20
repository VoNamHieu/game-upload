"""
Build sound_index.json from BGM and SFX CSV catalogs.
Run this once, or whenever the catalogs change.

Usage:
    python build_index.py
    python build_index.py --bgm path/to/bgm.csv --sfx path/to/sfx.csv
"""
import os
import sys
import json
import pandas as pd
from config import SOUND_INDEX_PATH

# Default CSV paths (adjust as needed)
DEFAULT_BGM_CSV = "./catalogs/bgm.csv"
DEFAULT_SFX_CSV = "./catalogs/sfx.csv"


def parse_tags(raw: str) -> dict[str, list[str]]:
    """Parse 'cat:combat, type:loop, mood:tense' → {'cat': ['combat'], 'type': ['loop'], 'mood': ['tense']}"""
    if pd.isna(raw):
        return {}
    result = {}
    for t in raw.split(","):
        t = t.strip()
        if ":" in t:
            prefix, value = t.split(":", 1)
            result.setdefault(prefix, []).append(value)
    return result


def build_index(bgm_csv: str, sfx_csv: str) -> list[dict]:
    entries = []

    for csv_path, source, tag_col in [
        (bgm_csv, "bgm", "tags"),
        (sfx_csv, "sfx", "tag"),
    ]:
        if not os.path.isfile(csv_path):
            print(f"  WARNING: {csv_path} not found, skipping.")
            continue

        df = pd.read_csv(csv_path)
        df = df.loc[:, ~df.columns.str.startswith("Unnamed")]

        # Normalize tag column name
        if tag_col in df.columns:
            df = df.rename(columns={tag_col: "tag_raw"})
        elif "tag_raw" not in df.columns:
            print(f"  WARNING: No tag column found in {csv_path}")
            df["tag_raw"] = ""

        for _, row in df.iterrows():
            entries.append(
                {
                    "file_id": row["file_id"],
                    "display_name": row["display_name"],
                    "desc": row["desc"],
                    "tags": parse_tags(row["tag_raw"]),
                    "tag_raw": row["tag_raw"] if pd.notna(row["tag_raw"]) else "",
                    "duration_sec": round(row["duration_sec"], 3),
                    "relative_path": row["relative_path"],
                    "sub_folder": row["sub_folder"],
                    "source": source,
                    "original_name": row["original_name"],
                    "final_name": row["final_name"],
                }
            )
        print(f"  Loaded {len(df)} entries from {csv_path} ({source})")

    return entries


def main():
    bgm_csv = DEFAULT_BGM_CSV
    sfx_csv = DEFAULT_SFX_CSV

    # Simple arg parsing
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--bgm" and i + 1 < len(args):
            bgm_csv = args[i + 1]
            i += 2
        elif args[i] == "--sfx" and i + 1 < len(args):
            sfx_csv = args[i + 1]
            i += 2
        else:
            i += 1

    print("Building sound index...")
    entries = build_index(bgm_csv, sfx_csv)

    if not entries:
        print("ERROR: No entries loaded!")
        sys.exit(1)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(SOUND_INDEX_PATH), exist_ok=True)

    with open(SOUND_INDEX_PATH, "w") as f:
        json.dump(entries, f, indent=2)

    bgm_count = sum(1 for e in entries if e["source"] == "bgm")
    sfx_count = sum(1 for e in entries if e["source"] == "sfx")
    size_kb = os.path.getsize(SOUND_INDEX_PATH) / 1024

    print(f"\n✓ Saved {len(entries)} entries to {SOUND_INDEX_PATH}")
    print(f"  BGM: {bgm_count} | SFX: {sfx_count} | Size: {size_kb:.0f}KB")


if __name__ == "__main__":
    main()
