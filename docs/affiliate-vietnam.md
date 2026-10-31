# AI Content Automation for Affiliate Marketing

Hệ thống tự động hóa sản xuất nội dung hình ảnh và video ngắn (30–60s) phục vụ tiếp thị liên kết (Affiliate Marketing) trên các nền tảng video ngắn (TikTok Shop, Shopee Video, Facebook Reels). 

Định hướng vận hành: AI tự động nghiên cứu, viết kịch bản, render ảnh và video; người dùng kiểm duyệt nhanh (Human-in-the-loop) trước khi xuất bản cùng link affiliate.

---

## 1. Input & Output

### Input
- **Sản phẩm (Product Data)**:
  - Ảnh packshot sản phẩm gốc (ảnh chất lượng cao, rõ bao bì/nhãn mác/chi tiết).
  - Thông tin cơ bản: Tên sản phẩm, tính năng cốt lõi, công dụng nổi bật, phân khúc khách hàng.
- **Quy tắc thương hiệu (Brand Guidelines & Rules)**:
  - Tone of voice (phong cách ngôn từ), phong cách thị giác (visual style).
  - Quy tắc tuân thủ (Claims rules: từ khóa cấm, rào cản nền tảng, không nói quá công dụng).
- **Tư liệu tham khảo (Reference Ads - Tùy chọn / Tự động)**:
  - Các mẫu quảng cáo thực tế từ thị trường đã qua bộ lọc (được duyệt về góc chụp, bối cảnh để ghép sản phẩm vào).

### Output
- **Gói nội dung xuất bản (Post Package)**:
  - **Ảnh tĩnh (Product Stills)**: Ảnh chất lượng cao ghép sản phẩm thật vào bối cảnh sinh hoạt/lifestyle thực tế, bảo toàn 100% chi tiết packshot gốc.
  - **Video ngắn (30–60s)**: Video gồm 4–8 phân cảnh liền mạch (seamless continuity) về bối cảnh, nhân vật và sản phẩm.
  - **Kịch bản & Caption**: Đoạn mở đầu thu hút (Hook), nội dung thuyết phục, lời kêu gọi hành động (CTA), danh sách hashtag tối ưu.
  - **Affiliate Package**: Link affiliate tương ứng (TikTok Shop, Shopee, Accesstrade/Ecomobi) kèm Sub-ID để theo dõi chuyển đổi.

---

## 2. Kế hoạch triển khai & Giải pháp tối ưu (Implementation Plan)

### Bước 1: Tiền xử lý & Nghiên cứu bối cảnh (Context & Reference Preparation)
- **Tối ưu hóa**: Không để AI tự tưởng tượng bối cảnh từ đầu (dễ bị ảo giác). Tận dụng bối cảnh từ các quảng cáo thực tế đã được sàng lọc hoặc bối cảnh sinh hoạt chuẩn của đối tượng mục tiêu.
- **Cơ chế**: Lọc trùng lặp ảnh tham khảo bằng perceptual hash (pHash); AI Vision sàng lọc góc máy phù hợp để thay thế (swap) sản phẩm.

### Bước 2: Tạo Brief & Kịch bản phân cảnh (Storyboard Scripting)
- **Tối ưu hóa**: Chuẩn hóa kịch bản cho video 30–60s theo công thức bán hàng:
  - `0–3s`: Hook gây chú ý thị giác hoặc vấn đề thường gặp.
  - `3–15s`: Trải nghiệm sản phẩm thực tế và công năng cốt lõi.
  - `15–30s (đến 60s)`: Đi sâu vào chi tiết, chứng minh hiệu quả, so sánh hoặc hướng dẫn sử dụng.
  - `Phân cảnh cuối`: Kêu gọi bấm vào link / giỏ hàng (CTA).
- **Cấu trúc kỹ thuật**: Kịch bản được chia nhỏ thành các scene từ 5–8 giây, có mô tả chi tiết trạng thái camera, chuyển động và vị trí sản phẩm.

### Bước 3: Sinh Ảnh & Video liền mạch (Visual Continuity & Fidelity)
- **Tối ưu độ trung thực sản phẩm (Product Fidelity)**: Sử dụng mô hình sinh ảnh nạp trực tiếp ảnh packshot gốc để thay thế/ghép vào khung hình, tránh hiện tượng AI vẽ lại làm biến dạng nhãn hiệu.
- **Tối ưu tính liền mạch video (Video Continuity)**:
  - Scene 1 sinh từ ảnh tĩnh chuẩn sản phẩm.
  - Từ Scene 2 trở đi: Trích xuất frame cuối cùng của clip trước (qua FFmpeg) làm frame mồi (first-frame conditioning) cho clip tiếp theo. Đảm bảo nhân vật, quần áo, góc phòng và sản phẩm không bị thay đổi đột ngột giữa các cảnh.
  - Ghép nối các phân đoạn clip thành video hoàn chỉnh bằng FFmpeg.
- **Tự động thẩm định (Automated Quality Check)**: AI chấm điểm độ nhận diện sản phẩm trong video; nếu sản phẩm bị mờ nhạt hoặc biến dạng, tự động yêu cầu sinh lại phân cảnh đó.

### Bước 4: Kiểm duyệt tinh gọn & Đóng gói (Human Review & Export)
- Giao diện trực quan cho người duyệt kiểm tra trong vòng dưới 1 phút:
  - Xem video hoàn chỉnh, kiểm tra kịch bản và caption.
  - Một nút bấm để: Duyệt (Approve), Yêu cầu sinh lại phân cảnh lỗi (Regenerate scene), hoặc Chỉnh sửa nhanh văn bản.
- Sau khi duyệt, hệ thống đóng gói đầy đủ video, ảnh thumbnail, caption và link affiliate để sẵn sàng đăng tải.

---

## 3. Lộ trình phát triển tiếp theo

1. **Hiện tại**: Tập trung hoàn thiện ổn định chất lượng video 30–60s, đảm bảo tính nhất quán của video và hình ảnh sản phẩm chuẩn xác.
2. **Giai đoạn tiếp theo**:
   - Thử nghiệm mở rộng độ dài video (>60s) cho các sản phẩm cần review chuyên sâu (review đồ gia dụng, đồ công nghệ).
   - Tối ưu hóa luồng lên lịch đăng và đồng bộ dữ liệu chuyển đổi từ các sàn thương mại điện tử.
