"""
Step 4: AI injects audio code into the game HTML (patch mode).

Instead of asking AI to rewrite the entire file (causes truncation),
AI returns small JSON patches → Python applies them to the original.

Output tokens: ~2000-4000 (vs 10000+ for full rewrite).
Never truncates regardless of game size.
"""
import json
import re
from ai_client import call_ai_json
from config import AUDIO_SUBFOLDER


# ─────────────────────── AUDIO MANAGER TEMPLATE ───────────────────────
# Hardcoded template ensures consistent naming across all games.
# Only the audioFiles mapping is dynamic.

AUDIO_MANAGER_TEMPLATE = """// ==================== AUDIO MANAGER ====================
var AudioManager = (function(){{
  var audioCtx = null;
  var buffers = {{}};
  var bgmSource = null;
  var bgmGain = null;
  var masterGain = null;
  var resumed = false;
  var SFX_VOL = 0.7;
  var BGM_VOL = 0.3;
  var audioFiles = {{
{file_entries}
  }};

  function getContext(){{
    if(!audioCtx){{
      try{{
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        masterGain = audioCtx.createGain();
        masterGain.gain.value = 1.0;
        masterGain.connect(audioCtx.destination);
      }}catch(e){{
        console.warn('Web Audio API not supported');
        return null;
      }}
    }}
    return audioCtx;
  }}

  function resumeOnInteraction(){{
    if(resumed) return;
    var ctx = getContext();
    if(ctx && ctx.state === 'suspended'){{
      ctx.resume().then(function(){{ resumed = true; }}).catch(function(){{}});
    }} else {{
      resumed = true;
    }}
  }}

  function setupInteractionGate(){{
    var events = ['touchstart','touchend','mousedown','click','keydown','pointerdown'];
    function handler(){{
      resumeOnInteraction();
      for(var i=0;i<events.length;i++){{
        document.removeEventListener(events[i], handler, true);
      }}
    }}
    for(var i=0;i<events.length;i++){{
      document.addEventListener(events[i], handler, {{capture:true, passive:true}});
    }}
  }}
  setupInteractionGate();

  function preload(){{
    var ctx = getContext();
    if(!ctx) return;
    var uniqueUrls = {{}};
    var keys = Object.keys(audioFiles);
    for(var i=0;i<keys.length;i++){{
      var url = audioFiles[keys[i]];
      if(!uniqueUrls[url]){{
        uniqueUrls[url] = true;
        (function(u){{
          var xhr = new XMLHttpRequest();
          xhr.open('GET', u, true);
          xhr.responseType = 'arraybuffer';
          xhr.onload = function(){{
            if(xhr.status === 200 || xhr.status === 0){{
              ctx.decodeAudioData(xhr.response, function(buffer){{
                buffers[u] = buffer;
              }}, function(){{
                console.warn('Failed to decode: ' + u);
              }});
            }}
          }};
          xhr.onerror = function(){{ console.warn('Failed to load: ' + u); }};
          xhr.send();
        }})(url);
      }}
    }}
  }}

  function playSFX(name, volumeOverride){{
    var ctx = getContext();
    if(!ctx) return;
    resumeOnInteraction();
    var url = audioFiles[name];
    if(!url) return;
    var buffer = buffers[url];
    if(!buffer) return;
    try{{
      var source = ctx.createBufferSource();
      source.buffer = buffer;
      var gainNode = ctx.createGain();
      gainNode.gain.value = (volumeOverride !== undefined) ? volumeOverride : SFX_VOL;
      source.connect(gainNode);
      gainNode.connect(masterGain);
      source.start(0);
    }}catch(e){{}}
  }}

  function playBGM(name){{
    var ctx = getContext();
    if(!ctx) return;
    resumeOnInteraction();
    if(bgmSource){{
      try{{ bgmSource.stop(); }}catch(e){{}}
      bgmSource = null;
    }}
    var url = audioFiles[name];
    if(!url) return;
    var buffer = buffers[url];
    if(!buffer) return;
    try{{
      bgmSource = ctx.createBufferSource();
      bgmSource.buffer = buffer;
      bgmSource.loop = true;
      bgmGain = ctx.createGain();
      bgmGain.gain.value = BGM_VOL;
      bgmSource.connect(bgmGain);
      bgmGain.connect(masterGain);
      bgmSource.start(0);
    }}catch(e){{}}
  }}

  function stopBGM(){{
    if(bgmSource){{
      try{{ bgmSource.stop(); }}catch(e){{}}
      bgmSource = null;
    }}
  }}

  preload();

  return {{
    playSFX: playSFX,
    playBGM: playBGM,
    stopBGM: stopBGM,
    preload: preload,
    resumeOnInteraction: resumeOnInteraction
  }};
}})();
// ==================== END AUDIO MANAGER ===================="""


