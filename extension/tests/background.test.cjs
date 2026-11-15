// The background worker runs 200 times faster than real time here, so minutes of waiting take milliseconds.
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const { test } = require("node:test");
const assert = require("node:assert/strict");

const SPEED = 200; // 1 real ms = 200 virtual ms
const t0 = Date.now();
const vnow = () => t0 + (Date.now() - t0) * SPEED;

function makeWorld(fetchImpl = async () => ({ json: async () => [] })) {
  const store = {};
  let nextTab = 100;
  const opened = [];
  const removed = [];
  const notes = [];
  const refusals = { create: 0 };
  let handler;
  const chrome = {
    storage: {
      local: {
        get: (defaults) => Promise.resolve(Object.fromEntries(Object.entries(defaults).map(([k, v]) => [k, store[k] ?? v]))),
        set: (values) => {
          Object.assign(store, JSON.parse(JSON.stringify(values)));
          return Promise.resolve();
        },
      },
    },
    tabs: {
      create: async ({ url }) => {
        if (refusals.create-- > 0) throw new Error("Tabs cannot be edited right now (user may be dragging a tab).");
        const id = nextTab++;
        opened.push({ id, url, at: vnow() });
        return { id };
      },
      remove: (id) => {
        removed.push(id);
        return Promise.resolve();
      },
      update: () => Promise.resolve(),
    },
    action: { setBadgeText: () => {} },
    notifications: { create: (options) => notes.push(options.message) },
    runtime: { onMessage: { addListener: (listener) => { handler = listener; } } },
  };
  const FakeDate = class extends Date {
    static now() {
      return vnow();
    }
  };
  const context = {
    chrome,
    fetch: fetchImpl,
    console,
    Date: FakeDate,
    setTimeout: (callback, ms) => setTimeout(callback, Math.max(0, ms / SPEED)),
    clearTimeout,
    Math,
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "background.js"), "utf8"), context);
  const send = (message, tab) =>
    new Promise((resolve) => {
      const returned = handler(message, { tab: tab ? { id: tab } : undefined }, resolve);
      if (!returned) resolve();
    });
  return { store, opened, removed, notes, refusals, send };
}

const wait = (virtualMs) => new Promise((resolve) => setTimeout(resolve, virtualMs / SPEED));
const urls = (count) => Array.from({ length: count }, (_, i) => `https://shop.tiktok.com/vn/pdp/s/${1000 + i}`);

test("three captcha waves stop the run and block a new one for a while", async () => {
  const w = makeWorld();
  await w.send({ type: "walker-start", urls: urls(20), concurrency: 3 });
  await wait(20_000);
  for (let i = 0; i < 3; i += 1) {
    const tab = Object.keys(w.store.walker.active)[0];
    await w.send({ type: "challenge", reason: "captcha" }, Number(tab));
    if (i < 2) {
      await w.send({ type: "resumed" });
      await wait(40_000);
    }
  }
  await wait(1000);
  assert.ok(w.store.walker.running === false && /3 captchas/.test(w.store.walker.note), w.store.walker.note);
  await w.send({ type: "walker-start", urls: urls(5), concurrency: 1 });
  await wait(500);
  assert.ok(w.store.walker.running === false && /Wait about/.test(w.store.autoNote), w.store.autoNote);
});

test("captchas on several tabs at once count as one wave and double the delay once", async () => {
  const w = makeWorld();
  await w.send({ type: "walker-start", urls: urls(20), concurrency: 3 });
  await wait(20_000);
  const before = w.store.walker.delayMs;
  for (const tab of Object.keys(w.store.walker.active)) await w.send({ type: "challenge", reason: "captcha" }, Number(tab));
  await wait(500);
  assert.equal(w.store.captchaLog.length, 1);
  const after = w.store.walker.delayMs;
  assert.ok(after >= before * 2 * 0.75 - 1 && after <= before * 2 * 1.25 + 1, `${before} -> ${after}`);
  assert.equal(w.store.walker.paused, true);
  await wait(15 * 60_000 + 5_000);
  assert.ok(w.store.walker.running === false && /15 minutes/.test(w.store.walker.note), w.store.walker.note);
});

test("a login wall is not counted as a captcha", async () => {
  const w = makeWorld();
  await w.send({ type: "walker-start", urls: urls(5), concurrency: 1 });
  await wait(2_000);
  await w.send({ type: "challenge", reason: "login" }, Number(Object.keys(w.store.walker.active)[0]));
  assert.ok(!(w.store.captchaLog || []).length);
});

