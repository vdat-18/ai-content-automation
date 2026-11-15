const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const src = (...parts) => fs.readFileSync(path.resolve(__dirname, "../src", ...parts), "utf8");

const sourceFiles = () => {
  const files = [];
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(target);
      else if (/\.(ts|tsx)$/.test(entry.name)) files.push(target);
    }
  };
  visit(path.resolve(__dirname, "../src"));
  return files;
};

test("only the http service talks to the backend", () => {
  const http = src("services", "http.ts");
  assert.match(http, /response = await fetch\(path, init\)/);
  for (const file of sourceFiles().filter((item) => !item.endsWith(path.join("services", "http.ts")))) {
    assert.doesNotMatch(fs.readFileSync(file, "utf8"), /\bfetch\(/, file);
  }
});

test("the app has four menu pages, the studio and redirects for old links", () => {
  const app = src("App.tsx");
  const shell = src("components", "Shell.tsx");
  for (const route of ["products", "videos", "studio/:productId", "memory", "notifications"]) {
    assert.match(app, new RegExp(`path="${route}"`));
  }
  for (const [from, to] of [["briefs", "/videos"], ["outputs", "/videos"], ["second-brain", "/memory"]]) {
    assert.match(app, new RegExp(`path="${from}" element=\\{<Navigate replace to="${to}" />`));
  }
  for (const label of ["Home", "Products", "My videos", "AI memory"]) assert.match(shell, new RegExp(`label: "${label}"`));
});

test("the interface is English only and has no translation layer", () => {
  for (const file of sourceFiles()) {
    assert.doesNotMatch(fs.readFileSync(file, "utf8"), /useI18n|I18nProvider/, file);
  }
});

test("a rule the AI proposes waits for a human before it is used", () => {
  const rules = src("pages", "memory", "RulesTab.tsx");
  const api = src("services", "pilotApi.ts");
  assert.match(api, /creative-knowledge\/bootstrap/);
  assert.match(api, /retireCreativeKnowledge/);
  assert.match(rules, /Approve all/);
  assert.match(rules, /decideCreativeKnowledge\(saved\.knowledge_id, "approved"/);
  assert.doesNotMatch(rules, /autoApprove|auto_approve/);
});

test("the studio pauses for image review before the video is paid for", () => {
  const idea = src("pages", "studio", "IdeaStep.tsx");
  const images = src("pages", "studio", "ImagesStep.tsx");
  const hook = src("hooks", "useStudio.ts");
  assert.match(idea, /until: "images"/);
  assert.match(images, /until: "images"/);
  assert.match(images, /until: "video"/);
  assert.match(images, /Approve every scene to continue/);
  assert.match(hook, /pipeline/);
});
