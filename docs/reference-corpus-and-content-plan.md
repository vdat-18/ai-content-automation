# Thiết kế: kho ảnh tham chiếu và kế hoạch nhiều content cho một sản phẩm

Trạng thái: giai đoạn 1 (kho ảnh tự động) và giai đoạn 2 (chống trùng bằng embedding) đã làm xong; giai đoạn 3 còn là đề xuất. Giai đoạn 2 dùng DINOv3 ViT-S/16 chạy ONNX trên CPU (đổi được bằng `AIC_EMBEDDING_MODEL`), ngưỡng cosine 0,90 và dHash cách nhau tối đa 4 bit, chỉnh theo dữ liệu thật. Mục tiêu: một sản phẩm tạo được nhiều ads/content **khác nhau rõ rệt**, từ kho ảnh tham chiếu có thể lên tới hàng nghìn ảnh, không cần người duyệt từng ảnh.

## 1. Vấn đề của bản hiện tại

| Điểm | Hiện tại | Hệ quả khi kho lớn |
|---|---|---|
| Duyệt | Người duyệt tay từng ảnh sau Gemini | Không làm nổi với hàng trăm ảnh |
| Chọn ảnh cho brief | 8 ảnh đã duyệt mới nhất | Không phải ảnh tốt nhất, không hợp sản phẩm, không đa dạng |
| Số content | Một brief cho mỗi sản phẩm | Muốn nhiều ads thì phải bấm lại, và các brief dễ giống nhau |
| Chống trùng | Chỉ theo URL | Cùng một ảnh repin bằng link khác vẫn lọt, tốn lượt Gemini |
| Chất lượng ảnh | Chỉ có đạt/không đạt | Không xếp hạng được |

## 2. Nguyên tắc thiết kế

1. **Gemini là cổng duy nhất.** Ảnh qua Gemini thì tự có hiệu lực ("live"); người dùng chỉ **xóa** ảnh trên frontend. Ảnh bị xóa được nhớ lại để lần crawl sau không nạp lại.
2. **Rẻ trước, đắt sau.** Chống trùng bằng embedding chạy trước khi gọi Gemini để không trả tiền cho ảnh giống nhau.
3. **Chọn ảnh bằng toán, viết brief bằng LLM.** Việc chọn ảnh tham chiếu (liên quan, đa dạng, chưa dùng) làm bằng thuật toán trên embedding; LLM chỉ nhìn một nhóm nhỏ đã được chọn.
4. **Lập kế hoạch trước, viết sau.** Với N content của một sản phẩm, một bước lập kế hoạch bảo đảm N content khác nhau về góc bán, đối tượng và bối cảnh trước khi viết từng brief.

## 3. Embedding: dùng loại nào

Khuyến nghị: **mô hình CLIP chạy cục bộ** (ảnh và chữ cùng một không gian vector, không cần key, không dính hạn mức 429).

| Phương án | Ưu | Nhược |
|---|---|---|
| A. CLIP cục bộ (thư viện `fastembed`, ONNX, CPU) | Miễn phí, nhanh, ảnh và chữ cùng không gian nên tìm ảnh theo ý tưởng được; không phụ thuộc mạng | Thêm một thư viện và mô hình khoảng vài trăm MB vào image Docker; chữ tiếng Việt kém, cần dịch ý tưởng sang tiếng Anh trước khi nhúng |
| B. API embedding đa phương thức (qua 9Router nếu có) | Không thêm gánh nặng cho image, hiểu chữ Việt tốt hơn | Tốn tiền, có thể dính hạn mức, cần xác nhận 9Router có endpoint này |
| C. Nhúng mô tả chữ do Gemini viết | Dùng được với bất kỳ endpoint OpenAI-compatible | Không bắt được ảnh trùng về mặt hình ảnh, mất thông tin thị giác |

Cần kiểm chứng trước khi code: tên mô hình CLIP mà `fastembed` đang hỗ trợ, thời gian nhúng thực tế trên máy của bạn, và ngưỡng trùng phù hợp (dự kiến cosine từ 0,92 đến 0,95, chỉnh bằng dữ liệu thật).

Embedding dùng cho 3 việc:
1. **Chống trùng:** ảnh mới có cosine với ảnh đã có vượt ngưỡng thì bỏ trước khi gọi Gemini.
2. **Độ liên quan:** xếp ảnh theo độ gần với ý tưởng của người dùng và mô tả sản phẩm.
3. **Độ đa dạng:** tránh chọn nhiều ảnh gần nhau cho các content khác nhau.

Lưu vector: với vài nghìn ảnh mỗi loại, lưu mảng số trong cột và tính cosine ngay trong Python là đủ. Chỉ chuyển sang `pgvector` khi kho lớn hơn nhiều (cần đổi image Postgres, không làm bây giờ).

