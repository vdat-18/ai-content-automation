[English](README.md) · **Tiếng Việt**

# AI Content Automation

Tạo video quảng cáo TikTok Shop Việt Nam từ một sản phẩm: kịch bản, ảnh từng cảnh, clip, giọng đọc,
video ghép hoàn chỉnh và caption. Người dùng đọc **kịch bản** và duyệt từng **ảnh** trước khi tốn tiền làm video.

## Luồng làm một video

1. **Thu thập** (extension Chrome trong `extension/`): sản phẩm TikTok Shop và ảnh tham chiếu Pinterest
   gửi về `POST /api/v1/products/ingest`.
2. **Idea → Script**: mỗi video theo **một người** trong thư viện người (ảnh tải lên một lần, dùng cho mọi
   sản phẩm; một người là mặc định, đổi được bất cứ lúc nào; bắt buộc có ảnh). Mặt trong ảnh sinh ra khớp
   ảnh đó, quần áo và bối cảnh đổi theo từng cảnh; video giữ người nó được viết cho dù mặc định đổi.
   AI viết kịch bản (brief). Các quy tắc đã duyệt trong `config/creative_knowledge/product_ad.json` dặn AI
   tránh từ cấm của TikTok Shop và chỉ dùng số liệu, khẳng định có trong dữ liệu sản phẩm. Không có code nào
   kiểm tra lại văn bản sau đó, nên hãy đọc kỹ: từng câu kịch bản hiện trên thẻ ảnh ở bước Images; API có
   thể dừng sau kịch bản (`until=script`) hoặc sửa nó (`PUT .../brief`).
3. **Images**: ảnh master trước, các cảnh còn lại sau. Mỗi ảnh được kiểm tra với ảnh sản phẩm thật và ảnh
   người mẫu. Pipeline luôn dừng sau ảnh master cho tới khi bạn duyệt; ảnh bị kiểm tra đánh dấu sẽ hiện
   cảnh báo, ảnh chưa kiểm tra được hiện là "Not checked".
4. **Finish**: clip (ảnh → video), giọng đọc, ghép video 9:16, caption và hashtag. Clip lỗi hoặc bị đánh dấu
   nằm trong danh sách "Scenes that need a look" để làm lại hoặc dùng luôn.

Pipeline chạy nền trên server, kết quả và lý do dừng được lưu (xem `product_pipeline_runs`) và có thông báo
khi xong. Chạy lại luôn tiếp tục từ phần đã làm, không làm lại phần đã có.

## Chạy

Yêu cầu: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node + pnpm, ffmpeg (ghép video, giọng, kiểm tra)
và một database PostgreSQL (`AIC_AI_DATABASE_URL`; chạy `uv run alembic upgrade head` một lần). Chạy bằng
Docker bên dưới là dễ nhất vì đã có sẵn PostgreSQL.

```bash
uv sync --extra dev
uv run uvicorn ai_content.entrypoints.api.app:app --reload   # API: http://127.0.0.1:8000
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev -- --port 4174                         # http://localhost:4174/dashboard/
```

Docker (PostgreSQL, SeaweedFS, API, dashboard): sao chép `deploy/.env.example` thành `deploy/.env`, điền khoá
rồi dùng `just up`. Dashboard và API **không có đăng nhập**, nên mặc định chỉ nghe trên `127.0.0.1`
(`AIC_HTTP_BIND_ADDRESS`). Muốn mở ra ngoài thì bật đăng nhập nginx bằng `deploy/nginx/auth.example.conf`
(hướng dẫn trong file) hoặc đặt sau VPN.

## Cấu hình chính (`deploy/.env.example`)

