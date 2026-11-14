# Giới hạn của các model đang dùng

Số liệu đo trực tiếp qua ViLao (`https://api.vilao.ai/v1`), không lấy từ tài liệu bên ngoài. Cách
đo: script gửi ảnh đánh số hoặc clip thử rồi xem kết quả trả về. Đo lại khi đổi model hoặc nhà cung
cấp. Ghi ngày đo ở mỗi mục.

## Model ảnh: `veo/gemini-3.1-flash-image` (đo 2026-11-05 và 2026-11-06)

| Mục | Kết quả đo |
| --- | --- |
| Số ảnh đầu vào mỗi yêu cầu | Nhận và dùng đủ **30 ảnh** (đã thử 5, 14, 15, 20, 30; ảnh trả về có đủ số). Từ 31 đến 40 ảnh báo "upstream overloaded", nhưng lỗi này cũng xảy ra lúc thử lại 30 ảnh, nên chưa chứng minh được giới hạn trên 30 |
| Số ảnh đầu ra mỗi yêu cầu | **1 ảnh**. Gửi `n: 3` hay bảo "làm 4 ảnh" vẫn chỉ ra 1 ảnh (1 `choice`, 1 link) |
| Thời gian | 60 đến 80 giây mỗi yêu cầu |
| Size ảnh dọc | `size: "1024x1792"` cho ảnh 768x1376. `size: "9:16"` bị lỗi, không dùng |
| Giá | 50 đ mỗi yêu cầu |

## Model video: `xai/grok-imagine-video` (khai báo `dw/xai/grok-imagine-video`, đo 2026-11-06)

| Mục | Kết quả đo |
| --- | --- |
| Ảnh làm khung đầu (image-to-video) | Đúng **1 ảnh**. Clip bắt đầu từ ảnh này, giữ bố cục |
| Độ dài clip image-to-video | `seconds` từ **1 đến 15** (đã thử 5, 8, 10, 12, 15 đều chạy; 16, 20, 30 bị từ chối: "seconds phải từ 1 đến 15"). `/models` chỉ liệt kê 6 và 15 nhưng các số khác vẫn chạy |
| Độ phân giải | 704x1280 khi có ảnh khung đầu, 720x1280 khi chỉ có ảnh tham chiếu. Có hay không có `quality: "720p"` đều như nhau |
| Ảnh tham chiếu (`reference_images`) | Tối đa **7 ảnh**. Gửi 8 ảnh bị từ chối: "nhận tối đa 7 ảnh tham chiếu" |
| Độ dài clip khi dùng ảnh tham chiếu | Tối đa **10 giây** (10 giây chạy; 12 và 15 giây job báo "Yêu cầu không hợp lệ") |
| Ảnh khung đầu cùng lúc với ảnh tham chiếu | **Bị từ chối** |
| Ảnh tham chiếu không có khung đầu | Video dùng đúng hình tham chiếu nhưng dựng lại toàn bộ cảnh, không giữ bố cục |
| Âm thanh | Clip có sẵn một track âm thanh (AAC) do Grok tự tạo, kể cả khi prompt bảo "không tiếng"; có thể ra lệnh cho Grok nói câu tiếng Việt, miệng cử động theo tiếng đó |
| Giá | 999 đ mỗi yêu cầu, không phụ thuộc số giây |

**Quy tắc dùng (chốt 2026-11-14):** giá tính theo yêu cầu, không theo số giây hay độ phân giải, nên
mỗi lần tạo clip luôn xin mức dài nhất và nét nhất model nhận: `seconds = 15` (`CLIP_SECONDS` trong
`clips.py`), khung 9:16 với keyframe làm khung đầu (704x1280, không có mức cao hơn). Không xin clip
ngắn hơn hay nhỏ hơn để tiết kiệm; cần ngắn thì cắt sau khi tạo. Đo lại khi đổi model hoặc nhà cung cấp.

Hệ quả: clip chỉ chọn một trong hai cách, keyframe làm khung đầu (đang dùng, tối đa 15 giây) hoặc tối
đa 7 ảnh tham chiếu (tối đa 10 giây). Sản phẩm phải đúng ngay ở keyframe.

## TTS: `bh2/tts-1` (đo 2026-11-06)

| Mục | Kết quả đo |
| --- | --- |
| Đầu vào | `input` là văn bản, kèm `voice` (`giongadam.mp3`, `hamy.mp3`, `tiendat.mp3`, `huuduc.mp3`, `kimoanh.mp3`, `maichi.mp3`, `auto`) và `response_format` (`mp3` hoặc `wav` theo `/models`) |
| Đầu ra | Một file âm thanh. mp3: 24 kHz, mono, khoảng 49 kbps |
| Độ dài đã chạy được | 400 ký tự (84 từ tiếng Việt) cho ra **28,9 giây** âm thanh, mất 11 giây để tạo; 80 ký tự cho 5,6 giây |
| Giới hạn độ dài tối đa | **Chưa đo được**: dịch vụ chập chờn, các yêu cầu 800 ký tự trở lên trả `503 upstream request failed` sau 120 giây, nhưng cả yêu cầu 80 ký tự cũng lỗi cùng lúc đó. Đo lại khi dịch vụ ổn định |
| Định dạng wav | Chưa đo được vì cùng lý do |
| Giá | 20 đ mỗi yêu cầu |

## Model chấm và viết brief: `gemini/gemini-3.6-flash`, dự phòng `cc/claude-sonnet-5`

Chưa đo giới hạn số ảnh. Qua 9Router (`AIC_SCREENING_BASE_URL`). Brief hiện gửi tối đa 9 ảnh sản phẩm
mà vẫn chạy. Đã gặp: đầu ra bị cắt cụt khi `max_tokens` nhỏ vì Gemini tốn token để suy nghĩ, nên đặt
`max_output_tokens` cho brief là 12000 và cho các bước chấm là 4000.