## 4. Luồng crawl → kho ảnh

```
crawl Pinterest
  → loại link trùng (đã có)
  → nhúng embedding, loại ảnh gần giống ảnh đã có hoặc đã bị xóa
  → Gemini chấm: đạt/không đạt + một đoạn mô tả ảnh (bối cảnh, ánh sáng, phong cách, màu, chỗ đặt sản phẩm)
  → đạt: trạng thái live (hiện trên frontend), không đạt: rejected (ẩn, vẫn nhớ để khỏi chấm lại)
```

Frontend: bỏ nút Duyệt/Loại, chỉ còn **Xóa** (đánh dấu xóa mềm). Không có điểm chất lượng; khi chọn ảnh cho brief, hệ thống lấy các ảnh khác nhau nhiều nhất theo vector embedding.

## 5. Từ một sản phẩm đến N content

Đầu vào: sản phẩm, N (số content muốn), ý tưởng người dùng (không bắt buộc, có thể nhiều ý).

1. **Rút gọn ứng viên.** Từ kho của loại sản phẩm, lấy khoảng 3N ảnh bằng điểm gộp:
   `điểm = a·liên quan(ý tưởng, sản phẩm) + b·chất lượng − c·đã dùng cho sản phẩm này`
   rồi chọn lần lượt kiểu **MMR** (mỗi ảnh được chọn làm giảm điểm các ảnh gần nó) để ứng viên đã đa dạng.
2. **Lập kế hoạch (một lần gọi LLM, chỉ chữ).** Nhận thông tin sản phẩm, ý tưởng của người dùng và mô tả ngắn từng ứng viên. Trả về N kế hoạch: góc bán, đối tượng, câu móc (hook), ảnh chính và ảnh phụ, cách biến tấu bối cảnh. Ràng buộc: không hai kế hoạch trùng góc bán hoặc trùng ảnh chính.
3. **Viết brief (N lần gọi song song).** Mỗi kế hoạch được viết thành brief đầy đủ, lần này LLM nhìn ảnh sản phẩm thật (tự chọn tối đa 5 ảnh để sinh ảnh) và đọc mô tả chữ của ảnh tham chiếu để chọn đúng 1 bối cảnh.
4. **Ghi nhận đã dùng.** Mỗi ảnh tham chiếu đã dùng cho sản phẩm nào được lưu lại, lần sau ưu tiên ảnh chưa dùng. Dùng lại giữa các sản phẩm khác nhau thì được.

Ý tưởng người dùng: nếu có nhiều ý thì mỗi ý neo một kế hoạch; nếu ít hơn N thì các kế hoạch còn lại agent tự chọn hướng, nhưng vẫn khác các ý đã có.

## 6. Thay đổi dữ liệu

- `product_briefs`: khóa chính đổi từ `product_id` thành `brief_id`, thêm `product_id`, `batch_id`, `plan` (JSON kế hoạch), `status`.
- `reference_uses(product_id, image_id, brief_id)`.
- `reference_images`: thêm `embedding`, `quality_score`, `removed_at`; bỏ trạng thái `approved`.
- Frontend: trang Briefs cho phép nhập N, bấm "Tạo N content", xem danh sách brief của sản phẩm.

## 7. Thứ tự làm đề xuất

| Giai đoạn | Nội dung | Phụ thuộc |
|---|---|---|
| 1. Kho ảnh tự động | Ảnh qua Gemini là live; chỉ xóa; điểm chất lượng; frontend xếp theo điểm | Không |
| 2. Embedding | Nhúng ảnh, chống trùng trước Gemini, lưu vector | Quyết định phương án A/B/C |
| 3. Kế hoạch nhiều content | Rút gọn bằng MMR, lập kế hoạch, N brief, ghi nhận đã dùng, UI | Giai đoạn 1 và 2 |

Mỗi giai đoạn dùng được độc lập. Giai đoạn 1 nhỏ nhất và giải quyết ngay chuyện duyệt tay.

## 8. Rủi ro và cách giảm

- **Gemini nhận nhầm ảnh rác vào kho** khi không còn người duyệt: ngưỡng điểm chất lượng tối thiểu, xóa nhanh trên giao diện, kho rejected vẫn xem được để chỉnh prompt.
- **Ngưỡng trùng sai:** chỉnh bằng dữ liệu thật; lưu cả ảnh bị loại do trùng để kiểm tra lại.
- **Bản quyền ảnh Pinterest:** vẫn chỉ dùng làm tham chiếu bối cảnh, brief không được sao chép nguyên ảnh, logo hay chữ (đã có trong prompt).
- **Chi phí LLM nhân với N:** lập kế hoạch một lần, chỉ gửi ảnh của đúng kế hoạch cho bước viết; giới hạn N tối đa trên giao diện.
