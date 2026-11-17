# AIC Collector (Chrome extension)

Runs in your own Chrome. You log in and solve any security check; the extension pauses and resumes by itself.

1. Start the API on `127.0.0.1:8000` (the extension talks to this address directly, not through the
   dashboard on port 8080, so nginx basic auth does not protect it).
2. `chrome://extensions` → Developer mode → Load unpacked → this folder.
3. One product: open a TikTok Shop product page and press "Send this product" in the popup. "Make a video
   from it" then opens the product in the dashboard.
4. Many products: open "Collect many products", log in and clear any captcha on TikTok Shop, then press
   "Collect everything: home page + 28 categories, then every product page". It reads the home page and each
   category, then opens the product pages from `GET /api/v1/products/queue`. The tab count (default 20,
   at most 20) is used for both parts. At a captcha or login it pauses all tabs and waits for you.
   "Capture this page" sends the page you are looking at.
5. Download results from the popup (Excel, JSON) or `GET /api/v1/products/export?format=json|xlsx`.
6. Reference images: approve the search keywords in the dashboard under AI memory → Reference scenes, then
   press "Collect Pinterest images for approved keywords" (log in to Pinterest first; 3 tabs by default, at
   most 5). Images land in `GET /api/v1/products/reference-images`.

## Politeness and safety

- The pause between two product tabs starts at 3 s, doubles (with jitter, up to 120 s) after every captcha and shrinks back by 10% after each good page. At most 20 pages are opened per minute.
- Captcha waves (tabs hit at the same moment count once): 3 in 10 minutes stop the run; a new run is refused until the window has passed.
- When a captcha or login is waiting for you and nobody clears it within 15 minutes, the run stops.
- A product page that stays empty is skipped; a product not sold in your region is skipped and remembered.
- TikTok and Pinterest runs are separate: each has its own queue, tabs and pauses.
- The extension never solves captchas: you do, and it carries on.
- Tests: `node --test extension/tests/background.test.cjs`.
