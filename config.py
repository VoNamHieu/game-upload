"""
Configuration for Auto SFX/BGM Tool
Update paths to match your local setup.
"""
import os

# ─── Anthropic API ───
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")
MODEL = "claude-opus-4-6"
MAX_TOKENS = 16384

# ─── Paths ───
GAMES_DIR = "./games"           # folder chứa các file .zip game
SOUNDS_BGM_DIR = "./sounds/BGM" # folder chứa subfolder BGM (Action/, Sci-fi/, ...)
SOUNDS_SFX_DIR = "./sounds/SFX" # folder chứa subfolder SFX (Animal/, UI/, ...)
SOUND_INDEX_PATH = "./catalogs/sound_index.json"
OUTPUT_DIR = "./output"         # game đã xử lý xong

# ─── Processing ───
SHORTLIST_SIZE = 25             # max candidates per event gửi cho AI chọn
EVENTS_PER_BATCH = 5            # gộp bao nhiêu events trong 1 lần gọi matching
AUDIO_SUBFOLDER = "assets/audio" # folder trong game zip để chứa nhạc