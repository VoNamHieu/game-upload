# Game Upload Pipeline

Upload game `.zip` lên Operation Web (Rezona Create Pro), lấy Share URL ghi
về CSV.

## Setup

```bash
pip install -r requirements.txt
```

Folder structure:
```
upload-pipeline/
├── games/              ← drop file .zip game vào đây
├── covers/             ← ảnh cover, đặt tên CÙNG stem với zip
├── fixed games/        ← (optional) zip đã fix, tên <name>_fixed.zip
├── games.csv           ← tự sinh bằng prepare_csv.py, paste User ID vào cột 1
└── results.csv         ← output: Share URL + Reupload URL (auto-generated)
```

### Quy tắc đặt tên (quan trọng)
- Zip và cover **cùng tên stem** để match. Ví dụ:
  ```
  games/space-shooter.zip
  covers/space-shooter.jpg
  ```
- Cover optional: thiếu cover vẫn upload được (không có ảnh).
- Cover chấp nhận: `.jpg / .jpeg / .png / .webp / .gif`.

## Flow

```bash
# 1. Drop .zip vào games/, drop cover vào covers/ (cùng tên)

# 2. Sinh games.csv tự động (cột User ID để trống)
python3 prepare_csv.py

# 3. Mở games.csv, paste User ID vào cột 1 cho từng dòng

# 4. Dry run xem trước
python3 upload_games.py --dry-run

# 5. Upload
python3 upload_games.py --workers 5

# 6. Kết quả ghi vào results.csv (cột Share URL)
```

## Reupload (game đã fix)

```bash
# 1. Bỏ zip fix vào fixed games/ với tên <name>_fixed.zip
# 2. Upload lại, URL mới ghi vào cột Reupload URL
python3 upload_games.py --reupload --workers 5
```

## Resume

Nếu bị dừng giữa chừng, chạy lại với `--resume` để bỏ qua game đã có URL:
```bash
python3 upload_games.py --resume
python3 upload_games.py --reupload --resume
```

## CSV format

**games.csv** (input):
| User ID | Game UUID | Source |
|---|---|---|
| 123 | space-shooter | space-shooter.zip |

- `Game UUID` = stem tên zip (prepare_csv.py tự điền)
- `Source` = tên zip đầy đủ (để tham chiếu)
- `User ID` = paste tay

**results.csv** (output): 7 cột — `User ID, Game UUID, Source, Share URL, Error, Reupload URL, Reupload Error`.

## Config

Server/password mặc định có trong `upload_games.py` (hằng số ở đầu file).
Override qua CLI nếu cần: `--host`, `--password`, `--workers`.
