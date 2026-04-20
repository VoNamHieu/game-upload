"""
Sound catalog: load index and filter by tags/keywords.
"""
import json
from config import SOUND_INDEX_PATH, SHORTLIST_SIZE


def load_index() -> list[dict]:
    """Load sound_index.json."""
    with open(SOUND_INDEX_PATH, "r") as f:
        return json.load(f)


def filter_by_tags(
    index: list[dict],
    desired_tags: dict[str, list[str]],
    source_pref: str | None = None,
    max_results: int = SHORTLIST_SIZE,
) -> list[dict]:
    """
    Filter index entries by structured tags.

    desired_tags format: {"mood": ["tense", "heavy"], "use": ["bg"], "type": ["loop"]}
    source_pref: "bgm" or "sfx" — prioritize but don't exclude
    """
    scored = []
    for entry in index:
        score = 0
        entry_tags = entry.get("tags", {})

        # Score based on tag overlap
        for prefix, values in desired_tags.items():
            entry_values = entry_tags.get(prefix, [])
            for v in values:
                if v in entry_values:
                    score += 2
                # Partial match (e.g. "combat" matches "cat:combat")
                elif any(v in ev for ev in entry_values):
                    score += 1

        # Source preference bonus
        if source_pref and entry["source"] == source_pref:
            score += 1

        if score > 0:
            scored.append((score, entry))

    # Sort by score descending
    scored.sort(key=lambda x: -x[0])
    return [entry for _, entry in scored[:max_results]]


def filter_by_keywords(
    index: list[dict],
    keywords: list[str],
    source_pref: str | None = None,
    max_results: int = SHORTLIST_SIZE,
) -> list[dict]:
    """
    Fallback keyword search in display_name + desc + tag_raw.
    """
    keywords_lower = [k.lower() for k in keywords]
    scored = []
    for entry in index:
        searchable = (
            f"{entry['display_name']} {entry['desc']} {entry['tag_raw']}"
        ).lower()
        score = sum(2 if kw in searchable else 0 for kw in keywords_lower)
        if source_pref and entry["source"] == source_pref:
            score += 1
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: -x[0])
    return [entry for _, entry in scored[:max_results]]


def compact_for_ai(entries: list[dict]) -> list[dict]:
    """Reduce entry size for sending to AI (save tokens)."""
    return [
        {
            "id": e["file_id"][:8],  # short id for reference
            "name": e["display_name"],
            "desc": e["desc"],
            "tags": e["tag_raw"],
            "dur": e["duration_sec"],
            "src": e["source"],
        }
        for e in entries
    ]


def get_entry_by_short_id(index: list[dict], short_id: str) -> dict | None:
    """Find full entry by short file_id (first 8 chars)."""
    for entry in index:
        if entry["file_id"].startswith(short_id):
            return entry
    return None
