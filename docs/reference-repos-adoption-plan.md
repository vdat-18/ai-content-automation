# Kế hoạch áp dụng ý tưởng từ 3 repo tham khảo

Nguồn tham khảo (đã clone ở `D:\video-repos\`, chỉ để đọc, không chạy):

- `nguyentatkiem-ai-video-studio` (MIT, yêu cầu giữ ghi công tác giả): phần mềm dựng video dùng Claude CLI.
- `ai-video-editor` (MIT, license model hỗn hợp): Timeline Studio, kèm skill `edit-timeline-studio`.
- `zecloud-ai-video-studio`: app Azure/OneDrive. Không thấy file LICENSE ở thư mục gốc nên **chỉ học ý tưởng, không copy code**.

Cả 3 repo dựng video từ footage có sẵn, không repo nào sinh footage từ ảnh sản phẩm và mặt người thật như dự án này. Vì vậy chỉ lấy **mẫu thiết kế**, không lấy engine hay template.

## Quy trình duyệt

Mỗi mục có trạng thái. Chỉ làm mục có trạng thái `Đã duyệt`. Làm xong ghi `Xong` kèm commit.

Trạng thái: `Chờ duyệt` · `Đã duyệt` · `Bỏ` · `Xong`

---

## 1. Bền trạng thái và tự thử lại khi provider bận

**Trạng thái:** Xong phần code và test (commit c9919f1). Chưa thử với provider thật vì sẽ tốn tiền clip; chờ người dùng cho phép chạy video · **Công sức:** vừa · **Nguồn:** nguyentatkiem (autopilot, queue), ai-video-editor (remote-video-generation)

**Đã làm:** `pipeline.py` nhận ra lỗi "provider bận" (`is_busy_error` trong `clips.py`), chờ 60 giây rồi gửi lại từng clip một, tối đa 15 lần mỗi shot, hết lượt thì dừng với thông báo rõ. Lỗi khác vẫn dừng ngay.

**Không làm bảng lưu trạng thái riêng:** pipeline đã chạy tiếp được vì mỗi bước kiểm tra dữ liệu có sẵn trong DB (ảnh đã duyệt, clip đã xong) và bỏ qua phần đã làm. Chỉ có chỉ báo "đang chạy" là nằm trong bộ nhớ nên mất khi restart server; chạy lại thì tự tiếp tục từ chỗ dở.

**Vấn đề hiện tại.** Provider video (`api.vilao.ai`) hay trả "hệ thống đang xử lý lượng lớn yêu cầu". Pipeline gửi cả 3 clip cùng lúc, cả 3 lỗi và cả pipeline dừng. Trạng thái run nằm trong bộ nhớ nên restart server là mất.

**Làm gì.**
- Gửi clip lần lượt, không gửi dồn.
- Nếu provider báo bận thì chờ rồi thử lại (cách nhau vài chục giây, tối đa vài lần). Lỗi khác thì dừng như cũ.
- Lưu trạng thái từng bước (brief, ảnh, clip, giọng, ghép) vào DB để chạy lại thì bỏ qua bước đã xong.
- Trạng thái job thật: đang chờ, đang chạy, xong, lỗi. Chỉ hiện % khi provider trả tiến độ thật.
- Tải byte clip về lưu ngay, vì URL của provider có thể hết hạn.

**Tác dụng và lý do.** Video không còn chết giữa chừng chỉ vì provider bận. Không tốn lại credit của bước đã xong. Đây là việc đang chặn video 30s.

**Rủi ro.** Retry quá tay có thể tốn credit nếu provider tính tiền cả lần lỗi. Phải giới hạn số lần và ghi log rõ.

---

## 2. Phụ đề chạy theo từng chữ

**Trạng thái:** Xong phần code và test · **Công sức:** vừa · **Nguồn:** nguyentatkiem (`topic_video`)

**Đã làm (khác kế hoạch một chỗ).** Không dùng Whisper: giọng đọc được tạo theo từng shot nên đã biết sẵn mỗi shot nói trong bao lâu; chữ được chia theo số ký tự (cộng thêm thời gian nghỉ sau dấu phẩy/chấm) trong khoảng đó. Đỡ một thư viện nặng và không có lỗi nghe sai tiếng Việt. Mỗi dòng tối đa 4 từ, từ có chữ số (giá, số lượng) tô vàng. Bật bằng ô "Show the on-screen text" ở bước Finish; giọng tải lên từ file không có mốc nên dùng chữ on-screen cũ. Đã chạy thử trong Docker: chữ hiện đúng lúc và tắt khi hết lời. Nếu sau này lệch nhiều, nâng cấp bằng Whisper được.

**Vấn đề hiện tại.** Caption là một khối `drawtext` hiện suốt cả shot (`clips.py`), không chạy theo lời đọc.

**Làm gì.**
- Có giọng đọc xong thì nghe lại bằng Whisper để lấy mốc thời gian từng chữ.
- Đối chiếu với **đúng chữ trong kịch bản** (không dùng chữ Whisper nghe nhầm), chữ nào không khớp thì chia theo số ký tự giữa hai chữ khớp.
- Mỗi dòng tối đa 4 từ, tô nổi 1–2 từ khoá.
- Xuất file ASS rồi ffmpeg đốt vào video.

**Tác dụng và lý do.** Video bán hàng TikTok gần như luôn dùng kiểu phụ đề nhảy theo chữ vì giữ người xem và xem được khi tắt tiếng. Đây là chỗ thấy khác biệt rõ nhất giữa video "AI làm" và video "ra dáng quảng cáo".

**Rủi ro.** Whisper tiếng Việt đôi khi nghe sai, nên bắt buộc dùng chữ kịch bản làm chuẩn. Cần font hỗ trợ dấu tiếng Việt.

---

## 3. QC cho video cuối

**Trạng thái:** Xong phần code và test · **Công sức:** vừa · **Nguồn:** nguyentatkiem (`ai_qc`)

**Đã làm.** Sau khi ghép video, máy đo bằng ffprobe/ffmpeg: kích thước 1080x1920, thời lượng, có âm thanh, độ to (-14 LUFS ±3), đỉnh âm (> -1 dB), im lặng ≥ 2,5 s, hình đứng yên ≥ 6 s, có chữ ở cảnh đầu, chữ on-screen quá 5 từ. Lỗi nặng trừ 25 điểm, nhẹ trừ 10; kết quả lưu trong `video.json` và hiện ở bước Finish (endpoint `/video-check`). **Chưa làm:** kiểm tra chữ tràn vùng an toàn (chữ luôn nằm giữa nên không tràn), nhạc át giọng (không đo riêng được hai luồng, đã có ducking), và đề xuất luật SecondBrain từ lỗi lặp lại (sẽ gộp vào mục 4 cùng vòng phản hồi). Đã đo thử trong Docker trên video giả; chưa chạy trên video thật.

**Vấn đề hiện tại.** Đang QC từng ảnh và từng clip bằng Gemini, nhưng không kiểm tra video đã ghép.

**Làm gì.** Bước máy tự đo (không cần AI):
- 2 giây đầu có chữ hook hoặc không.
- Chữ có tràn ngoài vùng an toàn của TikTok không, caption có quá 5 từ không.
- Có đoạn dài hơn 6 giây không có sự kiện hình không.
- Độ to và true peak của bản cuối (chuẩn -14 LUFS, ≤ -1 dBTP), nhạc có át giọng không, có im lặng giữa chừng không.
- Kiểm tra ffprobe: có audio, đúng kích thước 9:16, đúng thời lượng.

Mỗi lỗi có mức nặng/nhẹ, ra điểm 0–100. Lỗi lặp lại nhiều lần thì đề xuất thành luật SecondBrain.

**Tác dụng và lý do.** Bắt lỗi trước khi người dùng thấy. Cũng là cách để SecondBrain tự học từ lỗi thật của video cuối, không chỉ từ ảnh.

**Rủi ro.** Chỉ đo lỗi kỹ thuật, không chấm thẩm mỹ. Chỉ báo lỗi, chưa tự sửa ở giai đoạn đầu.

---

## 4. Vòng phản hồi sau video

**Trạng thái:** Xong phần code và test. Thêm sau: clip bị AI kiểm tra gắn cờ cũng đề xuất một luật cho kịch bản (người gửi `gemini-qa`, mỗi luật một lần) · **Công sức:** nhỏ–vừa · **Nguồn:** nguyentatkiem (`feedback.mjs`)

**Đã làm (khác bản gốc theo ý người dùng).** Không chấm sao, không ngưỡng 2 lần/25%: ở bước Finish có ô nhận xét tự do, gửi vào SecondBrain thành luật chờ duyệt (loại `brief`, vì luật cho kịch bản mới ảnh hưởng video sau). Kết quả kiểm tra video (mục 3) cũng vào SecondBrain: khi cùng một lỗi (không có hook, chữ quá dài, im lặng) xuất hiện ở từ 2 video, hệ thống đề xuất luật nhãn `video-check`; luật đã có (kể cả đã duyệt hoặc từ chối) không bị mở lại. Lỗi về độ to, đỉnh âm, hình đứng yên không đề xuất vì kịch bản không sửa được. Chưa có AI xem video cuối rồi nhận xét (tốn tiền, chưa được duyệt).

**Làm gì.**
- Sau mỗi video, người dùng chấm 1–5 sao và chọn thẻ lỗi: mở đầu yếu, chữ khó đọc, nhạc to, dài quá, giọng lạ.
- Một thẻ xuất hiện ≥ 2 lần và chiếm ≥ 25% trong 8 phản hồi gần nhất thì mới tạo đề xuất.
- Đề xuất đi vào SecondBrain như một **luật chờ duyệt** (người duyệt, LLM chép lại cho sạch). Không tự áp.

**Tác dụng và lý do.** SecondBrain học từ ý kiến của chính người dùng, đúng ý "agent feedback tự sửa nhưng phải duyệt". Ngưỡng 2 lần/25% chặn việc sửa luật chỉ vì một lần chấm cảm tính.

**Rủi ro.** Cần người dùng chịu chấm. Nên chỉ cần 1 cú bấm thẻ.

---

## 5. Biến thể hook A/B

**Trạng thái:** Xong phần code và test. Bước Finish có mục "Try other opening lines": AI viết 3 hook (câu hỏi, con số, nỗi đau/lợi ích; tối đa 7 từ; loại hook có từ cấm hoặc số không có trong dữ liệu sản phẩm), mỗi hook bấm "Make this video" thì đọc lại giọng và ghép lại từ các clip đã có, lưu ở `videos/<id>/hook_N/`, không sinh clip mới. Không làm cold open. Hook không dùng được khi cảnh đầu là cảnh nói trước camera (lời cố định theo clip). Phần bước 6 (file JSON dựng chỉnh được) chưa làm; mục này chỉ dùng thư mục riêng cho từng hook. Đã chạy dựng video hook trong Docker với giọng giả; đã gọi AI thật một lần với sản phẩm giả: 2 trong 3 hook qua kiểm tra (lần đầu bị cắt cụt vì giới hạn đầu ra 1500 token, đã nâng lên 4000) · **Công sức:** vừa · **Nguồn:** nguyentatkiem (`variants.mjs`)

**Làm gì.**
- LLM viết N hook (mặc định 3), mỗi hook ≤ 7 từ và một góc khác nhau: câu hỏi, con số/tuyên bố, nỗi đau/lợi ích.
- Với mỗi hook, chỉ đổi câu mở đầu (lời + caption) rồi ghép lại, **dùng lại các clip đã sinh**.
- Tuỳ chọn cold open: kéo câu mạnh nhất lên đầu.

**Tác dụng và lý do.** Affiliate cần thử nhiều hook để biết hook nào ra đơn. Làm cách này gần như không tốn credit video. Phụ thuộc mục 6 để ghép lại không phải sinh lại clip.

**Rủi ro.** Đổi lời hook thì giọng đọc shot 1 phải làm lại, tốn một ít TTS. Hook mới phải qua bước kiểm tra compliance như bình thường.

---

## 6. Lưu bản dựng dưới dạng JSON chỉnh được

**Trạng thái:** Chưa làm; mục 5 chạy được không cần mục này (xem ghi chú mục 5). Chỉ làm khi cần đổi thứ tự cảnh hoặc cắt cảnh trên giao diện · **Công sức:** vừa · **Nguồn:** ai-video-editor (timeline là nguồn sự thật)

**Làm gì.** Lưu kèm mỗi video một file mô tả bản dựng: thứ tự shot, mốc cắt, mốc từng chữ, mức nhạc, giọng. Bước Finish đổi giọng, caption, nhạc thì ghép lại từ file này.

**Tác dụng và lý do.** Đổi caption hay nhạc không phải sinh lại clip, không tốn credit, không phải chờ. Là nền cho mục 2 và 5.

**Rủi ro.** Phải giữ file clip gốc trên đĩa. Cần quy ước phiên bản của file.

---

## 7. Giọng đọc theo cụm hơi

**Trạng thái:** Xong phần code và test (cảnh không có clip dẫn: đọc theo cụm, nghỉ 0,28 s sau dấu phẩy và 0,4 s sau câu, cân mỗi đoạn về -16 LUFS, tối đa ±12 dB). Khác kế hoạch: (1) vẫn tăng tốc giọng khi dài hơn cảnh vì độ dài cảnh cố định theo clip đã trả tiền, tốc độ mặc định giữ nguyên; (2) các số nằm trong hằng số của `speech.py`, chưa đưa vào SecondBrain vì luật ở đó là văn bản, chưa có loại voiceover; (3) cảnh nói trước camera (khớp môi) giữ nguyên cách cũ. Sau khi chạy thử thật: cảnh có lời kết thúc sớm bị cắt ngay sau lời (cộng 1,2 s, tối thiểu 4 s mỗi cảnh) để video không có khoảng im lặng dài, và bước kiểm tra đo im lặng trên riêng giọng đọc. Chưa nghe thử với giọng TTS thật · **Công sức:** nhỏ–vừa · **Nguồn:** ai-video-editor (`voiceover-workflow`)

**Làm gì.**
- Chia lời thành cụm ngắn theo dấu phẩy và câu, đọc từng cụm riêng, nghỉ 0,28–0,4 giây giữa các cụm.
- Chốt âm thanh trước, sau đó mới khớp hình theo thời lượng thật của giọng. Không tăng tốc giọng cho vừa độ dài.
- Đo độ to từng đoạn, chênh nhau ≤ 1 LU.
- Đưa các quy tắc này vào SecondBrain (loại voiceover), không hard-code.

**Tác dụng và lý do.** Giọng tiếng Việt bớt đều đều như máy, nhịp tự nhiên hơn.

**Rủi ro.** Nhiều lần gọi TTS hơn nên tốn thời gian hơn một chút.

---

## 8. Trạng thái của từng claim

**Trạng thái:** Xong phần code và test, bản đơn giản: chỉ kiểm số liệu (phần trăm, tiền, số từ 100 trở lên) so với dữ liệu sản phẩm và ý tưởng của người dùng; số không có nguồn hiện thành cảnh báo cho người đọc (cùng chỗ với cảnh báo từ cấm), không tự xoá và không gắn ba nhãn `verified`/`official-claim`/`illustrative`. Số đếm cho phép làm tròn xuống ("hơn 3.000" cho 3.200). Chưa thử với kịch bản AI viết thật · **Công sức:** nhỏ · **Nguồn:** ai-video-editor (promotion-narrative), nguyentatkiem ("không tự bịa số liệu")

**Làm gì.** Mỗi con số hay lời hứa trong script gắn nhãn nguồn: `verified` (có trong dữ liệu sản phẩm: giá, lượt bán, đánh giá), `official-claim` (người bán tự nói), `illustrative` (minh hoạ). Claim không có nguồn thì không cho vào video.

**Tác dụng và lý do.** Tránh nói sai về sản phẩm, bổ sung cho `compliance.py` và luật quảng cáo.

**Rủi ro.** Có thể làm script bớt "bốc" nếu claim bị loại. Đây là đánh đổi cố ý.

---

## 9. Hồ sơ nhịp theo mục tiêu

**Trạng thái:** Hoãn, chờ được phép chạy video thật để thử số liệu · **Công sức:** nhỏ · **Nguồn:** zecloud (`narrativePacingMaximum`)

**Làm gì.** Độ dài tối đa mỗi cảnh theo loại video (ví dụ giới thiệu sản phẩm ≤ 8 giây, ngắn dồn dập ≤ 6 giây). Lưu thành cấu hình trong SecondBrain thay vì hard-code, dùng khi chia shot và viết script.

**Tác dụng và lý do.** Nhịp dựng là thứ người làm nội dung hay muốn chỉnh, nên phải sửa được mà không đụng code.

**Rủi ro.** Số liệu của zecloud là cho video quay thật, cần thử lại cho video AI.

---

## 10. Phân tích một quảng cáo mẫu

**Trạng thái:** Xong phần code và test. Trang AI memory, tab rules có ô "Learn from an example ad": chọn video MP4 (tối đa 100 MB, 3 phút), hệ thống lấy 40 khung, đo điểm cắt bằng ffmpeg, nhờ AI mô tả cấu trúc thành 3–6 luật "brief" chờ duyệt (người gửi `reference-ad`). Video không được lưu. Khác kế hoạch: vị trí chữ do AI nhìn khung hình mô tả, không đo bằng máy. Đã thử lấy khung và đo cắt trên video giả trong Docker; đã gọi AI thật một lần trên video giả hai cảnh: ra 4 luật hợp lý (giới hạn đầu ra nâng lên 4000 token); chưa thử trên quảng cáo thật · **Công sức:** vừa–lớn · **Nguồn:** nguyentatkiem (Tạo style)

**Làm gì.** Người dùng thả một quảng cáo TikTok đang chạy tốt. Hệ thống lấy khoảng 40 khung hình, đo nhịp cắt, vị trí chữ rồi nhờ LLM mô tả cấu trúc: loại hook, vai trò từng shot, nhịp, vị trí caption. Kết quả được **đề xuất thành luật SecondBrain chờ duyệt**.

**Tác dụng và lý do.** Học từ cái đang thắng thay vì đoán. Chỉ học cấu trúc, **không chép nội dung, logo hay lời** của người khác.

**Rủi ro.** LLM chỉ thấy ảnh tĩnh, không thấy chuyển động nên nhịp là ước lượng. Cần cân nhắc bản quyền khi lưu video mẫu.

---

## 11. Duyệt qua điện thoại (Telegram)

**Trạng thái:** Hoãn, người dùng nói chưa cần · **Công sức:** lớn · **Nguồn:** nguyentatkiem (agent Telegram)

**Làm gì.** Bot Telegram gửi ảnh để duyệt, nhận nút Duyệt / Không đạt, báo khi video xong. Dùng long polling nên không cần URL công khai. Ghép nối bằng mã, người lạ bị từ chối, bot không bao giờ chạy lệnh shell.

**Tác dụng và lý do.** Người làm marketing duyệt ngay trên điện thoại, không cần ngồi trước dashboard.

**Rủi ro.** Thêm một kênh và một token cần bảo mật. Nên làm sau cùng.

---

## 12. Sticker giá, mã giảm, nút CTA

**Trạng thái:** Xong phần code và test. Bước Finish có ô chọn "Show price, sales and rating stickers" (mặc định tắt, giống caption): 3 sticker vàng góc trên trái, số lấy từ dữ liệu sản phẩm (giá bán và giá gốc, đã bán, đánh giá). Mỗi sticker hiện ở cảnh mà lời nhắc tới số đó; giá không cảnh nào nhắc thì hiện ở cảnh cuối; thiếu dữ liệu thì không có sticker. Chưa làm mã giảm vì chưa biết dữ liệu thật có trường này. Sau khi chạy thử thật: sticker thiết kế lại (thẻ giá đỏ có nhãn phần trăm giảm tính từ hai giá, giá gốc gạch ngang, viên thuốc tối với số màu vàng, ngôi sao cho điểm đánh giá, "225,2k+" thay cho số dài, vẽ mịn có bóng) và đặt cao để không che mặt người; giá viết kiểu "122.147" (chấm ngăn nghìn) đã đọc đúng. Đã dựng thử video giả trong Docker và xem khung hình (chữ tiếng Việt đúng, vị trí đúng cảnh); chưa thử trên video thật · **Công sức:** vừa · **Nguồn:** nguyentatkiem (khối HyperFrames, Apache-2.0 của HeyGen)

**Làm gì.** Render ảnh PNG từ dữ liệu thật của sản phẩm (giá, lượt bán, mã giảm) rồi ffmpeg `overlay` lên video đúng lúc nhắc tới.

**Tác dụng và lý do.** Quảng cáo Việt hay có giá và lượt bán trên màn hình, tăng độ tin cậy.

**Rủi ro.** Số liệu phải lấy đúng từ dữ liệu sản phẩm. Không dùng preset chứa số mẫu.

---

## Không áp dụng

- Template, 28 gói style, 11 nguồn b-roll stock: dành cho video quay thật.
- Chrome headless render, WebGPU/ONNX, avatar số (JoyVASA, LivePortrait): quá nặng và lệch hướng.
- Azure, OneDrive, DJI của zecloud.
- Quy tắc "ít nhất 3 case khác nhau" của ai-video-editor: quá nặng cho video 30 giây.
- Phụ thuộc Claude Code CLI để chạy AI: dự án đã có BAML và 9router.

## Thứ tự đề xuất

1 → (2, 3) → (4, 8) → (5, 6, 7) → còn lại. Mục 5 cần mục 6.
