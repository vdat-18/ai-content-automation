const enabled = document.getElementById("enabled");
const status = document.getElementById("status");
const walkerBox = document.getElementById("walker");
const pinBox = document.getElementById("pin-walker");

const sendToTab = (tabId, message) =>
  chrome.tabs.sendMessage(tabId, message, () => {
    if (chrome.runtime.lastError) status.textContent = "Hãy mở trang TikTok/Pinterest rồi tải lại tab (F5).";
  });

// One walker runs at a time, and its progress shows only in the section of the site it belongs to.
const paint = ({ box, bar, stop }, w, mine, describe) => {
  const total = mine ? w.queue.length : 0;
  box.textContent = mine ? describe(w) : "";
  bar.hidden = !total;
  bar.firstElementChild.style.width = total ? `${Math.round(((w.done + w.failed) / total) * 100)}%` : "0%";
  stop.hidden = !(mine && w.running);
};
const state = (w) => (w.running ? (w.paused ? "TẠM DỪNG, cần bạn" : "Đang chạy") : "Đã dừng");
const tiktokText = (w) =>
  `${state(w)}: ${w.done + w.failed}/${w.queue.length} sản phẩm | ${Object.keys(w.active || {}).length} tab | OK ${w.done} | lỗi ${w.failed}\n${w.note}`;
const pinterestText = (w) =>
  `${state(w)}: từ khóa ${w.done + w.failed}/${w.queue.length} | OK ${w.done} | lỗi ${w.failed}${w.detail ? `\nĐang thu ${w.detail}` : `\n${w.note}`}`;

const refresh = () =>
  chrome.storage.local.get({ enabled: false, sent: 0, error: "", walker: null, autoNote: "" }, (s) => {
    const w = s.walker;
    document.getElementById("auto-note").textContent = w?.kind === "pinterest" && w.running ? "" : s.autoNote;
    enabled.checked = Boolean(s.enabled);
    status.textContent = s.error ? `Lỗi gửi: ${s.error}` : `Đã gửi ${s.sent} gói về collector`;
    const pinterest = w?.kind === "pinterest";
    paint({ box: walkerBox, bar: document.getElementById("walker-bar"), stop: document.getElementById("stop") }, w, Boolean(w) && !pinterest, tiktokText);
    paint({ box: pinBox, bar: document.getElementById("pin-bar"), stop: document.getElementById("pin-stop") }, w, Boolean(w) && pinterest, pinterestText);
    const busy = Boolean(w?.running);
    for (const id of ["auto", "start", "pins"]) {
      const button = document.getElementById(id);
      button.disabled = busy;
      button.title = busy ? "Đang có một lượt thu thập chạy, hãy đợi hoặc bấm Dừng" : "";
    }
  });

const version = document.getElementById("version");
if (version) version.textContent = `v${chrome.runtime.getManifest().version}`;
enabled.addEventListener("change", () => chrome.storage.local.set({ enabled: enabled.checked }));
document.getElementById("capture").addEventListener("click", () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) sendToTab(tabs[0].id, { type: "capture-now" });
  });
});
document.getElementById("auto").addEventListener("click", () => {
  const auto = {
    concurrency: Number(document.getElementById("auto-tabs").value) || 3,
    limit: Number(document.getElementById("auto-limit").value) || 0, // 0 = every product found
  };
  chrome.storage.local.set({ autoNote: "Đang cuộn lấy danh sách..." });
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) sendToTab(tabs[0].id, { type: "harvest", rounds: auto.limit ? 80 : 400, auto });
  });
});
document.getElementById("harvest").addEventListener("click", () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) sendToTab(tabs[0].id, { type: "harvest", rounds: 15 });
  });
});
document.getElementById("start").addEventListener("click", async () => {
  const count = Number(document.getElementById("count").value) || 20;
  try {
    const response = await fetch(`http://127.0.0.1:8000/api/v1/products/queue?limit=${count}`);
    const urls = await response.json();
    if (!urls.length) {
      walkerBox.textContent = "Collector không có link nào chưa thu.";
      return;
    }
    chrome.runtime.sendMessage({ type: "walker-start", urls });
  } catch (error) {
    walkerBox.textContent = `Không gọi được collector: ${error}`;
  }
});
document.getElementById("stop").addEventListener("click", () => chrome.runtime.sendMessage({ type: "walker-stop" }));
document.getElementById("pin-stop").addEventListener("click", () => chrome.runtime.sendMessage({ type: "walker-stop" }));
const API = "http://127.0.0.1:8000/api/v1/products";
document.getElementById("pins").addEventListener("click", async () => {
  chrome.storage.local.set({ autoNote: "" });
  const searches = Number(document.getElementById("pin-searches").value) || 200;
  const maxImages = Number(document.getElementById("pin-images").value) || 0;
  try {
    const items = await (await fetch(`${API}/reference-queue?limit=${searches}`)).json();
    if (!items.length) {
      pinBox.textContent = "Chưa có từ khóa nào đã duyệt (hoặc đã crawl hết).";
      return;
    }
    const meta = Object.fromEntries(items.map((item) => [item.url, { product_type: item.product_type, query: item.query, max_images: maxImages }]));
    chrome.runtime.sendMessage({ type: "walker-start", kind: "pinterest", urls: items.map((item) => item.url), meta });
  } catch (error) {
    pinBox.textContent = `Không gọi được API: ${error}`;
  }
});
document.getElementById("xlsx").addEventListener("click", () => chrome.tabs.create({ url: `${API}/export?format=xlsx` }));
document.getElementById("json").addEventListener("click", () => chrome.tabs.create({ url: `${API}/export?format=json` }));
document.getElementById("media").addEventListener("click", async () => {
  const box = document.getElementById("media-status");
  box.textContent = "Đang tải...";
  try {
    const r = await (await fetch(`${API}/media/download`, { method: "POST" })).json();
    box.textContent = `Mới ${r.downloaded}, trùng ${r.duplicates}, đã có ${r.skipped}, lỗi ${r.failed}`;
  } catch (error) {
    box.textContent = `Lỗi: ${error}`;
  }
});
chrome.storage.onChanged.addListener(refresh);
refresh();
