const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const src = (...parts) => fs.readFileSync(path.resolve(__dirname, "../src", ...parts), "utf8");

test("pilot API owns every backend HTTP request", () => {
  const api = src("services", "pilotApi.ts");
  const http = src("services", "http.ts");
  const sourceRoot = path.resolve(__dirname, "../src");
  const files = [];
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(target);
      else if (/\.(ts|tsx)$/.test(entry.name)) files.push(target);
    }
  };
  visit(sourceRoot);

  assert.match(http, /response = await fetch\(path, init\)/);
  assert.match(api, /sourceBrands.*\/api\/v1\/data-sources\/brands/);
  assert.match(api, /creativeKnowledge[\s\S]*marketing\/creative-knowledge/);
  assert.match(api, /researchCrawls[\s\S]*marketing\/research-crawls/);
  for (const file of files.filter((item) => !item.endsWith(path.join("services", "http.ts")))) {
    assert.doesNotMatch(fs.readFileSync(file, "utf8"), /\bfetch\(/, file);
  }
});

test("the dashboard only routes to research and knowledge pages", () => {
  const app = src("App.tsx");
  const shell = src("components", "AppShell.tsx");

  for (const route of ["research-crawler", "research-library", "second-brain", "notifications"]) {
    assert.match(app, new RegExp(`path="${route}"`));
  }
  assert.match(app, /<Navigate replace to="\/research-crawler" \/>/);
  assert.doesNotMatch(app, /creative-production|creatives|approvals|workflows|data-sources/);
  assert.doesNotMatch(shell, /creative-production|\/creatives|\/approvals|\/data-sources/);
});

test("SecondBrain edits Creative knowledge in place under human review", () => {
  const page = src("pages", "CreativeKnowledge.tsx");
  const styles = src("styles.css");
  const api = src("services", "pilotApi.ts");

  assert.match(api, /creative-knowledge\/bootstrap/);
  assert.match(api, /manifest_id: "creative"/);
  assert.match(api, /decideCreativeKnowledge/);
  assert.match(api, /markCreativeKnowledgeConflict/);
  assert.doesNotMatch(api, /versions\//);
  assert.doesNotMatch(page, /Version history/);
  assert.match(page, /Edit knowledge/);
  assert.match(page, /Propose reusable lesson/);
  assert.match(page, /knowledge_type === "feedback"/);
  assert.match(page, /Used by stages/);
  assert.match(page, /applies_to: proposal\.appliesTo/);
  assert.match(page, /useSplitResize\("aic-second-brain-split"/);
  assert.match(page, /<SplitHandle label="Resize knowledge panels"/);
  assert.match(styles, /\.second-brain-layout\.split-active/);
  assert.match(styles, /\.second-brain-detail \{[^}]*overflow-y: auto/);
  assert.doesNotMatch(page, /autoApprove|auto_approve/);
});
