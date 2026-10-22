const { spawn } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");

const dashboardUrl = process.env.DASHBOARD_URL ?? "http://127.0.0.1:4174/dashboard";
const dashboardReadyUrl = `${dashboardUrl.replace(/\/+$/, "")}/`;
const scripts = ["browser-smoke.cjs", "browser-creative.cjs", "browser-marketing.cjs"];

function run(commandName, args, environment) {
  return new Promise((resolve, reject) => {
    const child = spawn(commandName, args, { cwd: process.cwd(), env: environment, stdio: "inherit" });
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (code === 0) resolve();
      else reject(new Error(`${commandName} ${args.join(" ")} exited with ${signal ?? code}`));
    });
  });
}

async function waitForDashboard() {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (await dashboardIsReady()) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Dashboard did not become ready at ${dashboardReadyUrl}`);
}

function dashboardIsReady() {
  return new Promise((resolve) => {
    const request = http.get(dashboardReadyUrl, (response) => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 400);
    });
    request.setTimeout(2_000, () => request.destroy());
    request.on("error", () => resolve(false));
  });
}

async function stop(child) {
  if (child.exitCode !== null || child.killed) return;
  child.kill();
  await new Promise((resolve) => child.once("exit", resolve));
}

async function main() {
  if (process.env.DASHBOARD_URL) {
    for (const script of scripts) await run(process.execPath, [`tests/${script}`], process.env);
    return;
  }

  const vite = spawn(
    process.execPath,
    [
      path.join(process.cwd(), "node_modules", "vite", "bin", "vite.js"),
      "--host",
      "127.0.0.1",
      "--port",
      "4174",
      "--strictPort",
    ],
    {
      cwd: process.cwd(),
      env: process.env,
      stdio: "inherit",
    },
  );
  try {
    await waitForDashboard();
    for (const script of scripts) {
      await run(process.execPath, [`tests/${script}`], { ...process.env, DASHBOARD_URL: dashboardUrl });
    }
  } finally {
    await stop(vite);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
