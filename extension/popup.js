// The top-level categories of TikTok Shop VN (name and id as in the links of its home page)
const CATEGORIES = [
  ["womenswear-underwear", 601152],
  ["phones-electronics", 601739],
  ["fashion-accessories", 605248],
  ["menswear-underwear", 824328],
  ["home-supplies", 600001],
  ["beauty-personal-care", 601450],
  ["shoes", 601352],
  ["sports-outdoor", 603014],
  ["luggage-bags", 824584],
  ["toys-hobbies", 604206],
  ["automotive-motorcycle", 605196],
  ["kids-fashion", 802184],
  ["kitchenware", 600024],
  ["computers-office-equipment", 601755],
  ["baby-maternity", 602284],
  ["tools-hardware", 604579],
  ["textiles-soft-furnishings", 600154],
  ["pet-supplies", 602118],
  ["home-improvement", 604968],
  ["food-beverages", 700437],
  ["muslim-fashion", 601303],
  ["books-magazines-audio", 801928],
  ["household-appliances", 600942],
  ["health", 700645],
  ["furniture", 604453],
  ["jewelry-accessories-derivatives", 953224],
  ["collectibles", 951432],
  ["pre-owned", 856720],
];
const enabled = document.getElementById("enabled");
const status = document.getElementById("status");
const walkerBox = document.getElementById("walker");
const pinBox = document.getElementById("pin-walker");

const sendToTab = (tabId, message) =>
  chrome.tabs.sendMessage(tabId, message, () => {
    if (chrome.runtime.lastError) status.textContent = "Open a TikTok or Pinterest page, then reload the tab (F5).";
  });

// One walker runs at a time, and its progress shows only in the section of the site it belongs to.
const paint = ({ box, bar, stop }, w, mine, describe) => {
  const total = mine ? w.queue.length : 0;
  box.textContent = mine ? describe(w) : "";
  bar.hidden = !total;
  bar.firstElementChild.style.width = total ? `${Math.round(((w.done + w.failed) / total) * 100)}%` : "0%";
  stop.hidden = !(mine && w.running);
};
const state = (w) => (w.running ? (w.paused ? "PAUSED, needs you" : "Running") : "Stopped");
const tiktokText = (w) =>
  `${state(w)}: ${w.done + w.failed}/${w.queue.length} ${w.kind === "category" ? "categories" : "products"} | ${Object.keys(w.active || {}).length} tabs | OK ${w.done} | failed ${w.failed}\n${w.note}`;
const pinterestText = (w) =>
  `${state(w)}: keywords ${w.done + w.failed}/${w.queue.length} | OK ${w.done} | failed ${w.failed}${w.detail ? `\nCollecting ${w.detail}` : `\n${w.note}`}`;

const STUDIO = "http://localhost:8080/dashboard/studio";
const showCapture = (capture) => {
  const note = document.getElementById("send-note");
  const link = document.getElementById("open-studio");
  link.hidden = true;
  if (!capture) return;
  if (capture.stored === "detail") {
    note.textContent = "Sent. The product is saved.";
    link.href = `${STUDIO}/${capture.productId}`;
    link.hidden = false;
  } else if (capture.stored === "ignored") {
    note.textContent = "This page has no product data. Open a product page, wait for it to load, then press the button again.";
  } else {
    note.textContent = `The collector did not accept it: ${capture.reason || "unknown error"}`;
  }
};

const refresh = () =>
  chrome.storage.local.get({ enabled: false, sent: 0, error: "", walker: null, autoNote: "", lastCapture: null }, (s) => {
    showCapture(s.lastCapture);
    const w = s.walker;
    document.getElementById("auto-note").textContent = w?.kind === "pinterest" && w.running ? "" : s.autoNote;
    enabled.checked = Boolean(s.enabled);
    status.textContent = s.error ? `Send error: ${s.error}` : `Sent ${s.sent} packages to the collector`;
    const pinterest = w?.kind === "pinterest";
    paint({ box: walkerBox, bar: document.getElementById("walker-bar"), stop: document.getElementById("stop") }, w, Boolean(w) && !pinterest, tiktokText);
    paint({ box: pinBox, bar: document.getElementById("pin-bar"), stop: document.getElementById("pin-stop") }, w, Boolean(w) && pinterest, pinterestText);
    const busy = Boolean(w?.running);
    for (const id of ["auto", "crawl-all", "start", "pins"]) {
      const button = document.getElementById(id);
      button.disabled = busy;
      button.title = busy ? "A collection is already running; wait or press Stop" : "";
    }
  });

const version = document.getElementById("version");
if (version) version.textContent = `v${chrome.runtime.getManifest().version}`;
enabled.addEventListener("change", () => chrome.storage.local.set({ enabled: enabled.checked }));
document.getElementById("send-one").addEventListener("click", () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (!tab?.id || !(tab.url || "").includes("/pdp/")) {
      document.getElementById("send-note").textContent = "Open a product page on TikTok Shop first.";
      return;
    }
    document.getElementById("send-note").textContent = "Sending...";
    document.getElementById("open-studio").hidden = true;
    chrome.storage.local.set({ lastCapture: null }, () => sendToTab(tab.id, { type: "capture-now" }));
  });
});
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
  chrome.storage.local.set({ autoNote: "Scrolling the list..." });
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) sendToTab(tabs[0].id, { type: "harvest", rounds: auto.limit ? 80 : 400, auto });
  });
});
document.getElementById("crawl-all").addEventListener("click", () => {
  const concurrency = Number(document.getElementById("auto-tabs").value) || 5;
  const urls = [
    "https://shop.tiktok.com/vn", // the "Bán chạy nhất" list of the home page
    ...CATEGORIES.map(([slug, id]) => `https://shop.tiktok.com/vn/c/${slug}/${id}`),
  ];
  const meta = Object.fromEntries(urls.map((url) => [url, { category: true }]));
  chrome.storage.local.set({ autoNote: `Collecting ${urls.length} categories, ${concurrency} at a time, then the product pages.` });
  chrome.runtime.sendMessage({ type: "walker-start", kind: "category", urls, meta, concurrency, followUp: { concurrency } });
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
      walkerBox.textContent = "The collector has no links left to collect.";
      return;
    }
    chrome.runtime.sendMessage({ type: "walker-start", urls });
  } catch (error) {
    walkerBox.textContent = `Could not reach the collector: ${error}`;
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
      pinBox.textContent = "No approved keywords left to collect.";
      return;
    }
    const meta = Object.fromEntries(items.map((item) => [item.url, { product_type: item.product_type, query: item.query, max_images: maxImages }]));
    chrome.runtime.sendMessage({ type: "walker-start", kind: "pinterest", urls: items.map((item) => item.url), meta });
  } catch (error) {
    pinBox.textContent = `Could not reach the API: ${error}`;
  }
});
document.getElementById("xlsx").addEventListener("click", () => chrome.tabs.create({ url: `${API}/export?format=xlsx` }));
document.getElementById("json").addEventListener("click", () => chrome.tabs.create({ url: `${API}/export?format=json` }));
document.getElementById("media").addEventListener("click", async () => {
  const box = document.getElementById("media-status");
  box.textContent = "Downloading...";
  try {
    const r = await (await fetch(`${API}/media/download`, { method: "POST" })).json();
    box.textContent = `New ${r.downloaded}, duplicates ${r.duplicates}, already had ${r.skipped}, failed ${r.failed}`;
  } catch (error) {
    box.textContent = `Error: ${error}`;
  }
});
chrome.storage.onChanged.addListener(refresh);
refresh();