| Biến | Dùng cho |
|---|---|
| `AIC_SCREENING_BASE_URL`, `AIC_SCREENING_API_KEY` | Endpoint OpenAI-compatible cho mọi bước LLM; không có key thì mọi bước LLM tắt |
| `AIC_WRITER_MODEL` | Model viết brief, hook, caption, rút gọn lời thoại và quy tắc (bắt buộc) |
| `AIC_REVIEW_MODEL` | Model kiểm tra ảnh, keyframe, clip, chọn ảnh tham chiếu và giọng (bắt buộc) |
| `AIC_IMAGE_*`, `AIC_IMAGE_API` | Model tạo ảnh (`chat` hoặc `edits`) |
| `AIC_VIDEO_*` | Model ảnh → video; `AIC_VIDEO_FRAME_FIELDS` chọn trường nhận khung hình đầu (mặc định `image`, đã thử thật) |
| `AIC_TTS_*` | Giọng đọc |
| `AIC_TEXT_EMBEDDING_MODEL` | Ghép ảnh tham chiếu cho từng cảnh (để trống thì tắt) |
| `AIC_EMBEDDING_MODEL` | Model ảnh chạy local để loại ảnh tham chiếu trùng (`dinov3-vits16`, `dinov2-small`; để trống thì tắt và không lưu được ảnh tham chiếu nào) |
| `AIC_TTS_SPEED`, `AIC_CLIP_SPEED`, `AIC_DUPLICATE_SIMILARITY` | Tốc độ giọng đọc (mặc định 1.1), tốc độ phát clip (1.1), ngưỡng trùng ảnh (0.80) |
| `AIC_BGM_PATH`, `AIC_CAPTION_FONT` | Nhạc nền và font caption tuỳ chọn (mặc định `config/default_bgm.wav`, DejaVu Sans) |
| `AIC_AI_DATABASE_URL` | URL PostgreSQL (`postgresql+psycopg://...`); chỉ hỗ trợ PostgreSQL |

Quy tắc mặc định cho quảng cáo nằm trong `config/creative_knowledge/product_ad.json`. Server nạp chúng khi
khởi động. Sửa nội dung file thì phải đổi `bootstrap_id`, test sẽ nhắc.

## Backup và khôi phục

`just backup` (hoặc `just backup-server` trên máy Linux) tạm dừng API và dashboard, ghi một bộ backup đã
kiểm tra gồm bản dump PostgreSQL và mọi object trong bucket vào `.backups/<id>`, rồi chép ra ngoài khi
`AIC_BACKUP_OFFSITE_ENABLED` bật. `just deploy-safe` backup trước, sau đó pull, build lại và chạy smoke test.
`deploy/scripts/restore-drill.sh <bộ backup>` khôi phục thử vào một stack dùng một lần để chứng minh dùng được.
`deploy/systemd/` có timer chạy hằng ngày cho server.

## Kiểm tra

Chạy trong Docker (có sẵn ffmpeg và font, giống mọi máy; không cần cài gì trên máy):

```bash
just test            # hoặc: just test tests/test_stickers.py
just lint
```

Chạy thẳng trên máy: cần một database PostgreSQL rỗng dùng một lần trong `AIC_AI_DATABASE_URL` (mỗi test
xoá sạch nó; không chạy hai phiên test cùng một database) và ffmpeg (test cần ffmpeg bị bỏ qua nếu máy không có):

```bash
uv run ruff check .
uv run pytest
pnpm --dir frontend lint && pnpm --dir frontend test && pnpm --dir frontend build
```

Sau khi sửa `baml_src/`, sinh lại client: `uv run baml-cli generate` (không sửa tay `adapters/baml_client`).
Migration PostgreSQL nằm trong `migrations/`. Test cần PostgreSQL nên chạy bằng `just test` (Docker tự bật
một database dùng một lần).

## Tài liệu

- `docs/video-ads-pipeline.md`: thiết kế gốc của luồng ảnh → clip → video.
- `docs/model-limits.md`, `docs/reference-corpus-and-content-plan.md`.
- `frontend/DEVELOPMENT.md`, `extension/README.md`.
