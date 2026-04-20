"""
Wrapper for Anthropic API calls with retry and JSON parsing.
"""
import json
import time
import httpx
from config import ANTHROPIC_API_KEY, MODEL, MAX_TOKENS


def call_ai(system_prompt: str, user_prompt: str, retries: int = 3) -> str:
    """Call Claude API and return text response."""
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    for attempt in range(retries):
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                text = "".join(
                    block["text"] for block in data["content"] if block["type"] == "text"
                )
                return text
        except Exception as e:
            print(f"  [AI] Attempt {attempt+1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def call_ai_json(system_prompt: str, user_prompt: str, retries: int = 3) -> dict | list:
    """Call Claude API and parse response as JSON."""
    text = call_ai(system_prompt, user_prompt, retries)

    # Strip markdown fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.index("\n")
        cleaned = cleaned[first_newline + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"  [AI] JSON parse failed, retrying... Error: {e}")
        print(f"  [AI] Raw response (first 500 chars): {text[:500]}")
        if retries > 1:
            return call_ai_json(system_prompt, user_prompt, retries - 1)
        raise
