// Runs in the page context. Passively copies JSON responses the page itself requests
// (product detail, reviews...) and hands them to content.js. It does not change any
// request and does not touch automation markers.
(() => {
  const MAX_BYTES = 3_000_000;
  const post = (url, status, text) => {
    if (!text || text.length > MAX_BYTES) return;
    window.postMessage({ source: "aic-hook", kind: "json", url: String(url), status, body: text }, "*");
  };

  const originalFetch = window.fetch;
  window.fetch = async function (...args) {
    const response = await originalFetch.apply(this, args);
    try {
      const type = response.headers.get("content-type") || "";
      if (type.includes("json")) {
        const url = typeof args[0] === "string" ? args[0] : args[0]?.url || response.url;
        response.clone().text().then((text) => post(url, response.status, text)).catch(() => {});
      }
    } catch (_) {
      // never break the page
    }
    return response;
  };

  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.addEventListener("load", () => {
      try {
        const type = this.getResponseHeader("content-type") || "";
        if (type.includes("json") && (this.responseType === "" || this.responseType === "text")) {
          post(url, this.status, this.responseText);
        }
      } catch (_) {
        // ignore
      }
    });
    return open.call(this, method, url, ...rest);
  };
})();
