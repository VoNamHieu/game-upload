"""
Step 1: Analyze game code to identify where audio is needed.
"""
from ai_client import call_ai_json

SYSTEM_PROMPT = """You are a game audio designer. You analyze HTML5 game source code and identify every point where sound effects (SFX) or background music (BGM) should be added.

For each audio event you identify, output a JSON object with:
- "event_id": short unique id like "bgm_menu", "sfx_cut", "sfx_win" etc.
- "type": "bgm" or "sfx"
- "description": what the sound should feel like, 1-2 sentences
- "suggested_tags": object with tag prefixes as keys, e.g. {"mood": ["tense"], "cat": ["combat"], "type": ["loop"], "use": ["bg"]}
- "keywords": array of search keywords for fallback matching
- "code_context": the relevant code snippet (max 3 lines) where this sound should play
- "injection_hint": brief description of where/how to inject the audio code

Think about:
- Background music for different game states (menu, gameplay, win, lose)
- SFX for player actions (click, swipe, cut, drag)
- SFX for game events (score change, level complete, win, fail/lose)
- SFX for visual effects (particles, fragments, confetti)
- UI sounds (button hover, transition)

Respond with ONLY a JSON array. No markdown, no explanation."""


def analyze_game(html_content: str) -> list[dict]:
    """Analyze game HTML and return list of audio events."""
    user_prompt = f"""Analyze this HTML5 game and identify all points where SFX or BGM should be added.

GAME CODE:
```html
{html_content}
```

Return a JSON array of audio events."""

    print("  [Analyzer] Sending game code to AI...")
    events = call_ai_json(SYSTEM_PROMPT, user_prompt)
    print(f"  [Analyzer] Found {len(events)} audio events")
    for e in events:
        print(f"    - {e['event_id']} ({e['type']}): {e['description'][:60]}...")
    return events
