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

  const runWalkerFlow = async () => {
    await wait(3000);
    await waitForHuman();
    if (!/\/pdp\//.test(location.pathname)) {
      send({ type: "page-done", ok: false, reason: "không phải trang sản phẩm" });
      return;
    }
    await scrollLikeReader();
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
  const PIN_SCROLL_ROUNDS = 14;
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
    for (let round = 0; round < PIN_SCROLL_ROUNDS; round += 1) {
      collectPins(pins);
      window.scrollBy({ top: Math.round(window.innerHeight * 0.9), behavior: "smooth" });
      send({ type: "heartbeat" });
      banner(`AIC Collector: Pinterest ${round + 1}/${PIN_SCROLL_ROUNDS}, ${pins.size} ảnh`);
      await wait(1400 + Math.random() * 900);
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
  const harvestFeed = async (rounds) => {
    state.harvest = true;
    for (let i = 0; i < rounds; i += 1) {
      await waitForHuman();
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
      await wait(1200);
      clickByText("Xem thêm");
      banner(`AIC Collector: lấy danh sách ${i + 1}/${rounds}`);
      send({ type: "heartbeat" });
      await wait(2200 + Math.random() * 1500);
    }
    state.harvest = false;
    window.scrollTo({ top: 0, behavior: "smooth" });
    banner("AIC Collector: xong, đã gửi danh sách sản phẩm");
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
      harvestFeed(Number(message.rounds) || 15);
    }
    if (message?.type === "capture-now") {
      if (challengeReason()) banner("AIC Collector: đang có kiểm tra bảo mật, hãy xử lý trước");
      else snapshot("manual");
    }
  });
})();
