# Auto SFX/BGM Tool

Tự động thêm nhạc nền (BGM) và hiệu ứng âm thanh (SFX) vào game HTML5 bằng AI.

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set API key
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. Chuẩn bị folder structure
auto-sfx-tool/
├── games/                    ← bỏ file .zip game vào đây
├── sounds/
│   ├── BGM/                  ← copy folder SOUND_BGM_POOL_879 vào đây
│   │   ├── Action/
│   │   ├── Sci-fi/
│   │   └── ...
│   └── SFX/                  ← copy folder SFX vào đây
│       ├── Animal/
│       ├── UI/
│       └── ...
├── catalogs/
│   └── sound_index.json     ← đã có sẵn (1184 entries)
└── output/                   ← game đã xử lý
```

`sound_index.json` đã build sẵn từ 2 CSV (879 BGM + 305 SFX).
Chỉ cần chạy `python build_index.py` nếu muốn rebuild khi có nhạc mới.

## Usage

```bash
# Process tất cả game trong games/
python main.py

# Process 1 game cụ thể
python main.py my-game.zip

# Chỉ phân tích, không sửa code (dry run)
python main.py --dry-run my-game.zip
```

## Pipeline

```
Game .zip → Unzip → Tìm .html → AI phân tích → Filter catalog → AI chọn nhạc → AI sửa code → Copy nhạc → Zip lại
```

1. **Analyze**: AI đọc code game, liệt kê điểm cần nhạc
2. **Filter**: Python lọc catalog 1184 files → shortlist 25 files/event (theo tags)
3. **Match**: AI chọn file nhạc phù hợp nhất từ shortlist
4. **Inject**: AI sửa code HTML thêm audio playback
5. **Package**: Copy file nhạc + zip lại giữ tên file gốc

## Config

Sửa `config.py` để thay đổi:
- `MODEL`: model AI (default: claude-sonnet-4-20250514)
- `SHORTLIST_SIZE`: số candidates/event (default: 25)
- `AUDIO_SUBFOLDER`: folder chứa nhạc trong game (default: assets/audio)

## Cost

~$0.08-0.20 per game (Sonnet), tùy kích thước code.
