# AI Content Automation

Tạo video quảng cáo TikTok Shop Việt Nam từ một sản phẩm: kịch bản, ảnh từng cảnh, clip, giọng đọc,
video ghép hoàn chỉnh và caption. Người dùng chỉ đọc và duyệt ở hai chốt: **kịch bản** và **ảnh**.

## Luồng làm một video

1. **Thu thập** (extension Chrome trong `extension/`): sản phẩm TikTok Shop và ảnh tham chiếu Pinterest
   gửi về `POST /api/v1/products/ingest`.
2. **Idea → Script**: AI viết kịch bản (brief). Kịch bản được kiểm tra: từ cấm của TikTok Shop, số liệu
   và khẳng định phải có trong dữ liệu sản phẩm (kể cả số đọc thành chữ). Pipeline dừng để bạn đọc.
3. **Images**: ảnh master trước, các cảnh còn lại sau. Mỗi ảnh được kiểm tra với ảnh sản phẩm thật và ảnh
   người mẫu. Master bị đánh dấu thì pipeline dừng; ảnh chưa kiểm tra được hiện là "Not checked".
4. **Finish**: clip (ảnh → video), giọng đọc, ghép video 9:16, caption và hashtag. Clip lỗi hoặc bị đánh dấu
   nằm trong danh sách "Scenes that need a look" để làm lại hoặc dùng luôn.

Pipeline chạy nền trên server, kết quả và lý do dừng được lưu (xem `product_pipeline_runs`) và có thông báo
khi xong. Chạy lại luôn tiếp tục từ phần đã làm, không làm lại phần đã có.

## Chạy

Yêu cầu: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node + pnpm, ffmpeg (ghép video, giọng, kiểm tra).

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
| `AIC_SCREENING_*` | LLM viết brief, kiểm tra ảnh và clip, review kịch bản (OpenAI-compatible) |
| `AIC_IMAGE_*`, `AIC_IMAGE_API` | Model tạo ảnh (`chat` hoặc `edits`) |
| `AIC_VIDEO_*` | Model ảnh → video; `AIC_VIDEO_FRAME_FIELDS` chọn trường nhận khung hình đầu (thu còn một trường khi đã biết trường nào chạy) |
| `AIC_TTS_*` | Giọng đọc |
| `AIC_TEXT_EMBEDDING_MODEL` | Ghép ảnh tham chiếu cho từng cảnh (để trống thì tắt) |
| `AIC_AI_DATABASE_BACKEND` | `sqlite` (dev) hoặc `postgresql` |

Quy tắc mặc định cho quảng cáo nằm trong `config/creative_knowledge/product_ad.json`. Server nạp chúng khi
khởi động. Sửa nội dung file thì phải đổi `bootstrap_id`, test sẽ nhắc.

## Kiểm tra

```bash
uv run ruff check .
uv run pytest
pnpm --dir frontend lint && pnpm --dir frontend test && pnpm --dir frontend build
```

Sau khi sửa `baml_src/`, sinh lại client: `uv run baml-cli generate` (không sửa tay `adapters/baml_client`).
Migration PostgreSQL nằm trong `migrations/`; SQLite tự tạo bảng khi mở.

## Tài liệu

- `docs/video-ads-pipeline.md`: thiết kế gốc của luồng ảnh → clip → video.
- `docs/model-limits.md`, `docs/affiliate-vietnam.md`, `docs/reference-corpus-and-content-plan.md`.
- `frontend/DEVELOPMENT.md`, `extension/README.md`.
