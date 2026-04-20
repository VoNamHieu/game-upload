"""
Step 2-3: Filter catalog by tags, then AI picks the best match for each event.
"""
import json
from ai_client import call_ai_json
from catalog import (
    load_index,
    filter_by_tags,
    filter_by_keywords,
    compact_for_ai,
    get_entry_by_short_id,
)
from config import EVENTS_PER_BATCH

SYSTEM_PROMPT = """You are a game audio designer matching sound files to game events.

For each game event, you receive a shortlist of candidate sound files. Pick the BEST match.

Rules:
- For BGM: prefer loops (type:loop), appropriate mood, reasonable duration (>10s for gameplay, shorter for jingles)
- For SFX: prefer short sounds (type:oneshot or short duration), matching the action feel
- If NO candidate is a good fit, set "match_id" to null

Respond with ONLY a JSON array where each item has:
- "event_id": the event id from input
- "match_id": the "id" field of the best candidate (first 8 chars of file_id), or null
- "reason": 1 sentence explaining why this match works

No markdown, no explanation outside the JSON."""


def build_shortlists(events: list[dict], index: list[dict]) -> dict[str, list[dict]]:
    """For each event, filter the catalog to a shortlist of candidates."""
    shortlists = {}
    for event in events:
        source_pref = event["type"]  # "bgm" or "sfx"

        # Try tag-based filter first
        suggested_tags = event.get("suggested_tags", {})
        candidates = filter_by_tags(index, suggested_tags, source_pref)

        # If too few results, fallback to keyword search
        if len(candidates) < 5:
            keywords = event.get("keywords", [])
            if keywords:
                kw_results = filter_by_keywords(index, keywords, source_pref)
                # Merge, deduplicate
                seen_ids = {c["file_id"] for c in candidates}
                for r in kw_results:
                    if r["file_id"] not in seen_ids:
                        candidates.append(r)
                        seen_ids.add(r["file_id"])

        shortlists[event["event_id"]] = candidates
        print(f"    {event['event_id']}: {len(candidates)} candidates")

    return shortlists


def match_events(
    events: list[dict], index: list[dict]
) -> dict[str, dict | None]:
    """
    Main matching pipeline:
    1. Build shortlists (Python, no AI)
    2. AI picks best match per event (batched)

    Returns: {event_id: full_entry_or_None}
    """
    print("  [Matcher] Building shortlists...")
    shortlists = build_shortlists(events, index)

    # Batch events for AI calls
    mapping = {}
    batches = []
    current_batch = []
    for event in events:
        current_batch.append(event)
        if len(current_batch) >= EVENTS_PER_BATCH:
            batches.append(current_batch)
            current_batch = []
    if current_batch:
        batches.append(current_batch)

    print(f"  [Matcher] Matching in {len(batches)} batches...")
    for i, batch in enumerate(batches):
        print(f"  [Matcher] Batch {i+1}/{len(batches)}...")

        # Build prompt for this batch
        batch_data = []
        for event in batch:
            candidates = shortlists.get(event["event_id"], [])
            batch_data.append(
                {
                    "event_id": event["event_id"],
                    "type": event["type"],
                    "description": event["description"],
                    "candidates": compact_for_ai(candidates),
                }
            )

        user_prompt = (
            "Match each game event to the best sound file from its candidates.\n\n"
            + json.dumps(batch_data, indent=2)
        )

        results = call_ai_json(SYSTEM_PROMPT, user_prompt)

        for r in results:
            eid = r["event_id"]
            mid = r.get("match_id")
            if mid:
                full_entry = get_entry_by_short_id(index, mid)
                if full_entry:
                    mapping[eid] = full_entry
                    print(f"    ✓ {eid} → {full_entry['display_name']} ({r['reason']})")
                else:
                    print(f"    ✗ {eid} → match_id '{mid}' not found in index")
                    mapping[eid] = None
            else:
                print(f"    ✗ {eid} → no suitable match ({r.get('reason', 'N/A')})")
                mapping[eid] = None

    return mapping
