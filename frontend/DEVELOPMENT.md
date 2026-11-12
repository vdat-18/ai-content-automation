# Dashboard

This Dashboard renders records persisted by the local Python APIs. It does not publish
anything, send messages, or fall back to browser mock data.

## Active Routes

- `/` (home): videos in progress and finished
- `/products`: collected products; pick one to make a video
- `/studio/:productId`: the steps of one video (Idea, Script, Images, Finish)
- `/videos`: every video, finished or in progress
- `/memory`: rules the AI follows and reference scenes
- `/notifications`: runs that ended or need a look

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

## Tests

The Node suites check the routing, the HTTP boundary and the research and
SecondBrain pages:

```powershell
pnpm --dir frontend test
```

## Data Behavior

- `services/http.ts` and `services/pilotApi.ts` are the only HTTP boundary.
- Active route pages use React Query hooks backed by pilot APIs.
- Browser-local mock workflow modules and their legacy-only tests were removed;
  active pages use persisted backend state only.

Use the VI/EN selector to localize interface copy, status labels, dates, and
numbers. Source evidence, briefs, feedback, and generated marketing content keep
their original language.
