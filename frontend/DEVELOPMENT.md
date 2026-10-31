# Dashboard

This Dashboard renders records persisted by the local Python APIs. It does not publish
anything, send messages, or fall back to browser mock data.

## Active Routes

- `/creative-production` (home): create images and videos for a product, review runs
- `/creatives`: generated images and videos, versions and audit details
- `/approvals`: approval inbox
- `/workflows`: Creative loop and durable command status
- `/research-crawler`: collect references from a public results URL
- `/research-library`: review and approve references for Creative
- `/second-brain`: creative rules and knowledge
- `/data-sources`: sandbox product sources and manual sync
- `/notifications`: notifications

Unknown URLs show a "Page not found" panel.

## Run And Check

From the repository root:

```powershell
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev -- --port 4174
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
```

Open `http://localhost:4174/dashboard/` (keep the trailing slash). Vite proxies
`/api`, `/health`, and `/artifacts` to FastAPI. If the backend is unavailable,
active operational surfaces show the API error rather than synthetic records.

## Docker Development

```powershell
docker compose --env-file deploy/.env -f deploy/compose.yaml up --build --detach
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm smoke
```

Open `http://localhost:8080/dashboard/`. For Vite HMR and Uvicorn reload:

```powershell
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.dev.yaml up --build
```

## Browser Tests

The Node suites cover active backend-only routes, Creative summaries, workflow
deep links, responsive layouts, and navigation focus:

```powershell
$env:DASHBOARD_URL = "http://127.0.0.1:4174/dashboard"
pnpm --dir frontend test:browser
```

The browser suites require the `playwright` package and installed Chrome in an
isolated browser context. If Playwright is supplied by a shared runtime, set
`NODE_PATH` to that runtime's Node package directory. Optionally set
`DASHBOARD_SCREENSHOTS` to an existing output directory for screenshots.

## Data Behavior

- `services/http.ts` and `services/pilotApi.ts` are the only HTTP boundary.
- Active route pages use React Query hooks backed by pilot APIs.
- Browser-local mock workflow modules and their legacy-only tests were removed;
  active pages use persisted backend state only.
- Approval actions are business gates; no action publishes a post or writes to a
  source system.
- Creative cards use API `display_title` and `thumbnail_web_url`; the list does
  not make a detail request per thumbnail.
- Workflow IDs and step references are grouped under `Technical details`.
- Creative version hashes and prompt/rubric/policy/workflow versions are in
  collapsible `Audit details`.

Use the VI/EN selector to localize interface copy, status labels, dates, and
numbers. Source evidence, briefs, feedback, and generated marketing content keep
their original language.

## Cleanup Boundary

`frontend/src/marketing` and browser-local storage modules retain code needed by
existing tests and historical browser scenarios. They are intentionally not used
as fallback data for active backend-only routes. Removing them safely requires a
separate test/test-data migration.
