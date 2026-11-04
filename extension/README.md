# AIC Collector (Chrome extension)

Runs in your own Chrome. You log in and solve any security check; the extension pauses and resumes by itself.

1. Start the API on `127.0.0.1:8000`.
2. `chrome://extensions` → Developer mode → Load unpacked → this folder.
3. Open a TikTok Shop VN listing, log in and clear any captcha, click the extension and press "Tự cuộn lấy hết danh sách rồi cào chi tiết". It scrolls until no new product appears, then opens the product pages from `GET /api/v1/products/queue` in up to 5 tabs at once (3 by default). At a captcha or login it pauses all tabs and waits for you.
   The manual buttons "Cuộn trang danh sách" and "Lấy danh sách từ collector và chạy" still work, one tab at a time.
5. Download results: `GET /api/v1/products/export?format=json|xlsx`.

6. Reference images: approve keywords on the Products page, then press "Crawl Pinterest theo từ khóa đã duyệt" (log in to Pinterest first). Images land in `GET /api/v1/products/reference-images`.

## Politeness and safety

- The pause between two product tabs starts at 8 s, doubles (with jitter, up to 120 s) after every captcha and shrinks back by 10% after each good page. At most 6 pages are opened per minute.
- Captcha waves (tabs hit at the same moment count once): 3 in 10 minutes stop the run; a new run is refused until the window has passed.
- When a captcha or login is waiting for you and nobody clears it within 15 minutes, the run stops.
- A product page that stays empty is skipped; a product not sold in your region is skipped and remembered.
- The extension never solves captchas: you do, and it carries on.
- Tests: `node --test extension/tests/background.test.cjs`.
