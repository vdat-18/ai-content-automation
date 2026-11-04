const COLLECTOR = "http://127.0.0.1:8000/api/v1/products";
const PAGE_TIMEOUT_MS = 120_000;
const MIN_GAP_MS = 4_000; // pause between opening two product tabs, so they do not all load at once
const MAX_GAP_MS = 8_000;
const MAX_TABS = 5;

const EMPTY = { running: false, queue: [], meta: {}, next: 0, active: {}, done: 0, failed: 0, paused: false, concurrency: 1, note: "" };
const timers = new Map(); // tabId -> timeout that gives up on a page that never finishes
let opening = false;
let lock = Promise.resolve();

const getState = () => chrome.storage.local.get({ walker: EMPTY }).then((s) => ({ ...EMPTY, ...s.walker }));
const setState = (walker) => chrome.storage.local.set({ walker });
// Several tabs report at the same time, so every change to the walker state runs one after another.
const locked = (task) => {
  const run = lock.then(task, task);
  lock = run.catch(() => {});
  return run;
};

// ---- ingest from content scripts -------------------------------------------------
async function ingest(payload) {
  try {
    await fetch(`${COLLECTOR}/ingest`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const s = await chrome.storage.local.get({ sent: 0 });
    await chrome.storage.local.set({ sent: s.sent + 1, error: "" });
  } catch (error) {
    await chrome.storage.local.set({ error: String(error) });
  }
}

// ---- walker: opens up to `concurrency` product tabs at once -----------------------
const badge = (w) => chrome.action.setBadgeText({ text: w.running ? String(w.queue.length - w.done - w.failed) : "" });
const armTimer = (tabId) => {
  clearTimeout(timers.get(tabId));
  timers.set(tabId, setTimeout(() => finishTab(tabId, false, "timeout"), PAGE_TIMEOUT_MS));
};

async function fill() {
  if (opening) return;
  opening = true;
  try {
    for (;;) {
      const w = await locked(getState);
      if (!w.running || w.paused) return;
      if (w.next >= w.queue.length) {
        if (!Object.keys(w.active).length) {
          w.running = false;
          w.note = `Xong: ${w.done} thành công, ${w.failed} lỗi`;
          await locked(() => setState(w));
          badge(w);
        }
        return;
      }
      if (Object.keys(w.active).length >= w.concurrency) return;
      const url = w.queue[w.next];
      const tab = await chrome.tabs.create({ url, active: false });
      await locked(async () => {
        const fresh = await getState();
        fresh.active[tab.id] = url;
        fresh.next += 1;
        fresh.note = `Đang chạy ${Object.keys(fresh.active).length} tab song song`;
        await setState(fresh);
        badge(fresh);
      });
      armTimer(tab.id);
      await new Promise((resolve) => setTimeout(resolve, MIN_GAP_MS + Math.random() * (MAX_GAP_MS - MIN_GAP_MS)));
    }
  } finally {
    opening = false;
  }
}

async function finishTab(tabId, ok, reason) {
  clearTimeout(timers.get(tabId));
  timers.delete(tabId);
  const known = await locked(async () => {
    const w = await getState();
    if (!w.active[tabId]) return false;
    delete w.active[tabId];
    if (ok) w.done += 1;
    else w.failed += 1;
    w.note = ok ? "OK" : `Bỏ qua (${reason})`;
    await setState(w);
    badge(w);
    return true;
  });
  if (!known) return;
  chrome.tabs.remove(tabId).catch(() => {});
  fill();
}

async function pauseForHuman(tabId, reason) {
  await locked(async () => {
    const w = await getState();
    w.paused = true;
    w.note = `Đang chờ bạn xử lý: ${reason}`;
    await setState(w);
  });
  for (const id of timers.keys()) clearTimeout(timers.get(id));
  chrome.action.setBadgeText({ text: "!" });
  if (tabId) chrome.tabs.update(tabId, { active: true }).catch(() => {});
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icon.png",
    title: "AIC Collector cần bạn",
    message: `Xử lý ${reason} trong tab TikTok, thu thập sẽ tự chạy tiếp.`,
  });
}

async function startWalker(urls, meta, concurrency) {
  await locked(() =>
    setState({
      ...EMPTY,
      running: true,
      queue: urls,
      meta: meta || {},
      concurrency: Math.min(Math.max(Number(concurrency) || 1, 1), MAX_TABS),
      note: "Bắt đầu",
    }),
  );
  fill();
}

// ---- one click: scroll the feed, then read every product page ---------------------
async function afterHarvest(auto) {
  // give the page's last JSON responses time to reach the collector
  await new Promise((resolve) => setTimeout(resolve, 5000));
  try {
    const urls = await (await fetch(`${COLLECTOR}/queue?limit=${Number(auto.limit) || 5000}`)).json();
    if (!urls.length) {
      await chrome.storage.local.set({ autoNote: "Không có sản phẩm mới để lấy chi tiết." });
      return;
    }
    await chrome.storage.local.set({ autoNote: `Đã có ${urls.length} sản phẩm, đang lấy chi tiết` });
    startWalker(urls, {}, auto.concurrency);
  } catch (error) {
    await chrome.storage.local.set({ autoNote: `Không gọi được collector: ${error}` });
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const tabId = sender.tab?.id;
  switch (message?.type) {
    case "ingest":
      ingest(message.payload);
      break;
    case "am-i-walker":
      locked(getState).then((w) => {
        const url = w.active[tabId];
        sendResponse({ walker: w.running && Boolean(url), meta: (url && w.meta?.[url]) || null });
      });
      return true;
    case "heartbeat":
      locked(getState).then((w) => {
        if (w.running && !w.paused && w.active[tabId]) armTimer(tabId);
      });
      break;
    case "challenge":
      pauseForHuman(tabId, message.reason || "kiểm tra bảo mật");
      break;
    case "resumed":
      locked(async () => {
        const w = await getState();
        w.paused = false;
        w.note = "Đã xử lý, tiếp tục";
        await setState(w);
        badge(w);
        for (const id of Object.keys(w.active)) armTimer(Number(id));
      }).then(fill);
      break;
    case "page-done":
      finishTab(tabId, Boolean(message.ok), message.reason || "");
      break;
    case "harvest-done":
      if (message.auto) afterHarvest(message.auto);
      break;
    case "walker-start":
      startWalker(message.urls, message.meta, message.concurrency);
      break;
    case "walker-stop":
      locked(async () => {
        const w = await getState();
        for (const id of Object.keys(w.active)) {
          clearTimeout(timers.get(Number(id)));
          chrome.tabs.remove(Number(id)).catch(() => {});
        }
        w.running = false;
        w.active = {};
        w.note = "Đã dừng";
        await setState(w);
        badge(w);
      });
      break;
    default:
      break;
  }
});
