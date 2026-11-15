const COLLECTOR = "http://127.0.0.1:8000/api/v1/products";
const PAGE_TIMEOUT_MS = 120_000;
const MAX_TABS = 5;

// Politeness: the pause between two product tabs starts at BASE_DELAY_MS, doubles (with jitter) every time
// TikTok shows a captcha, and shrinks back slowly while pages load fine. PAGES_PER_MINUTE is a hard cap.
const BASE_DELAY_MS = 4_000;
const MAX_DELAY_MS = 120_000;
const SHRINK_FACTOR = 0.9;
const PAGES_PER_MINUTE = 12;
const QUEUE_LIMIT = 100_000; // every product still without its page
// Circuit breaker: this many captcha waves in this window stops the run, so TikTok is not pushed further.
const BREAKER_CAPTCHAS = 3;
const BREAKER_WINDOW_MS = 10 * 60_000;
const CAPTCHA_WAVE_MS = 30_000; // captchas on several tabs at once count as one
const HUMAN_WAIT_MS = 15 * 60_000; // give up when nobody clears a captcha or login in time

// TikTok and Pinterest are separate lanes: each has its own queue, tabs, pauses and Stop button,
// so one can run (or wait for a captcha) while the other keeps going.
const STORAGE_KEY = { tiktok: "walker", pinterest: "pinWalker" };
const LANES = Object.keys(STORAGE_KEY);
const laneOfKind = (kind) => (kind === "pinterest" ? "pinterest" : "tiktok");

const EMPTY = {
  running: false,
  queue: [],
  meta: {},
  next: 0,
  active: {},
  done: 0,
  failed: 0,
  paused: false,
  concurrency: 1,
  delayMs: BASE_DELAY_MS,
  note: "",
  detail: "",
  kind: "tiktok", // which collector owns the run: "tiktok", "category" or "pinterest"
  followUp: null, // after the last category: read the product pages with this many tabs
  lane: "tiktok",
};
const timers = new Map(); // tabId -> timeout that gives up on a page that never finishes
const local = Object.fromEntries(LANES.map((lane) => [lane, { recentOpens: [], humanTimer: null, opening: false }]));
let lock = Promise.resolve();

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const jitter = (low = 0.75, high = 1.25) => low + Math.random() * (high - low);
const getState = (lane = "tiktok") =>
  chrome.storage.local.get({ [STORAGE_KEY[lane]]: EMPTY }).then((s) => ({ ...EMPTY, ...s[STORAGE_KEY[lane]], lane }));
const setState = (walker) => chrome.storage.local.set({ [STORAGE_KEY[walker.lane || "tiktok"]]: walker });
// Several tabs report at the same time, so every change to the walker state runs one after another.
const locked = (task) => {
  const run = lock.then(task, task);
  lock = run.catch(() => {});
  return run;
};
// Which lane a tab belongs to, or null when no run opened it.
const laneOfTab = async (tabId) => {
  for (const lane of LANES) {
    if ((await getState(lane)).active[tabId]) return lane;
  }
  return null;
};

