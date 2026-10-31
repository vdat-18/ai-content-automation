# AI Content Automation for Affiliate Marketing (Autonomous Architecture)

Hệ thống tự động hóa sản xuất nội dung video ngắn (30–60s) phục vụ tiếp thị liên kết (Affiliate Marketing) trên các nền tảng video ngắn (TikTok Shop, Shopee Video, Facebook Reels). 

Định hướng vận hành: **Tự động hóa 1-Click (Autonomous Flow)** — Người dùng chỉ cần dán link sản phẩm; toàn bộ quá trình bóc tách dữ liệu sản phẩm và media gốc, đối chiếu SecondBrain, tự chọn bối cảnh tham khảo (references), viết kịch bản và sinh video 30–60s liền mạch đều do Agent tự động thực hiện.

---

## 1. Luồng vận hành tổng thể (End-to-End Workflow)

```text
[Dán Link Sản Phẩm (Shopee / TikTok Shop) + Link Affiliate]
                            ↓
               [BƯỚC 1: PRODUCT INTAKE AGENT]
  - Tự động cào toàn bộ thông tin sản phẩm: Tiêu đề, thông số, mô tả chi tiết, phân loại
  - Tự động cào toàn bộ media: Bộ ảnh gốc đa góc độ (packshot, cận cảnh chất liệu, chi tiết)
  - LLM trích xuất: USP, tính năng nổi bật, kịch bản sử dụng thực tế
                            ↓
       [BƯỚC 2: SECONDBRAIN & AUTO-REFERENCE MATCHING]
  - Nạp Creative Playbook từ SecondBrain: Rule Hook 3s, từ cấm nền tảng, góc quay
  - Agent tự quét kho References: tự chọn 1-2 bối cảnh phù hợp nhất (không cần chọn tay)
                            ↓
         [BƯỚC 3: CREATIVE ENGINE & MEDIA GENERATION]
  - BAML Orchestrator: Viết kịch bản bán hàng 30–60s (Hook -> Demo -> CTA)
  - Managed Media Runtime: Ghép sản phẩm thật vào bối cảnh + nối các cảnh qua FFmpeg (Frame Chaining)
  - Product Fidelity Check: Tự động kiểm tra độ nét và bảo toàn logo/chi tiết sản phẩm
                            ↓
                    [GÓI XUẤT BẢN HOÀN CHỈNH]
  - File Video MP4 30–60s hoàn chỉnh
  - Caption + Hashtag tối ưu SEO
  - Link Affiliate sẵn sàng gắn giỏ hàng
```

---

## 2. Chi tiết các thành phần cốt lõi

### A. Product Intake: Đọc toàn bộ thông tin & Media sản phẩm
* **Không cần nhập liệu thủ công**: Hệ thống nhận link URL từ sàn (Shopee / TikTok Shop).
* **Bóc tách toàn bộ thông tin chi tiết**: Tiêu đề sản phẩm, bảng thông số kỹ thuật (specs), mô tả công dụng, cách dùng và các phân loại hàng.
* **Thu thập bộ Media gốc (Product Truth)**:
  * Tải toàn bộ ảnh có độ phân giải cao nhất của nhà bán hàng: ảnh nền trắng/packshot, ảnh cận cảnh chất liệu, ảnh chụp các góc độ khác nhau.
  * Đóng gói thành bộ ảnh tham chiếu đa chiều (Multi-angle packet) làm dữ liệu mồi chuẩn cho AI sinh hình ảnh.

### B. SecondBrain (Cẩm nang bí kíp Affiliate)
SecondBrain đóng vai trò là kho tri thức (Knowledge Base) định hướng cho các Agent sáng tạo:
* **Bộ quy tắc Hook (0–3s đầu)**: Danh sách các cấu trúc mở đầu giật tít, khơi gợi trí tò mò hoặc đánh vào nỗi đau người tiêu dùng.
* **Bộ quy tắc tuân thủ (Compliance & Safe Words)**: Danh mục từ ngữ bị cấm hoặc hạn chế trên TikTok Shop / Shopee (tránh cam kết 100%, trị dứt điểm, vĩnh viễn... để không bị bóp tương tác hoặc cấm giỏ hàng).
* **Quy chuẩn thị giác (Visual Style Rules)**: Bối cảnh đời sống Việt Nam chân thật, góc cầm sản phẩm 45 độ, ánh sáng rõ mặt sản phẩm, nhãn mác luôn hướng về camera.
* **Bài học tích lũy (Feedback Loop)**: Ghi nhận phong cách video nào tạo ra tương tác cao để các lần sau Agent tự ưu tiên áp dụng.

### C. Tự động chọn bối cảnh tham khảo (Auto-Reference Matching)
* Tận dụng kho dữ liệu quảng cáo xu hướng đã cào (`research_crawler`).
* **Agent tự làm hoàn toàn**:
  * Dựa trên danh mục sản phẩm (ví dụ: Đồ gia dụng phòng bếp, Mỹ phẩm dưỡng da, Thời trang công sở).
  * Agent tự lọc và xếp hạng (Screening & Shortlist) các mẫu video/ảnh có bối cảnh đẹp, ánh sáng tốt và góc máy thuận lợi để ghép sản phẩm vào.
  * Người dùng không phải tìm kiếm hay tích chọn thủ công từng tư liệu tham khảo.

### D. Sinh Video ngắn liền mạch (30–60s Video Continuity)
* **Kịch bản phân cảnh chuẩn bán hàng**:
  * `0–3s (Hook)`: Thị giác mạnh hoặc tình huống gây tò mò, giữ chân người xem dừng lại.
  * `3–15s (Experience)`: Trải nghiệm sản phẩm thực tế tận tay (texture, cách sử dụng).
  * `15–30s+ (Value & Proof)`: Phân tích ưu điểm nổi trội từ thông số và công năng sản phẩm.
  * `Cảnh cuối (CTA)`: Lời kêu gọi hành động rõ ràng hướng dẫn bấm vào giỏ hàng vàng/link bên dưới.
* **Kỹ thuật Video Continuity**:
  * Trích xuất frame cuối của cảnh trước (bằng FFmpeg) làm frame mồi (first-frame) cho cảnh tiếp theo (Frame Chaining).
  * Đảm bảo cùng một người mẫu, cùng trang phục, cùng bối cảnh phòng và giữ nguyên hình dáng sản phẩm trong suốt 30–60s.

---

## 3. Lộ trình triển khai R&D (Roadmap)

1. **Giai đoạn 1 (Core Prototype)**: 
   - Crawler lấy toàn bộ thông tin sản phẩm (mô tả, thông số) và bộ media ảnh gốc từ Shopee.
   - LLM trích xuất USP & sinh 3 mẫu kịch bản Hook.
   - Ráp nối pipeline sinh video ngắn 30s với kỹ thuật Frame Chaining và kiểm định chất lượng (VLM).
2. **Giai đoạn 2 (Scale & Integration)**: 
   - Auto-Reference Matching hoàn chỉnh với kho video mẫu.
   - Tích hợp SecondBrain hai chiều (vừa đọc quy tắc vừa ghi nhận kết quả).
   - Mở rộng crawler cho TikTok Shop.
3. **Giai đoạn 3 (Automation & Optimization)**: 
   - Mở rộng thời lượng video lên 60s.
   - Kết nối công cụ Product Hunter (Kalodata/FastMoss) gợi ý sản phẩm trending.
   - Auto-publish API lên TikTok / Shopee.
