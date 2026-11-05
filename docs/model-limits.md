# Giới hạn của các model đang dùng

Số liệu đo trực tiếp ngày 2026-11-05 qua ViLao (`https://api.vilao.ai/v1`), không lấy từ tài liệu
bên ngoài. Cách đo: script gửi ảnh đánh số, xem kết quả trả về. Đo lại khi đổi model hoặc nhà
cung cấp.

## Model ảnh: `veo/gemini-3.1-flash-image`

| Mục | Kết quả đo |
| --- | --- |
| Số ảnh đầu vào mỗi yêu cầu | Nhận và dùng đủ **20 ảnh** (đã thử 5, 14, 15, 20; không bị cắt ở 14). Chưa thử trên 20 |
| Thời gian | 60 đến 80 giây mỗi yêu cầu |
| Size ảnh dọc | `size: "1024x1792"` cho ảnh 768x1376. `size: "9:16"` bị lỗi, không dùng |
| Giá | 50 đ mỗi yêu cầu |

## Model video: `xai/grok-imagine-video` (khai báo `dw/xai/grok-imagine-video`)

| Mục | Kết quả đo |
| --- | --- |
| Ảnh làm khung đầu (image-to-video) | Đúng **1 ảnh**. Clip bắt đầu từ ảnh này, giữ bố cục |
| Độ phân giải | 704x1280 khi có ảnh khung đầu, 720x1280 khi chỉ có ảnh tham chiếu. Có hay không có `quality: "720p"` đều như nhau, không cần gửi |
| Ảnh tham chiếu (`reference_images`) | Chạy được, tối đa **7 ảnh**. Gửi 8 ảnh bị từ chối: "nhận tối đa 7 ảnh tham chiếu" |
| Ảnh khung đầu cùng lúc với ảnh tham chiếu | **Bị từ chối** ("Yêu cầu không hợp lệ") |
| Ảnh tham chiếu không có khung đầu | Video dùng đúng hình tham chiếu nhưng dựng lại toàn bộ cảnh, không giữ bố cục |
| Độ dài | 6 hoặc 15 giây (`/models` của ViLao) |
| Giá | 999 đ mỗi yêu cầu |

Hệ quả: clip chỉ chọn một trong hai cách, keyframe làm khung đầu (đang dùng) hoặc tối đa 7 ảnh
tham chiếu. Sản phẩm phải đúng ngay ở keyframe.

## Model chấm và viết brief: `gemini/gemini-3.6-flash`, dự phòng `cc/claude-sonnet-5`

Chưa đo. Cổng `AIC_SCREENING_BASE_URL` không chạy lúc đo. Đo khi cổng bật.

## TTS: `bh2/tts-1`

Giá 20 đ mỗi yêu cầu; giọng, tốc độ xem `AIC_TTS_*` trong `deploy/.env`.