// ---- ingest from content scripts -------------------------------------------------
async function ingest(payload) {
  try {
    const response = await fetch(`${COLLECTOR}/ingest`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const s = await chrome.storage.local.get({ sent: 0 });
    if (!response.ok) {
      // the collector refused the data (for example the duplicate check is off): say so, never swallow it
      const detail = await response.json().then((body) => body.detail).catch(() => "");
      await chrome.storage.local.set({ sent: s.sent + 1, error: `HTTP ${response.status}${detail ? `: ${detail}` : ""}` });
      if (payload.kind === "page") await chrome.storage.local.set({ lastCapture: { stored: "refused", reason: String(detail || response.status) } });
      return;
    }
    const result = await response.json().catch(() => ({}));
    // the popup shows what happened to the page the user just sent
    if (payload.kind === "page") {
      await chrome.storage.local.set({ lastCapture: { stored: result.stored || "", productId: result.product_id || "", reason: result.reason || "" } });
    }
    const failed = Number(result.check_failed || 0);
    await chrome.storage.local.set({ sent: s.sent + 1, error: failed ? `${failed} images could not be checked for duplicates (see the References page)` : "" });
  } catch (error) {
    await chrome.storage.local.set({ error: String(error) });
  }
}

// ---- captcha log and circuit breaker (TikTok only) ---------------------------------
async function recentCaptchas() {
  const s = await chrome.storage.local.get({ captchaLog: [] });
  return s.captchaLog.filter((at) => Date.now() - at < BREAKER_WINDOW_MS);
}

// Returns true when this captcha is a new wave and counts toward the breaker.
function logCaptcha() {
  // locked: tabs hit by the same captcha wave report within milliseconds of each other
  return locked(async () => {
    const log = await recentCaptchas();
    const isNewWave = !log.length || Date.now() - log[log.length - 1] > CAPTCHA_WAVE_MS;
    if (isNewWave) log.push(Date.now());
    await chrome.storage.local.set({ captchaLog: log });
    return { isNewWave, count: log.length };
  });
}

async function breakerOpenFor() {
  const log = await recentCaptchas();
  if (log.length < BREAKER_CAPTCHAS) return 0;
  return Math.max(0, log[log.length - BREAKER_CAPTCHAS] + BREAKER_WINDOW_MS - Date.now());
}

// ---- walker: opens up to `concurrency` tabs at once, per lane -----------------------
// The badge counts what is left in both lanes.
async function badge() {
  const states = await Promise.all(LANES.map((lane) => getState(lane)));
  const left = states.filter((w) => w.running).reduce((sum, w) => sum + w.queue.length - w.done - w.failed, 0);
  chrome.action.setBadgeText({ text: states.some((w) => w.running) ? String(left) : "" });
}
const armTimer = (tabId) => {
  clearTimeout(timers.get(tabId));
  timers.set(tabId, setTimeout(() => finishTab(tabId, false, "timeout"), PAGE_TIMEOUT_MS));
};

async function waitForMinuteCap(lane) {
  const { recentOpens } = local[lane];
  for (;;) {
    const now = Date.now();
    while (recentOpens.length && now - recentOpens[0] > 60_000) recentOpens.shift();
    if (recentOpens.length < PAGES_PER_MINUTE) return;
    await sleep(Math.max(500, recentOpens[0] + 60_000 - now));
  }
}

async function fill(lane) {
  if (local[lane].opening) return;
  local[lane].opening = true;
  try {
    for (;;) {
      const w = await locked(() => getState(lane));
      if (!w.running || w.paused) return;
      if (w.next >= w.queue.length) {
        if (!Object.keys(w.active).length) {
          w.running = false;
          w.note = `Done: ${w.done} succeeded, ${w.failed} failed`;
          await locked(() => setState(w));
          badge();
          if (w.kind === "category" && w.followUp) fetchDetails(w.followUp);
        }
        return;
      }
      if (Object.keys(w.active).length >= w.concurrency) return;
      await waitForMinuteCap(lane);
      const url = w.queue[w.next];
      local[lane].recentOpens.push(Date.now());
      const tab = await chrome.tabs.create({ url, active: false });
      await locked(async () => {
        const fresh = await getState(lane);
        fresh.active[tab.id] = url;
        fresh.next += 1;
        fresh.note = `Running ${Object.keys(fresh.active).length} tabs, pausing about ${Math.round(fresh.delayMs / 1000)} s between pages`;
        await setState(fresh);
      });
      badge();
      armTimer(tab.id);
      await sleep((await locked(() => getState(lane))).delayMs * jitter());
    }
  } finally {
    local[lane].opening = false;
  }
}

async function finishTab(tabId, ok, reason) {
  clearTimeout(timers.get(tabId));
  timers.delete(tabId);
  const lane = await locked(async () => {
    for (const name of LANES) {
      const w = await getState(name);
      if (!w.active[tabId]) continue;
      if (reason === "unavailable") await rememberUnavailable(w.active[tabId]);
      delete w.active[tabId];
      w.detail = "";
      if (ok) {
        w.done += 1;
        w.delayMs = Math.max(BASE_DELAY_MS, Math.round(w.delayMs * SHRINK_FACTOR));
      } else {
        w.failed += 1;
      }
      w.note = ok ? "OK" : `Skipped (${reason})`;
      await setState(w);
      return name;
    }
    return null;
  });
  if (!lane) return;
  badge();
  chrome.tabs.remove(tabId).catch(() => {});
  fill(lane);
}

async function stopWalker(lane, note) {
  clearTimeout(local[lane].humanTimer);
  await locked(async () => {
    const w = await getState(lane);
    for (const id of Object.keys(w.active)) {
      clearTimeout(timers.get(Number(id)));
      chrome.tabs.remove(Number(id)).catch(() => {});
    }
    w.running = false;
    w.paused = false;
    w.active = {};
    w.note = note;
    await setState(w);
  });
  badge();
}

function notify(title, message) {
  chrome.notifications.create({ type: "basic", iconUrl: "icon.png", title, message });
}

async function pauseForHuman(tabId, reason) {
  const lane = (await laneOfTab(tabId)) || "tiktok";
  const isCaptcha = reason === "captcha";
  // only TikTok has the breaker: Pinterest is paused and resumed like TikTok, but never counted
  if (isCaptcha && lane === "tiktok") {
    const { isNewWave, count } = await logCaptcha();
    if (isNewWave) {
      // TikTok is getting suspicious: slow down for the rest of the run
      await locked(async () => {
        const w = await getState(lane);
        w.delayMs = Math.min(MAX_DELAY_MS, Math.round(w.delayMs * 2 * jitter()));
        await setState(w);
      });
    }
    if (count >= BREAKER_CAPTCHAS) {
      await stopWalker(lane, `Stopped after ${count} captchas in 10 minutes. Wait 15 to 30 minutes, then run again.`);
      notify("AIC Collector stopped", `${count} captchas in 10 minutes. Wait 15 to 30 minutes, then run again to avoid being flagged further.`);
      return;
    }
  }
  const active = await locked(async () => {
    const w = await getState(lane);
    w.paused = true;
    w.note = `Waiting for you: ${reason}`;
    await setState(w);
    return Object.keys(w.active).map(Number);
  });
  for (const id of active) clearTimeout(timers.get(id));
  clearTimeout(local[lane].humanTimer);
  local[lane].humanTimer = setTimeout(async () => {
    await stopWalker(lane, "Stopped: no one handled the captcha or login within 15 minutes.");
    notify("AIC Collector stopped", "The captcha or login was not handled within 15 minutes. Run again when you are ready.");
  }, HUMAN_WAIT_MS);
  chrome.action.setBadgeText({ text: "!" });
  if (tabId) chrome.tabs.update(tabId, { active: true }).catch(() => {});
  notify("AIC Collector needs you", `Handle the ${reason} in the ${lane === "pinterest" ? "Pinterest" : "TikTok"} tab; collection resumes by itself.`);
}

// Products TikTok does not sell to this region come back in the queue every run, so remember them.
const productKey = (url) => (url.match(/\/pdp\/(?:[^/?]+\/)?(\d+)/) || [])[1] || url;
async function rememberUnavailable(url) {
  const s = await chrome.storage.local.get({ unavailable: [] });
  const key = productKey(url);
  if (!s.unavailable.includes(key)) await chrome.storage.local.set({ unavailable: [...s.unavailable, key] });
}

async function startWalker(urls, meta, concurrency, kind = "tiktok", followUp = null) {
  const lane = laneOfKind(kind);
  if (lane === "tiktok") {
    const waitMs = await breakerOpenFor();
    if (waitMs > 0) {
      const note = `Too many captchas just now. Wait about ${Math.ceil(waitMs / 60_000)} more minutes, then run again.`;
      await chrome.storage.local.set({ autoNote: note });
      await locked(() => setState({ ...EMPTY, lane, note }));
      return;
    }
  }
  const skipped = new Set((await chrome.storage.local.get({ unavailable: [] })).unavailable);
  const wanted = skipped.size && lane === "tiktok" ? urls.filter((url) => !skipped.has(productKey(url))) : urls;
  await locked(() =>
    setState({
      ...EMPTY,
      lane,
      running: true,
      queue: wanted,
      meta: meta || {},
      kind,
      followUp,
      concurrency: Math.min(Math.max(Number(concurrency) || 1, 1), MAX_TABS),
      note: "Started",
    }),
  );
  badge();
  fill(lane);
}

// ---- one click: scroll the feed, then read every product page ---------------------
async function afterHarvest(auto, summary) {
  // give the page's last JSON responses time to reach the collector
  await sleep(5000);
  try {
    const urls = await (await fetch(`${COLLECTOR}/queue?limit=${Number(auto.limit) || 5000}`)).json();
    if (!urls.length) {
      await chrome.storage.local.set({
        autoNote: `Stopped scrolling: ${summary.reason}. The page has ${summary.count} products, "Load more" clicked ${summary.clicks} times. No new products to fetch.`,
      });
      return;
    }
    await chrome.storage.local.set({
      autoNote: `Stopped scrolling: ${summary.reason}. The page has ${summary.count} products, "Load more" clicked ${summary.clicks} times. Fetching details for ${urls.length} new products.`,
    });
    startWalker(urls, {}, auto.concurrency);
  } catch (error) {
    await chrome.storage.local.set({ autoNote: `Could not reach the collector: ${error}` });
  }
}

// ---- after the last category: read every product page that is still missing ---------
async function fetchDetails(followUp) {
  await sleep(5000); // the last JSON responses reach the collector
  try {
    const urls = await (await fetch(`${COLLECTOR}/queue?limit=${QUEUE_LIMIT}`)).json();
    const note = urls.length
      ? `All category lists collected. Fetching the page of ${urls.length} products.`
      : "All category lists collected. No product page is missing.";
    await chrome.storage.local.set({ autoNote: note });
    if (urls.length) startWalker(urls, {}, followUp.concurrency);
  } catch (error) {
    await chrome.storage.local.set({ autoNote: `Could not reach the collector: ${error}` });
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const tabId = sender.tab?.id;
  switch (message?.type) {
    case "ingest":
      ingest(message.payload);
      break;
    case "am-i-walker":
      locked(async () => {
        for (const lane of LANES) {
          const w = await getState(lane);
          const url = w.active[tabId];
          if (url) return { walker: w.running, meta: w.meta?.[url] || null };
        }
        return { walker: false, meta: null };
      }).then(sendResponse);
      return true;
    case "progress":
      locked(async () => {
        for (const lane of LANES) {
          const w = await getState(lane);
          if (!w.running || !w.active[tabId]) continue;
          w.detail = String(message.detail || "").slice(0, 160);
          await setState(w);
        }
      });
      break;
    case "heartbeat":
      locked(async () => {
        for (const lane of LANES) {
          const w = await getState(lane);
          if (w.running && !w.paused && w.active[tabId]) armTimer(tabId);
        }
      });
      break;
    case "challenge":
      pauseForHuman(tabId, message.reason || "security check");
      break;
    case "resumed":
      // the tab that was handled tells which lane goes on; without a tab, every paused lane does
      (async () => {
        const own = tabId ? await laneOfTab(tabId) : null;
        for (const lane of own ? [own] : LANES) {
          clearTimeout(local[lane].humanTimer);
          const resumed = await locked(async () => {
            const w = await getState(lane);
            if (!w.paused) return false;
            w.paused = false;
            w.note = "Handled, continuing";
            await setState(w);
            for (const id of Object.keys(w.active)) armTimer(Number(id));
            return true;
          });
          if (resumed) fill(lane);
        }
        badge();
      })();
      break;
    case "page-done":
      finishTab(tabId, Boolean(message.ok), message.reason || "");
      break;
    case "harvest-done":
      if (message.auto) afterHarvest(message.auto, { reason: message.reason || "", count: message.count || 0, clicks: message.clicks || 0 });
      break;
    case "walker-start":
      startWalker(
        message.urls,
        message.meta,
        message.concurrency,
        ["pinterest", "category"].includes(message.kind) ? message.kind : "tiktok",
        message.followUp || null,
      );
      break;
    case "walker-stop":
      for (const lane of message.lane ? [message.lane] : LANES) stopWalker(lane, "Stopped");
      break;
    default:
      break;
  }
});
