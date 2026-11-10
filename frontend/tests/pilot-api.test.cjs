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
  assert.match(api, /creativeKnowledge[\s\S]*marketing\/creative-knowledge/);
  assert.match(api, /notifications[\s\S]*\/api\/v1\/notifications/);
  for (const file of files.filter((item) => !item.endsWith(path.join("services", "http.ts")))) {
    assert.doesNotMatch(fs.readFileSync(file, "utf8"), /\bfetch\(/, file);
  }
});

test("the dashboard only routes to affiliate content and knowledge pages", () => {
  const app = src("App.tsx");
  const shell = src("components", "AppShell.tsx");

  for (const route of ["products", "references", "briefs", "second-brain", "notifications"]) {
    assert.match(app, new RegExp(`path="${route}"`));
  }
  assert.match(app, /<Navigate replace to="\/products" \/>/);
  assert.doesNotMatch(app, /creative-production|creatives|approvals|workflows|data-sources|research-/);
  assert.doesNotMatch(shell, /creative-production|\/creatives|\/approvals|\/data-sources/);
});

test("SecondBrain is a simple rule list where proposals wait for a human", () => {
  const page = src("pages", "CreativeKnowledge.tsx");
  const api = src("services", "pilotApi.ts");

  assert.match(api, /creative-knowledge\/bootstrap/);
  assert.match(api, /manifest_id: manifestId/);
  assert.match(api, /decideCreativeKnowledge/);
  assert.match(api, /retireCreativeKnowledge/);
  assert.match(page, /Approve all/);
  assert.match(page, /pilotApi\.proposeCreativeKnowledge/);
  assert.match(page, /decideCreativeKnowledge\(saved\.knowledge_id, "approved"/);
  assert.doesNotMatch(page, /autoApprove|auto_approve/);
});
