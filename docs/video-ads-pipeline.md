# Thiết kế: từ brief đến video ads, ảnh làm mỏ neo

Trạng thái: đã triển khai (xem README). Tài liệu giữ làm thiết kế gốc; vài chi tiết đã đổi: có người mẫu từ ảnh người dùng, giọng đọc, keyframe cắt 9:16, kịch bản được duyệt trước khi tạo ảnh. Mục tiêu: video ads ngắn ghép từ nhiều clip, trong đó **sản phẩm và bối cảnh giống nhau ở mọi clip** và giống sản phẩm thật.

## 1. Vì sao ảnh phải đi trước video

Model video chỉ tạo được clip ngắn (vài giây) và mỗi lần tạo là một lần "bịa" lại. Nếu chỉ đưa chữ, sản phẩm đổi màu, đổi hình, đổi chữ trên nhãn, bối cảnh đổi giữa các clip. Cách chữa: **mọi clip bắt đầu từ một ảnh keyframe đã được kiểm duyệt** (ảnh to video), và mọi keyframe lại được tạo từ **ảnh sản phẩm thật** cộng **ảnh bối cảnh tham chiếu**. Ảnh rẻ hơn video rất nhiều nên sai ở ảnh thì sửa ở ảnh, không đốt tiền ở video.

## 2. Luồng tổng thể

```
sản phẩm + ảnh thật + thông tin + ảnh tham chiếu + ý tưởng người dùng + quy tắc SecondBrain
  → [1] Concept + storyboard (agent, một lần gọi)
  → [2] Keyframe chủ (master): sản phẩm đặt vào bối cảnh tham chiếu         ← người xem và duyệt
  → [3] Keyframe các shot còn lại, sinh từ keyframe chủ + ảnh sản phẩm thật
  → [4] Kiểm tra tự động từng keyframe (đúng sản phẩm, đúng bối cảnh), sinh lại nếu sai
  → [5] Mỗi keyframe → một clip video ngắn (ảnh to video)
  → [6] Ghép clip + chữ + giọng đọc thành một video
```

Mỗi bước lưu kết quả để chạy lại riêng từng bước.

## 3. Brief đọc những gì (trả lời câu hỏi của bạn)

Đúng, và thêm hai thứ:

| Đầu vào | Dùng để |
|---|---|
| Thông tin sản phẩm (tên, giá, số bán, đánh giá, thông số, mô tả) | Góc bán, chi tiết đúng sự thật, không bịa tính năng |
| Ảnh sản phẩm thật | Màu, hình dáng, chi tiết; cũng là ảnh gốc cho model tạo ảnh |
| Ảnh tham chiếu và mô tả của Gemini | Bối cảnh để mượn |
| Ý tưởng của người dùng (nếu có) | Hướng sáng tạo, agent làm giàu |
| **Quy tắc SecondBrain (mới)** | Quy tắc hook mở đầu, từ cấm theo TikTok Shop, quy chuẩn thị giác, bài học đã tích lũy |
| **Loại sản phẩm (mới)** | Cách quay hợp loại sản phẩm (đồ gia dụng khác mỹ phẩm) |

## 4. Một sản phẩm chọn mấy ảnh tham chiếu

Khuyến nghị: **mỗi video một ảnh tham chiếu chính, mỗi sản phẩm nhiều video thì mỗi video một ảnh khác nhau.**

- **Trong một video, dùng một bối cảnh.** Các clip phải cùng một căn phòng, cùng ánh sáng thì ghép lại mới ra một video liền mạch. Nhiều ảnh tham chiếu khác nhau trong một video làm bối cảnh nhảy cóc, và model ảnh nhận được ít ảnh đầu vào mỗi lần nên không thể nhồi nhiều.
- **Giữa các video của cùng một sản phẩm, đổi ảnh tham chiếu.** Đó là nguồn đa dạng cho N ads (kết hợp với việc đổi góc bán, đối tượng, câu móc).
- **Ngoại lệ có kiểm soát:** cho phép một ảnh tham chiếu phụ cho một hai shot cần bối cảnh khác (ví dụ shot cận cảnh sử dụng), nhưng mặc định là một.

