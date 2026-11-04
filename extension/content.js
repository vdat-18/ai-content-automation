// Isolated content script. Relays what the page already loaded to the background worker.
// In walker mode it also scrolls the page like a reader would so lazy sections load.
// At any security check or login wall it stops and waits for you.
(() => {
  const state = { enabled: false, walker: false, harvest: false, sent: new Set(), captured: false };
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const challengeReason = () => {
    const title = (document.title || "").toLowerCase();
    const text = (document.body?.innerText || "").slice(0, 3000).toLowerCase();
    if (title.includes("security check") || text.includes("verify to continue") || text.includes("drag the puzzle")) {
      return "captcha";
    }
    if (location.pathname.includes("/login") || text.includes("đăng nhập vào tiktok") || text.includes("log in to tiktok")) {
      return "đăng nhập";
    }
    return null;
  };

  const banner = (message) => {
    let el = document.getElementById("aic-collector-banner");
    if (!el) {
      el = document.createElement("div");
      el.id = "aic-collector-banner";
      el.style.cssText =
        "position:fixed;z-index:2147483647;right:12px;bottom:12px;padding:8px 12px;border-radius:8px;" +
        "background:#111827;color:#fff;font:13px system-ui;opacity:.92";
      document.documentElement.appendChild(el);
    }
    el.textContent = message;
  };

  const send = (message) => {
    try {
      chrome.runtime.sendMessage(message);
    } catch (_) {
      // extension reloaded
    }
  };

  const snapshot = (reason) => {
    const scripts = {};
    document.querySelectorAll("script[type='application/ld+json']").forEach((el, i) => {
      scripts[`ldjson_${i}`] = el.textContent;
    });
    send({
      type: "ingest",
      payload: {
        kind: "page",
        reason,
        url: location.href,
        title: document.title,
        captured_at: new Date().toISOString(),
        scripts,
        html: document.documentElement.outerHTML,
      },
    });
    state.captured = true;
    banner(`AIC Collector: đã gửi trang (${reason})`);
  };

  // wait while a human clears a security check or login, then go on
  const waitForHuman = async () => {
    let reason = challengeReason();
    if (!reason) return;
    send({ type: "challenge", reason });
    banner(`AIC Collector: chờ bạn xử lý ${reason}`);
    while (challengeReason()) {
      send({ type: "heartbeat" });
      await wait(2000);
    }
    send({ type: "resumed" });
    await wait(3000);
  };

  const clickByText = (label) => {
    const candidates = Array.from(document.querySelectorAll("button, [role='button'], a, div, span")).filter(
      (el) => el.children.length <= 2 && (el.textContent || "").replace(/[\s→←]+/g, " ").trim() === label && el.offsetParent !== null,
    );
    const target = candidates[candidates.length - 1];
    if (!target) return false;
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.click();
    return true;
  };

  // The "Xem thêm" that loads more products sits under the product grid. The ones at the top of each
  // section are links to another page, so only a plain button, never one inside a link, is clicked,
  // and the lowest one on the page wins. The label is found from its text, whatever the markup is.
  const loadMoreButtons = () => {
    const found = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const label = (walker.currentNode.nodeValue || "").replace(/[\s→←>›»]+/g, " ").trim().toLowerCase();
      if (label !== "xem thêm" || !walker.currentNode.parentElement) continue;
      const element = walker.currentNode.parentElement;
      const target = element.closest("button, [role='button']") || element;
      if (target.closest("a[href]")) continue;
      const rect = target.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      found.push({ target, top: rect.top + window.scrollY });
    }
    return found.sort((x, y) => y.top - x.top);
  };

  const press = (target) => {
    target.scrollIntoView({ block: "center", behavior: "instant" });
    for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
      target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    }
  };

  // only a button below the last product card loads more; the others belong to a section above
  const clickLoadMore = () => {
    const buttons = loadMoreButtons();
    const gridBottom = Array.from(document.querySelectorAll("a[href*='/pdp/']")).reduce((bottom, card) => {
      const rect = card.getBoundingClientRect();
      return rect.height ? Math.max(bottom, rect.bottom + window.scrollY) : bottom;
    }, 0);
    const usable = buttons.filter(({ top }) => top >= gridBottom - 5);
    if (!usable.length) return { clicked: false, seen: buttons.length };
    press(usable[0].target);
    return { clicked: true, seen: buttons.length };
  };

  const REVIEW_PAGES = 1; // TikTok answers the review paging call with code 100000, so only the first page is read

  const scrollLikeReader = async () => {
    const steps = 9;
    for (let i = 0; i < steps; i += 1) {
      window.scrollBy({ top: Math.round(window.innerHeight * 0.8), behavior: "smooth" });
      send({ type: "heartbeat" });
      await wait(900 + Math.random() * 600);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
    await wait(800);
  };

  // TikTok answers a product it does not sell to this region with a bare JSON message
  const unavailable = () => /not currently available in your country or region/i.test((document.body?.innerText || "").slice(0, 600));

  const runWalkerFlow = async () => {
    await wait(3000);
    await waitForHuman();
    if (unavailable()) {
      send({ type: "page-done", ok: false, reason: "unavailable" });
      return;
    }
    if (!/\/pdp\//.test(location.pathname)) {
      send({ type: "page-done", ok: false, reason: "không phải trang sản phẩm" });
      return;
    }
    await scrollLikeReader();
    // the description is folded behind "Xem thêm"; open it so the page holds the whole text
    for (let i = 0; i < 3 && clickByText("Xem thêm"); i += 1) await wait(1500);
    await waitForHuman();
    snapshot("walker");
    for (let page = 2; page <= REVIEW_PAGES; page += 1) {
      await wait(1500 + Math.random() * 1200);
      if (!clickByText("Tiếp theo")) break;
      await wait(2500);
      await waitForHuman();
      snapshot(`walker-reviews-${page}`);
    }
    await wait(1500);
    send({ type: "page-done", ok: true });
  };

  // Pinterest keeps only the pins near the viewport in the DOM, so pins are gathered while scrolling.
  const PIN_MAX_ROUNDS = 80; // hard stop so a search never scrolls forever
  const PIN_IDLE_ROUNDS = 4; // stop after this many scrolls that found no new pin
  const pinterestLoginWall = () =>
    location.pathname.startsWith("/login") || Boolean(document.querySelector("[data-test-id='login-modal'], [data-test-id='registerForm']"));

  const collectPins = (pins) => {
    document.querySelectorAll("a[href*='/pin/']").forEach((link) => {
      const img = link.querySelector("img[src*='pinimg.com']");
      if (!img) return;
      const pinUrl = new URL(link.getAttribute("href"), location.origin).pathname;
      pins.set(img.src, { image_url: img.src, pin_url: pinUrl, title: (img.alt || "").trim() });
    });
  };

  const runPinterestFlow = async (meta) => {
    await wait(3000);
    for (let guard = 0; pinterestLoginWall() && guard < 600; guard += 1) {
      if (guard === 0) {
        send({ type: "challenge", reason: "đăng nhập Pinterest" });
        banner("AIC Collector: chờ bạn đăng nhập Pinterest");
      }
      send({ type: "heartbeat" });
      await wait(2000);
      if (!pinterestLoginWall()) send({ type: "resumed" });
    }
    const pins = new Map();
    const maxImages = Number(meta.max_images) || Infinity;
    let idleRounds = 0;
    for (let round = 0; round < PIN_MAX_ROUNDS && pins.size < maxImages && idleRounds < PIN_IDLE_ROUNDS; round += 1) {
      const before = pins.size;
      collectPins(pins);
      window.scrollBy({ top: Math.round(window.innerHeight * 0.9), behavior: "smooth" });
      send({ type: "heartbeat" });
      banner(`AIC Collector: Pinterest ${meta.query}: ${pins.size} ảnh`);
      await wait(1400 + Math.random() * 900);
      collectPins(pins);
      idleRounds = pins.size === before ? idleRounds + 1 : 0;
    }
    collectPins(pins);
    send({
      type: "ingest",
      payload: { kind: "pinterest", product_type: meta.product_type, query: meta.query, pins: [...pins.values()] },
    });
    await wait(1500);
    send({ type: "page-done", ok: pins.size > 0, reason: pins.size ? "" : "không thấy ảnh" });
  };

  // Scroll a feed page (home, category, search) so the page itself loads more products.
  // With `auto` it keeps going until no new product shows up, then tells the background worker,
  // which reads every product page.
  const productCount = () => new Set(Array.from(document.querySelectorAll("a[href*='/pdp/']")).map((a) => a.pathname)).size;
  const FEED_IDLE_ROUNDS = 4; // rounds with nothing new and no "Xem thêm" left
  const FEED_STUCK_CLICKS = 8; // clicks on "Xem thêm" in a row that brought nothing
  // after a click, wait for new cards or new JSON instead of a fixed pause
  const waitForGrowth = async (count, payloads, timeoutMs) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      await wait(500);
      if (productCount() > count || state.sent.size > payloads) return true;
    }
    return false;
  };

  const harvestFeed = async (rounds, auto) => {
    state.harvest = true;
    let idle = 0;
    let stuck = 0;
    let clicks = 0;
    let reason = "đã cuộn đủ số lượt";
    const startPath = location.pathname;
    let last = productCount();
    for (let i = 0; i < rounds; i += 1) {
      await waitForHuman();
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
      await wait(1500);
      const payloads = state.sent.size;
      const { clicked, seen } = clickLoadMore();
      if (clicked) clicks += 1;
      banner(`AIC Collector: lấy danh sách ${i + 1}/${rounds}, ${last} sản phẩm, đã bấm Xem thêm ${clicks} lần${clicked ? "" : ", chưa thấy nút Xem thêm"} (${seen} nút)`);
      send({ type: "heartbeat" });
      const grew = await waitForGrowth(last, payloads, clicked ? 8000 : 3000);
      if (location.pathname !== startPath) {
        // a button that opens another page was pressed by mistake: go back and stop
        history.back();
        await wait(2500);
        reason = "bấm nhầm một nút chuyển sang trang khác, đã quay lại";
        break;
      }
      const now = productCount();
      if (auto) {
        if (clicked) stuck = grew ? 0 : stuck + 1;
        idle = grew ? 0 : idle + 1;
        if (!clicked && idle >= FEED_IDLE_ROUNDS) {
          reason = "không còn nút Xem thêm và không có sản phẩm mới";
          break;
        }
        if (stuck >= FEED_STUCK_CLICKS) {
          reason = `bấm Xem thêm ${FEED_STUCK_CLICKS} lần liên tiếp mà không có sản phẩm mới`;
          break;
        }
      }
      last = now;
    }
    state.harvest = false;
    window.scrollTo({ top: 0, behavior: "smooth" });
    banner(auto ? `AIC Collector: dừng cuộn (${reason}), có ${last} sản phẩm` : "AIC Collector: xong, đã gửi danh sách sản phẩm");
    if (auto) send({ type: "harvest-done", auto, count: last, clicks, reason });
  };

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.source !== "aic-hook") return;
    if (!(state.enabled || state.walker || state.harvest)) return;
    const { url, status, body } = event.data;
    const key = url + ":" + body.length;
    if (state.sent.has(key)) return;
    state.sent.add(key);
    send({ type: "ingest", payload: { kind: "json", url, status, page_url: location.href, captured_at: new Date().toISOString(), body } });
  });

  chrome.storage.local.get({ enabled: false }, (stored) => {
    state.enabled = Boolean(stored.enabled);
    chrome.runtime.sendMessage({ type: "am-i-walker" }, (response) => {
      state.walker = Boolean(response?.walker);
      if (state.walker && location.hostname.endsWith("pinterest.com")) runPinterestFlow(response.meta || {});
      else if (state.walker) runWalkerFlow();
      else if (state.enabled && !location.hostname.endsWith("pinterest.com") && !challengeReason()) setTimeout(() => snapshot("auto"), 4000);
    });
  });
  chrome.storage.onChanged.addListener((changes) => {
    if (changes.enabled) state.enabled = Boolean(changes.enabled.newValue);
  });
  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type === "harvest") {
      harvestFeed(Number(message.rounds) || 15, message.auto || null);
    }
    if (message?.type === "capture-now") {
      if (challengeReason()) banner("AIC Collector: đang có kiểm tra bảo mật, hãy xử lý trước");
      else snapshot("manual");
    }
  });
})();