# ─────────────────────── AI PROMPT ───────────────────────

SYSTEM_PROMPT = """You are an expert HTML5 game audio integrator.

Your task: analyze game code and decide WHERE to insert audio play calls.

You do NOT rewrite the HTML. You return a JSON object with insertion instructions.

RULES:
1. Each "anchor" must be an EXACT line from the original code (copy-paste, including whitespace).
2. Pick anchors that are UNIQUE in the file. Avoid generic lines like "}" or "break;".
3. If a good anchor appears multiple times, include "context_before" (the line above it) to disambiguate.
4. "position" is "after" (insert below anchor) or "before" (insert above anchor). Default "after".
5. Volume: SFX default 0.7, BGM 0.3. Override with second param for quieter effects (e.g. 0.35 for subtle sounds).
6. Use event_id as the sound key (e.g. AudioManager.playSFX('sfx_jump'))
7. For BGM, use AudioManager.playBGM('bgm_gameplay')
8. For stopping BGM, use AudioManager.stopBGM()

Return ONLY this JSON structure:
{
  "insert_block_after": "<exact line after which to insert the AudioManager block, e.g. a <script> tag or first var declaration>",
  "calls": [
    {
      "anchor": "<exact line from original code>",
      "context_before": "<line above anchor, for disambiguation, optional>",
      "position": "after",
      "code": "AudioManager.playSFX('sfx_jump');",
      "comment": "Audio: player jump"
    }
  ]
}

IMPORTANT: Keep the calls list focused. Only add audio where it makes a clear difference.
Typical game needs 5-15 audio insertions. Don't over-instrument."""


def _build_audio_manager_block(events, mapping):
    """Build the AudioManager JS block with the correct audioFiles mapping."""
    file_entries = []
    for event in events:
        eid = event["event_id"]
        entry = mapping.get(eid)
        if entry:
            filename = entry["original_name"]
            file_entries.append(
                f"    '{eid}': '{AUDIO_SUBFOLDER}/{filename}'"
            )

    if not file_entries:
        return None

    entries_str = ",\n".join(file_entries)
    return AUDIO_MANAGER_TEMPLATE.format(file_entries=entries_str)


def _find_anchor_line(lines, anchor, context_before=None):
    """
    Find the line index matching the anchor.
    If context_before is provided, use it to disambiguate multiple matches.
    Returns line index or -1.
    """
    anchor_stripped = anchor.strip()
    matches = []

    for i, line in enumerate(lines):
        if line.strip() == anchor_stripped:
            matches.append(i)

    if not matches:
        # Fuzzy: try substring match (anchor might be truncated)
        for i, line in enumerate(lines):
            if anchor_stripped and anchor_stripped in line.strip():
                matches.append(i)

    if not matches:
        return -1

    if len(matches) == 1:
        return matches[0]

    # Multiple matches — use context_before to disambiguate
    if context_before:
        ctx_stripped = context_before.strip()
        for idx in matches:
            if idx > 0 and lines[idx - 1].strip() == ctx_stripped:
                return idx

    # Fallback: return first match
    return matches[0]


def _find_block_insertion_point(lines):
    """
    Find the best place to insert the AudioManager block.
    Prefer: after the last <script src="..."> tag, before game code starts.
    """
    last_script_src = -1
    first_script_inline = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        # <script src="..."></script> or <script src="...">
        if '<script' in stripped and 'src=' in stripped:
            last_script_src = i
        # <script> without src (inline script start)
        elif '<script>' in stripped or '<script ' in stripped:
            if 'src=' not in stripped and first_script_inline == -1:
                first_script_inline = i

    # Insert after last external script, or after first inline <script>
    if last_script_src >= 0:
        return last_script_src
    if first_script_inline >= 0:
        return first_script_inline

    # Fallback: after <body>
    for i, line in enumerate(lines):
        if '<body' in line:
            return i

    return 0


