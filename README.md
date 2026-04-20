# game-upload

Repo gồm 2 pipeline độc lập, mỗi folder tự chứa và có thể tải/dùng riêng:

## [audio-pipeline/](audio-pipeline/)
Tự động thêm nhạc nền (BGM) và hiệu ứng âm thanh (SFX) vào game HTML5 bằng AI.
Input: `.zip` game. Output: `.zip` đã chèn audio.

## [upload-pipeline/](upload-pipeline/)
Upload game `.zip` lên Operation Web (Rezona Create Pro), lấy share URL ghi
về CSV. Nhận input từ CSV + folder zip + folder cover (zip và cover phải
cùng tên để match).

## Chain 2 pipeline (tuỳ chọn)
Sau khi `audio-pipeline` chạy xong, copy hoặc symlink sang `upload-pipeline/games/`:

```bash
cp audio-pipeline/output/*.zip upload-pipeline/games/
# hoặc
ln -sf ../upload-pipeline/games audio-pipeline/output
```
