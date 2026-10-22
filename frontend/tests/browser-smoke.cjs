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
  const visit = async (route = "") => {
    await page.goto(base + (route || "/"));
    await page.locator("h1").waitFor();
    await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
  };
  const pilot = async () => {
    const result = await page.evaluate(async () => {
      const response = await fetch("/api/v1/dashboard/snapshot");
      return { ok: response.ok, status: response.status, body: await response.json() };
    });
    assert.equal(result.ok, true, `snapshot request failed: ${result.status}`);
    return result.body;
  };

  try {
    await visit();
    const language = page.locator(".language-switcher select");
    await language.selectOption("vi");
    await page.getByRole("heading", { name: "Hôm nay" }).waitFor();
    assert.equal(await page.locator("html").getAttribute("lang"), "vi");
    await page.reload();
    await page.getByRole("heading", { name: "Hôm nay" }).waitFor();
    assert.equal(await language.inputValue(), "vi", "Interface language must persist.");
    await language.selectOption("en");
    await page.getByRole("heading", { name: "Today" }).waitFor();
    await page.getByRole("navigation", { name: "Workspace status" }).waitFor();
    assert.equal(await page.locator(".topbar-context strong").innerText(), "Today");
    assert.equal(await page.getByRole("link", { name: "Start production" }).getAttribute("href"), "/dashboard/creative-production");

    await page.getByRole("button", { name: "Search workspace", exact: true }).click();
    const query = page.getByRole("textbox", { name: "Search query" });
    assert.equal(await query.evaluate((input) => input === document.activeElement), true);
    await page.keyboard.press("Escape");
    await page.keyboard.press("Control+k");
    await page.getByRole("dialog").waitFor();
    await page.keyboard.press("Escape");

    const snapshot = await pilot();
    const approval = snapshot.approvals[0];
    if (approval) {
      await visit("/approvals");
      const row = page.locator(".decision-card").first();
      await row.waitFor();
      assert.equal(await row.locator("code").count(), 0, "Technical IDs must stay out of the decision summary.");
      await row.locator(".decision-card__action").click();
      await page.locator("h1").waitFor();
    }

    if (snapshot.workflows.length) {
      const target = snapshot.workflows.find((item) => item.action_path.includes("?loop=")) ?? snapshot.workflows[0];
      await visit(target.action_path);
      if (target.action_path.includes("?loop=")) {
        assert.equal(new URL(page.url()).searchParams.get("loop"), new URL(target.action_path, base).searchParams.get("loop"));
      }
    }

    await visit("/creatives");
    const creativeResponse = await page.evaluate(async () => {
      const response = await fetch("/api/v1/creative/jobs?decision=all");
      return { ok: response.ok, status: response.status, body: await response.json() };
    });
    assert.equal(creativeResponse.ok, true, `creative jobs request failed: ${creativeResponse.status}`);
    for (const job of creativeResponse.body.items) {
      assert.equal(typeof job.display_title, "string");
      assert.ok(job.display_title.length);
      const card = page.locator(`.creative-card[href$="/creatives/${job.job_id}"]`);
      await card.waitFor();
      const expectedTitle = job.display_title.replace(/:\s*team-provided\s*\(\d+\s+variations?\)/i, " · Team brief");
      assert.equal((await card.locator(".creative-info h2").innerText()).toLocaleLowerCase(), expectedTitle.toLocaleLowerCase());
      if (job.thumbnail_web_url) assert.ok(await card.locator("img").count());
    }

    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      for (const route of ["", "/approvals", "/creatives", "/creative-production", "/performance", "/research-crawler", "/research-library", "/second-brain", "/media-library", "/workflows", "/notifications", "/exceptions", "/data-sources", "/ai-usage"]) {
        await visit(route);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2), true, `${route} overflows at ${width}`);
      }
      if (width === 390) {
        for (const name of ["Open menu", "Search workspace", "Open notifications"]) {
          const element = page.getByRole(name === "Open notifications" ? "link" : "button", { name, exact: true });
          const box = await element.evaluate((node) => ({ width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height }));
          assert.ok(box.width >= 44 && box.height >= 44, `${name} must provide a mobile touch target.`);
        }
        const navigation = page.locator("#workspace-navigation");
        assert.equal(await navigation.evaluate((node) => node.inert), true);
        await page.getByRole("button", { name: "Open menu", exact: true }).click();
        await page.getByRole("dialog", { name: "Workspace navigation" }).waitFor();
        for (let index = 0; index < 12; index++) {
          await page.keyboard.press("Tab");
          assert.equal(await navigation.evaluate((node) => node.contains(document.activeElement)), true);
        }
        await page.keyboard.press("Escape");
      }
    }

    assert.deepEqual(errors, []);
    console.log("PASS backend-only Dashboard smoke: language, search, routed approvals/workflows, Creative summaries, desktop/mobile navigation; no uncaught errors.");
  } catch (error) {
    console.error("Browser errors:", errors);
    console.error("Page:", page.url(), (await page.locator("body").innerText().catch(() => "")).slice(0, 1500));
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
