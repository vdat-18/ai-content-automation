const COLLECTOR = "http://127.0.0.1:8000/api/v1/products";
const PAGE_TIMEOUT_MS = 120_000;
const MIN_GAP_MS = 4_000;
const MAX_GAP_MS = 8_000;

let timer = null;

const getState = () => chrome.storage.local.get({ walker: { running: false, queue: [], index: 0, done: 0, failed: 0, paused: false, tabId: null, note: "" } }).then((s) => s.walker);
const setState = (walker) => chrome.storage.local.set({ walker });

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

// ---- walker ---------------------------------------------------------------------
async function openNext() {
  const w = await getState();
  if (!w.running) return;
  if (w.index >= w.queue.length) {
    w.running = false;
    w.note = `Xong: ${w.done} thành công, ${w.failed} lỗi`;
    await setState(w);
    chrome.action.setBadgeText({ text: "" });
    return;
  }
  const url = w.queue[w.index];
  const tab = await chrome.tabs.create({ url, active: false });
  w.tabId = tab.id;
  w.paused = false;
  w.note = `Đang mở ${w.index + 1}/${w.queue.length}`;
  await setState(w);
  chrome.action.setBadgeText({ text: String(w.queue.length - w.index) });
  clearTimeout(timer);
  timer = setTimeout(() => advance(false, "timeout"), PAGE_TIMEOUT_MS);
}

async function advance(ok, reason) {
  clearTimeout(timer);
  const w = await getState();
  if (!w.running) return;
  if (w.tabId) chrome.tabs.remove(w.tabId).catch(() => {});
  if (ok) w.done += 1;
  else w.failed += 1;
  w.index += 1;
  w.tabId = null;
  w.note = ok ? "OK" : `Bỏ qua (${reason})`;
  await setState(w);
  const gap = MIN_GAP_MS + Math.random() * (MAX_GAP_MS - MIN_GAP_MS);
  setTimeout(openNext, gap);
}

async function pauseForHuman(reason) {
  clearTimeout(timer);
  const w = await getState();
  w.paused = true;
  w.note = `Đang chờ bạn xử lý: ${reason}`;
  await setState(w);
  chrome.action.setBadgeText({ text: "!" });
  if (w.tabId) chrome.tabs.update(w.tabId, { active: true }).catch(() => {});
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icon.png",
    title: "AIC Collector cần bạn",
    message: `Xử lý ${reason} trong tab TikTok, thu thập sẽ tự chạy tiếp.`,
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message?.type) {
    case "ingest":
      ingest(message.payload);
      break;
    case "am-i-walker":
      getState().then((w) => sendResponse({ walker: w.running && w.tabId === sender.tab?.id }));
      return true;
    case "heartbeat":
      break;
    case "challenge":
      pauseForHuman(message.reason || "kiểm tra bảo mật");
      break;
    case "resumed":
      getState().then((w) => {
        w.paused = false;
        w.note = "Đã xử lý, tiếp tục";
        setState(w);
        chrome.action.setBadgeText({ text: String(w.queue.length - w.index) });
        clearTimeout(timer);
        timer = setTimeout(() => advance(false, "timeout"), PAGE_TIMEOUT_MS);
      });
      break;
    case "page-done":
      advance(Boolean(message.ok), message.reason || "");
      break;
    case "walker-start":
      setState({ running: true, queue: message.urls, index: 0, done: 0, failed: 0, paused: false, tabId: null, note: "Bắt đầu" }).then(openNext);
      break;
    case "walker-stop":
      clearTimeout(timer);
      getState().then((w) => {
        if (w.tabId) chrome.tabs.remove(w.tabId).catch(() => {});
        w.running = false;
        w.tabId = null;
        w.note = "Đã dừng";
        setState(w);
        chrome.action.setBadgeText({ text: "" });
      });
      break;
    default:
      break;
  }
});
