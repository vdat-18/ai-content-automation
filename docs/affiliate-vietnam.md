# Affiliate content cho thị trường Việt Nam

Tóm tắt hướng đi (nghiên cứu ngày 31/10/2026). Báo cáo đầy đủ nằm ngoài repo. Nhiều số liệu và
số điều luật lấy từ blog, báo chí và tóm tắt của văn phòng luật, chưa đối chiếu với trang
chính thức. Đây không phải tư vấn pháp lý hay thuế.

## Quyết định

- Không làm máy đăng video tự động. Pipeline hiện có đóng vai trò chọn sản phẩm, tạo nội dung
  bám sát sản phẩm và kiểm tra tuân thủ. Người thật duyệt và đăng từ tài khoản chính chủ.
- Lộ trình: A (người đăng tay) → B (lịch đăng sau khi duyệt) → không làm C (tự động hoàn toàn).
- Kênh: TikTok/TikTok Shop, rồi Shopee Video (video gốc, không watermark), rồi Facebook Reels
  gắn thẻ Shopee. YouTube Shorts, Zalo, Instagram, Lazada để sau.
- Affiliate: mạng Accesstrade và Ecomobi (có API tạo link, ngưỡng rút thấp), song song TikTok
  Shop Affiliate và Shopee Affiliate.

## Kinh tế (ước tính, chưa đo)

| Mục | Giá trị |
|---|---|
| Chi phí mỗi video đã đăng | khoảng 45.000-138.000 VND |
| Hoa hồng ròng mỗi đơn | khoảng 16.000 VND |
| Hòa vốn | khoảng 9.400-28.800 lượt xem mỗi video |

Cần đo bằng pilot 30 video: tỷ lệ click, tỷ lệ ra đơn, hao hụt đơn COD.

## Tuân thủ (checklist ngắn)

- Gắn nhãn nội dung AI nếu mô phỏng người hoặc sự kiện thật (Luật AI, Nghị định 142/2026).
- Nói rõ đây là quảng cáo; KOL/KOC chịu trách nhiệm với nội dung sai (Luật Quảng cáo sửa đổi,
  hiệu lực 1/1/2026).
- Không nêu công dụng sản phẩm chưa có giấy tờ; với thực phẩm chức năng, mỹ phẩm, sản phẩm sức
  khỏe cần kiểm tra giấy chứng nhận.
- Không bịa đánh giá hay trải nghiệm; video phải khác nhau thật sự, không dùng lại video của
  người khác.
- Thuế thu nhập từ affiliate: hỏi kế toán, các nguồn đang mâu thuẫn.

## Kỹ thuật

- API đăng TikTok không gắn được sản phẩm Shop hay link affiliate; bước gắn sản phẩm làm tay
  trong app. Chưa qua audit chỉ đăng riêng tư. Chưa xác nhận API có dùng được ở Việt Nam.
- Kiến trúc đề xuất: adapter mock trước, dịch vụ link affiliate gắn sub-ID cho mỗi bài, hàng
  đợi người duyệt, báo cáo chuyển đổi hằng ngày.

## Việc cần xác minh trước

1. Điều khoản chính thức của TikTok Shop VN và Shopee Affiliate (tự động hóa, AI, nhãn AI,
   ngưỡng follower, bảng hoa hồng).
2. Văn bản luật gốc (Luật 75/2025, Luật AI, Nghị định 142/2026).
3. Chế độ thuế với kế toán.
4. API tại Việt Nam: TikTok Content Posting, Shopee Affiliate, Meta App Review.
5. Số liệu phễu bằng pilot.