def _apply_patches(html_content, am_block, ai_patches, verbose=True):
    """
    Apply the AudioManager block and inline patches to the original HTML.
    Returns the modified HTML string.
    """
    lines = html_content.splitlines(True)  # keep newlines

    # Collect all insertions as (line_index, position, code_lines)
    insertions = []

    # 1. Find where to insert AudioManager block
    block_anchor = ai_patches.get("insert_block_after", "").strip()
    if block_anchor:
        idx = _find_anchor_line(lines, block_anchor)
    else:
        idx = -1

    if idx < 0:
        idx = _find_block_insertion_point(lines)

    insertions.append((idx, "after", am_block + "\n"))
    if verbose:
        print(f"  [Injector] AudioManager block → after line {idx + 1}")

    # 2. Process each call patch
    calls = ai_patches.get("calls", [])
    applied = 0
    skipped = 0

    for call in calls:
        anchor = call.get("anchor", "")
        ctx = call.get("context_before")
        position = call.get("position", "after")
        code = call.get("code", "")
        comment = call.get("comment", "")

        if not anchor or not code:
            skipped += 1
            continue

        line_idx = _find_anchor_line(lines, anchor, ctx)
        if line_idx < 0:
            if verbose:
                print(f"    ✗ Anchor not found: {anchor.strip()[:60]}")
            skipped += 1
            continue

        # Detect indentation from anchor line
        anchor_line = lines[line_idx]
        indent = re.match(r'^(\s*)', anchor_line).group(1)

        # Build insertion text
        insert_lines = ""
        if comment:
            insert_lines += f"{indent}// {comment}\n"
        insert_lines += f"{indent}{code}\n"

        insertions.append((line_idx, position, insert_lines))
        applied += 1
        if verbose:
            print(f"    ✓ L{line_idx + 1} ({position}): {code.strip()[:60]}")

    if verbose:
        print(f"  [Injector] Applied {applied}/{applied + skipped} patches")

    # 3. Apply insertions (process from bottom to top to preserve indices)
    insertions.sort(key=lambda x: (-x[0], 0 if x[1] == "before" else 1))

    for line_idx, position, code_text in insertions:
        code_lines = code_text.splitlines(True)
        if position == "after":
            insert_at = line_idx + 1
        else:
            insert_at = line_idx

        for j, cl in enumerate(code_lines):
            lines.insert(insert_at + j, cl)

    return "".join(lines)


# ─────────────────────── PUBLIC API ───────────────────────

def inject_audio(
    html_content: str,
    events: list[dict],
    mapping: dict[str, dict | None],
) -> str:
    """
    Inject audio into game HTML using patch mode.

    1. Build AudioManager block from template (deterministic)
    2. Ask AI for insertion points only (small JSON output)
    3. Apply patches to original HTML (deterministic)
    """
    # Filter to matched events only
    matched = [e for e in events if mapping.get(e["event_id"]) is not None]
    if not matched:
        print("  [Injector] No audio matches to inject, skipping.")
        return html_content

    # 1. Build AudioManager block
    am_block = _build_audio_manager_block(events, mapping)
    if not am_block:
        print("  [Injector] Failed to build AudioManager block.")
        return html_content

    # 2. Build event summary for AI
    event_summary = []
    for event in matched:
        eid = event["event_id"]
        entry = mapping[eid]
        event_summary.append({
            "event_id": eid,
            "type": event["type"],
            "description": event["description"],
            "code_context": event.get("code_context", ""),
            "injection_hint": event.get("injection_hint", ""),
        })

    user_prompt = f"""Analyze this HTML5 game and tell me WHERE to insert audio play calls.

AUDIO EVENTS TO INSERT:
{json.dumps(event_summary, indent=2)}

For SFX events, use: AudioManager.playSFX('event_id')
For SFX with custom volume: AudioManager.playSFX('event_id', 0.35)
For BGM events, use: AudioManager.playBGM('event_id')
To stop BGM: AudioManager.stopBGM()

GAME CODE:
{html_content}

Return the JSON with "insert_block_after" and "calls" array. Each call needs an exact "anchor" line from the code above."""

    print(f"  [Injector] Asking AI for {len(matched)} insertion points...")
    ai_patches = call_ai_json(SYSTEM_PROMPT, user_prompt)

    # 3. Apply patches
    modified = _apply_patches(html_content, am_block, ai_patches)

    # 4. Sanity checks
    if "AudioManager" not in modified:
        print("  [Injector] WARNING: AudioManager not found in output!")
    if "<!DOCTYPE" not in modified and "<html" not in modified:
        print("  [Injector] WARNING: Output doesn't look like valid HTML!")

    sfx_count = modified.count("AudioManager.playSFX")
    bgm_count = modified.count("AudioManager.playBGM")
    print(f"  [Injector] Result: {sfx_count} SFX + {bgm_count} BGM calls injected")

    return modified