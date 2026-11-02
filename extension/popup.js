const enabled = document.getElementById("enabled");
const status = document.getElementById("status");
const walkerBox = document.getElementById("walker");

const refresh = () =>
  chrome.storage.local.get({ enabled: false, sent: 0, error: "", walker: null }, (s) => {
    enabled.checked = Boolean(s.enabled);
    status.textContent = s.error ? `Lỗi gửi: ${s.error}` : `Đã gửi ${s.sent} gói về collector`;
    const w = s.walker;
    walkerBox.textContent = w
      ? `${w.running ? (w.paused ? "TẠM DỪNG - cần bạn" : "Đang chạy") : "Không chạy"}: ${w.index}/${w.queue.length} | OK ${w.done} | lỗi ${w.failed} | ${w.note}`
      : "";
  });

enabled.addEventListener("change", () => chrome.storage.local.set({ enabled: enabled.checked }));
document.getElementById("capture").addEventListener("click", () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) chrome.tabs.sendMessage(tabs[0].id, { type: "capture-now" });
  });
});
document.getElementById("harvest").addEventListener("click", () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) chrome.tabs.sendMessage(tabs[0].id, { type: "harvest", rounds: 15 });
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
const API = "http://127.0.0.1:8000/api/v1/products";
document.getElementById("pins").addEventListener("click", async () => {
  const searches = Number(document.getElementById("pin-searches").value) || 200;
  const maxImages = Number(document.getElementById("pin-images").value) || 0;
  try {
    const items = await (await fetch(`${API}/reference-queue?limit=${searches}`)).json();
    if (!items.length) {
      walkerBox.textContent = "Chưa có từ khóa nào đã duyệt (hoặc đã crawl hết).";
      return;
    }
    const meta = Object.fromEntries(items.map((item) => [item.url, { product_type: item.product_type, query: item.query, max_images: maxImages }]));
    chrome.runtime.sendMessage({ type: "walker-start", urls: items.map((item) => item.url), meta });
  } catch (error) {
    walkerBox.textContent = `Không gọi được API: ${error}`;
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
