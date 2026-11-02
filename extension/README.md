# AIC Collector (Chrome extension)

Runs in your own Chrome. You log in and solve any security check; the extension pauses and resumes by itself.

1. Start the API on `127.0.0.1:8000`.
2. `chrome://extensions` → Developer mode → Load unpacked → this folder.
3. Open a TikTok Shop VN listing, click the extension, "Cuộn trang danh sách" to collect listings.
4. Set a count and press start: it opens each product page from `GET /api/v1/products/queue`.
5. Download results: `GET /api/v1/products/export?format=json|xlsx`.
