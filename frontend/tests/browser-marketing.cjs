const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const base = process.env.DASHBOARD_URL ?? "http://127.0.0.1:4174/dashboard";

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  const externalWrites = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (["GET", "HEAD", "OPTIONS"].includes(request.method())) return;
    // Policy-installed browser extensions (e.g. ad blockers) issue fetches
    // without Sec-Fetch metadata; genuine page requests always carry it.
    const headers = request.headers();
    if (!headers["sec-fetch-site"] && !headers["origin"]) return;
    if (new URL(request.url()).origin !== new URL(base).origin) {
      externalWrites.push(request.method() + " " + request.url());
    }
  });
  const visit = async (route) => {
    await page.goto(base + (route || "/"));
    await page.locator("h1").waitFor();
    await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
  };
  const routes = ["", "/approvals", "/notifications", "/creatives", "/creative-production", "/performance", "/second-brain", "/workflows", "/exceptions", "/data-sources", "/ai-usage"];

  try {
    for (const route of routes) await visit(route);
    const snapshot = await page.evaluate(async () => (await fetch("/api/v1/dashboard/snapshot")).json());
    assert.equal(typeof snapshot.summary.pending_approvals, "number");
    assert.equal(typeof snapshot.summary.open_exceptions, "number");
    await visit("/workflows");
    await page.getByRole("heading", { name: "AI activity" }).waitFor();
    await visit("/creative-production");
    await page.getByRole("heading", { name: "Create Creative for a Product or Variant" }).waitFor();
    assert.equal(await page.getByRole("combobox", { name: "2. Creative approach" }).count(), 0);
    assert.equal(await page.getByRole("textbox", { name: "Run owner" }).count(), 0);
    await page.getByRole("separator", { name: "Resize output settings" }).waitFor();
    const outputSettings = page.locator(".automation-output-settings");
    assert.equal(await outputSettings.getAttribute("open"), null, "Advanced output settings are collapsed by default.");
    await outputSettings.locator(":scope > summary").click();
    assert.equal(await outputSettings.getAttribute("open"), "", "Clicking Output per Variant reveals advanced settings.");
    const imageOutputs = page.locator(".automation-output-section").filter({ hasText: "Images" });
    assert.equal(await imageOutputs.getAttribute("open"), "", "Image controls are ready when advanced settings are expanded.");
    await page.getByRole("combobox", { name: "Image placement and ratio" }).waitFor();
    await imageOutputs.locator("summary").click();
    assert.equal(await imageOutputs.getAttribute("open"), null, "Clicking an open output summary collapses its controls.");
    await imageOutputs.locator("summary").click();
    assert.equal(await imageOutputs.getAttribute("open"), "", "Clicking a collapsed output summary reveals its controls.");
    assert.equal(await page.getByText("Recent requests").count(), 0);
    await visit("/creative-production/missing");
    await page.getByRole("heading", { name: "Creative automation unavailable" }).waitFor();
    await visit("/workflows");
    assert.equal(await page.getByText("Marketing Creative Closed Loop").count(), 0, "Legacy approval gates stay out of the normal Marketing happy path");
    await visit("/performance");
    await page.getByRole("heading", { name: "Performance", exact: true }).waitFor();
    for (const width of [1920, 1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      for (const route of routes) {
        await visit(route);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, `${route} overflows ${width}px viewport`);
      }
      if (width === 1920) {
        const layout = await page.evaluate(() => {
          const main = document.querySelector(".main-area").getBoundingClientRect();
          const content = document.querySelector(".page-content").getBoundingClientRect();
          const styles = getComputedStyle(document.querySelector(".page-content"));
          return {
            widthRatio: content.width / main.width,
            paddingLeft: Number.parseFloat(styles.paddingLeft),
            paddingRight: Number.parseFloat(styles.paddingRight),
          };
        });
        assert.ok(layout.widthRatio >= 0.98, "Wide layouts should use the available workspace instead of a fixed-width island.");
        assert.ok(layout.paddingLeft >= 22 && layout.paddingRight >= 22, "Wide layouts should retain comfortable side breathing room.");
      }
    }
    assert.deepEqual(errors, [], "No uncaught page errors");
    assert.deepEqual(externalWrites, [], "No mutation requests leave the local application");
    console.log("PASS backend-only Marketing browser smoke: all active routes and responsive layouts; no external writes.");
  } catch (error) {
    console.error("Failed at:", page.url());
    console.error("Page errors:", errors);
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