Cách chọn ảnh chính cho mỗi video: lấy ứng viên khác nhau nhiều nhất (như bây giờ), agent chọn ảnh hợp nhất với sản phẩm và ý tưởng; các video sau của cùng sản phẩm loại ảnh đã dùng.

## 5. Brief trở thành concept và storyboard

Một brief mới gồm:

- **Concept:** góc bán, đối tượng, câu móc, tông giọng, ảnh tham chiếu chính đã chọn, mô tả "thế giới" của video (bối cảnh, ánh sáng, màu).
- **Storyboard 4 đến 6 shot**, mỗi shot gồm: vai trò (hook, vấn đề, demo, lợi ích, kêu gọi mua), mô tả hình, **prompt keyframe**, **prompt chuyển động** cho clip (máy quay, hành động ngắn), thời lượng, chữ trên màn hình, câu thoại.

Giữ nguyên nguyên tắc hiện tại: agent làm hết một lần, người dùng có thể thêm ý tưởng và sửa.

## 6. Giữ nhất quán sản phẩm và bối cảnh

1. **Keyframe chủ trước.** Tạo một ảnh đặt sản phẩm thật vào bối cảnh tham chiếu (model ảnh nhận ảnh sản phẩm và ảnh bối cảnh làm đầu vào). Người dùng duyệt ảnh này trước khi tạo tiếp: ảnh này đúng thì cả video đúng.
2. **Các shot còn lại sinh từ keyframe chủ**, kèm lại ảnh sản phẩm thật ở mọi lần gọi, chỉ đổi góc máy và hành động.
3. **Kiểm tra tự động bằng Gemini** sau mỗi keyframe: so với ảnh sản phẩm thật (màu, hình dáng, số lượng, chữ trên nhãn) và với keyframe chủ (cùng bối cảnh, cùng ánh sáng). Sai thì sinh lại, tối đa vài lần rồi báo người dùng.
4. **Tránh khuôn mặt người** ở bản đầu: shot chỉ có sản phẩm, bàn tay, không gian. Giữ nhất quán một nhân vật qua nhiều clip là vấn đề khó, để sau.
5. **Clip:** mỗi clip tạo từ đúng một keyframe (ảnh to video). Nếu model video hỗ trợ khung đầu và khung cuối thì dùng keyframe shot sau làm khung cuối để chuyển cảnh mượt.

## 7. Điểm duyệt của người dùng (tiết kiệm tiền)

1. Duyệt storyboard (chữ, rẻ).
2. **Duyệt keyframe chủ** (ảnh, rẻ). Đây là cổng quan trọng nhất.
3. Các keyframe còn lại: tự kiểm tra, người dùng chỉ xem lướt và xóa shot xấu.
4. Chỉ sau đó mới tạo clip (đắt).

## 8. Điều cần biết trước khi code

- **Model ảnh và model video bạn có qua 9Router** (tên, khả năng). Yêu cầu tối thiểu: model ảnh nhận **nhiều ảnh đầu vào** (ảnh sản phẩm và ảnh bối cảnh) để chỉnh sửa; model video hỗ trợ **ảnh to video**.
- Tỷ lệ khung hình (9:16 cho TikTok), độ dài video, số shot, thời lượng mỗi clip tối đa của model.
- Giọng đọc và nhạc: làm ở bước ghép, chưa nằm trong giai đoạn ảnh.

## 9. Thứ tự làm đề xuất

1. Đổi brief thành concept và storyboard (một lần gọi), lưu nhiều shot.
2. Tạo keyframe chủ (cần model ảnh) và trang duyệt.
3. Tạo keyframe các shot và kiểm tra tự động.
4. Tạo clip và ghép video.
5. Nhiều video cho một sản phẩm (kế hoạch N content, đã mô tả trong tài liệu kho ảnh).