test("never more than twenty pages in any minute, and every page is read", async () => {
  const w = makeWorld();
  await w.send({ type: "walker-start", urls: urls(24), concurrency: 5 });
  await new Promise((resolve) => setTimeout(resolve, 50));
  const stopAt = Date.now() + 8000;
  while (Date.now() < stopAt && w.store.walker.running) {
    for (const tab of Object.keys(w.store.walker.active)) await w.send({ type: "page-done", ok: true }, Number(tab));
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  const times = w.opened.map((entry) => entry.at);
  let maxIn60 = 0;
  for (const start of times) maxIn60 = Math.max(maxIn60, times.filter((at) => at >= start && at < start + 60_000).length);
  assert.ok(maxIn60 <= 20, `max in any 60s = ${maxIn60}`);
  assert.equal(w.store.walker.done, 24);
});

test("the popup learns what happened to the product page that was just sent", async () => {
  const answer = (body) => async () => ({ ok: true, json: async () => body });
  const saved = makeWorld(answer({ stored: "detail", product_id: "42" }));
  await saved.send({ type: "ingest", payload: { kind: "page", url: "https://shop.tiktok.com/vn/pdp/s/42" } });
  await wait(100);
  assert.deepEqual(saved.store.lastCapture, { stored: "detail", productId: "42", reason: "" });

  const empty = makeWorld(answer({ stored: "ignored", reason: "no product data in page" }));
  await empty.send({ type: "ingest", payload: { kind: "page", url: "https://shop.tiktok.com/vn/pdp/s/43" } });
  await wait(100);
  assert.equal(empty.store.lastCapture.stored, "ignored");
  assert.equal(empty.store.lastCapture.reason, "no product data in page");

  const listing = makeWorld(answer({ stored: "listing", count: 3 }));
  await listing.send({ type: "ingest", payload: { kind: "json", url: "https://shop.tiktok.com/api/feed" } });
  await wait(100);
  assert.equal(listing.store.lastCapture, undefined);
});

test("after the last category the product pages that are still missing are read", async () => {
  const calls = [];
  const products = ["https://shop.tiktok.com/vn/pdp/s/1", "https://shop.tiktok.com/vn/pdp/s/2"];
  const w = makeWorld(async (url) => {
    calls.push(String(url));
    return { ok: true, json: async () => (String(url).includes("/queue") ? products : []) };
  });
  const categories = ["https://shop.tiktok.com/vn/c/food-beverages/700437", "https://shop.tiktok.com/vn/c/health/700645"];
  const meta = Object.fromEntries(categories.map((url) => [url, { category: true }]));
  await w.send({ type: "walker-start", kind: "category", urls: categories, meta, concurrency: 5, followUp: { concurrency: 5 } });
  await new Promise((resolve) => setTimeout(resolve, 50));
  const stopAt = Date.now() + 8000;
  while (Date.now() < stopAt && !calls.some((url) => url.includes("/queue"))) {
    for (const tab of Object.keys(w.store.walker.active)) await w.send({ type: "page-done", ok: true }, Number(tab));
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  await wait(60_000);
  assert.ok(calls.some((url) => url.includes("/queue?limit=100000")), calls.join(" "));
  assert.equal(w.store.walker.kind, "tiktok");
  assert.equal(w.store.walker.concurrency, 5);
  assert.deepEqual(w.opened.slice(0, 2).map((entry) => entry.url), categories);
  assert.deepEqual(w.opened.slice(2, 4).map((entry) => entry.url), products);
});

test("a Pinterest run and a TikTok run do not disturb each other", async () => {
  const w = makeWorld();
  const pins = [1, 2, 3].map((i) => `https://www.pinterest.com/search/pins/?q=k${i}`);
  await w.send({ type: "walker-start", urls: urls(6), concurrency: 2 });
  await w.send({ type: "walker-start", kind: "pinterest", urls: pins, meta: {}, concurrency: 1 });
  await wait(20_000);
  assert.ok(w.store.walker.running && w.store.pinWalker.running);
  assert.ok(Object.keys(w.store.pinWalker.active).length >= 1);

  // a captcha on a TikTok tab pauses TikTok only
  await w.send({ type: "challenge", reason: "captcha" }, Number(Object.keys(w.store.walker.active)[0]));
  await wait(500);
  assert.equal(w.store.walker.paused, true);
  assert.equal(w.store.pinWalker.paused, false);
  assert.equal(w.store.captchaLog.length, 1);

  // a Pinterest page that finishes counts for Pinterest, and Stop on TikTok leaves Pinterest running
  await w.send({ type: "page-done", ok: true }, Number(Object.keys(w.store.pinWalker.active)[0]));
  await wait(500);
  assert.equal(w.store.pinWalker.done, 1);
  assert.equal(w.store.walker.done, 0);
  await w.send({ type: "walker-stop", lane: "tiktok" });
  await wait(500);
  assert.equal(w.store.walker.running, false);
  assert.equal(w.store.pinWalker.running, true);
});

test("a tab that Chrome refuses to open while the user drags a tab is opened again", async () => {
  const w = makeWorld();
  w.refusals.create = 2;
  await w.send({ type: "walker-start", urls: urls(2), concurrency: 2 });
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.deepEqual(w.opened.map((entry) => entry.url), urls(2));
  assert.equal(w.store.walker.running, true);
});
