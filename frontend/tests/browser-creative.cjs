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
  page.on("pageerror", (error) => errors.push(error.message));
  const visit = async (route) => {
    await page.goto(base + route);
    await page.locator("h1").waitFor();
    await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
  };

  try {
    await visit("/creatives");
    const jobs = await page.evaluate(async () => {
      const response = await fetch("/api/v1/creative/jobs?decision=all");
      return { ok: response.ok, status: response.status, body: await response.json() };
    });
    assert.equal(jobs.ok, true, `creative jobs request failed: ${jobs.status}`);
    assert.equal(jobs.body.items.length, jobs.body.total, "Creative list API must expose every persisted job in the browser suite.");
    if (!jobs.body.items.length) {
      await visit("/creatives");
      await page.getByText("No persisted creatives", { exact: false }).waitFor();
      assert.deepEqual(errors, []);
      console.log("PASS Creative browser smoke: empty persisted Creative state is explicit.");
      return;
    }

    await visit("/creatives");
    for (const job of jobs.body.items.slice(0, 3)) {
      const card = page.locator(`.creative-card[href$="/creatives/${job.job_id}"]`);
      await card.waitFor();
      const expectedTitle = job.display_title.replace(/:\s*team-provided\s*\(\d+\s+variations?\)/i, " · Team brief");
      assert.equal((await card.locator(".creative-info h2").innerText()).toLocaleLowerCase(), expectedTitle.toLocaleLowerCase());
      assert.equal(await card.locator(".creative-type").count(), 0, "Summary cards must not make detail requests for thumbnails.");
    }

    const selected = jobs.body.items[0];
    const expectedDetailTitle = selected.display_title.replace(/:\s*team-provided\s*\(\d+\s+variations?\)/i, " · Team brief");
    await page.locator(`.creative-card[href$="/creatives/${selected.job_id}"]`).click();
    await page.getByRole("heading", { name: expectedDetailTitle, exact: false }).waitFor();
    const detail = await page.evaluate(async (jobId) => {
      const response = await fetch(`/api/v1/creative/jobs/${jobId}`);
      return { ok: response.ok, status: response.status, body: await response.json() };
    }, selected.job_id);
    assert.equal(detail.ok, true, `creative job request failed: ${detail.status}`);
    assert.ok(detail.body.versions.length >= selected.version_count);
    await page.getByText("Context and evidence", { exact: true }).waitFor();

    await page.setViewportSize({ width: 390, height: 844 });
    await visit("/creatives");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, "Creative list must not overflow mobile.");
    assert.deepEqual(errors, []);
    console.log("PASS Creative browser smoke: summary titles/thumbnails, exact detail identity, mobile layout; no uncaught errors.");
  } catch (error) {
    console.error("Browser errors:", errors);
    console.error("Page:", page.url(), (await page.locator("body").innerText().catch(() => "")).slice(0, 1500));
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
