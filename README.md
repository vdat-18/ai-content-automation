**English** · [Tiếng Việt](README.vi.md)

# AI Content Automation

Turns one TikTok Shop product into a finished Vietnamese affiliate video ad: script, scene images,
video clips, natural voice-over, stitched 9:16 video, captions and hashtags. The user reads the
**script** and approves every **image** before any video is paid for.

> Built for the Vietnamese market. Prompts, the banned-word list, captions and voices are Vietnamese
> on purpose. Code, configuration and the dashboard are English.

## How one video is made

```mermaid
flowchart LR
    A[Collect<br/>Chrome extension] --> B[Idea → Script<br/>LLM brief + checks]
    B -->|you approve| C[Images<br/>master first, then scenes]
    C -->|you approve| D[Finish<br/>clips · voice · stitch · captions]
```

1. **Collect** (Chrome extension in `extension/`): TikTok Shop products and Pinterest reference images
   are sent to `POST /api/v1/products/ingest`.
2. **Idea → Script**: each video follows **one person** from a library (photo uploaded once, reused for
   every product). The generated face matches that photo; clothes and setting change per scene. An LLM
   writes the brief. The approved rules in `config/creative_knowledge/product_ad.json` tell it to avoid
   TikTok Shop banned words and to use only numbers and claims from the product data. No code checks
   the text afterwards, so read it: each line of the script is shown on its image card in the Images
   step, and the API can stop after the script (`until=script`) or edit it (`PUT .../brief`).
3. **Images**: the master image first, then the other scenes. Every image is checked against the real
   product photo and the model photo. The pipeline always stops after the master image until you
   approve it; an image the check flags is marked, and one it could not check shows "Not checked".
4. **Finish**: image → video clips, voice-over, 9:16 stitching with stickers, captions timed to the
   speech, and hashtags. Failed or flagged clips are listed under "Scenes that need a look".

The pipeline runs in the background, stores results and the reason it stopped (`product_pipeline_runs`),
and always resumes from what is already done.

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node + pnpm, ffmpeg, and a PostgreSQL
database (`AIC_AI_DATABASE_URL`; run `uv run alembic upgrade head` once). The Docker stack below brings
one, and is the easiest way to run everything.

```bash
uv sync --extra dev
uv run uvicorn ai_content.entrypoints.api.app:app --reload   # API: http://127.0.0.1:8000
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev -- --port 4174                         # http://localhost:4174/dashboard/
```

Docker (PostgreSQL, SeaweedFS, API, dashboard): copy `deploy/.env.example` to `deploy/.env`, fill in the
keys, then `just up`.

**Security:** the dashboard and API have **no login**, so they listen on `127.0.0.1` only
(`AIC_HTTP_BIND_ADDRESS`). Do not expose them to the internet. To open them up, enable nginx basic auth
with `deploy/nginx/auth.example.conf` or put them behind a VPN. See [SECURITY.md](SECURITY.md).

## What you need to bring

You supply the model endpoints and keys; nothing is bundled.

| Setting | Used for |
|---|---|
| `AIC_SCREENING_BASE_URL`, `AIC_SCREENING_API_KEY` | OpenAI-compatible endpoint for every LLM step; with no key all LLM steps are off |
| `AIC_WRITER_MODEL` | Model that writes the brief, hooks, captions, shortened lines and rules (required) |
| `AIC_REVIEW_MODEL` | Model that checks images, keyframes and clips, and picks references and the voice (required) |
| `AIC_IMAGE_*`, `AIC_IMAGE_API` | Image model (`chat` or `edits`) |
| `AIC_VIDEO_*` | Image → video model; `AIC_VIDEO_FRAME_FIELDS` picks the first-frame field |
| `AIC_TTS_*` | Voice-over |
| `AIC_TEXT_EMBEDDING_MODEL` | Matches reference images to scenes (empty = off) |
| `AIC_EMBEDDING_MODEL` | Local image model that drops duplicate references (`dinov3-vits16`, `dinov2-small`; empty = off, and then no reference image is stored) |
| `AIC_TTS_SPEED`, `AIC_CLIP_SPEED`, `AIC_DUPLICATE_SIMILARITY` | Voice-over pace (default 1.1), clip playback speed (1.1), duplicate threshold (0.80) |
| `AIC_BGM_PATH`, `AIC_CAPTION_FONT` | Optional background music file and caption font (defaults: `config/default_bgm.wav`, DejaVu Sans) |
| `AIC_AI_DATABASE_URL` | PostgreSQL URL (`postgresql+psycopg://...`); the only supported database |

Video models are usually billed per request, so each clip costs real money. See
[docs/model-limits.md](docs/model-limits.md) for the limits measured so far.

Default ad rules live in `config/creative_knowledge/product_ad.json` and load at startup. If you edit
the file, change its `bootstrap_id`; a test reminds you.

## Backup and restore

`just backup` (or `just backup-server` on a Linux host) stops the API and dashboard for a moment, writes
a verified set of the PostgreSQL dump and every object of the bucket to `.backups/<id>`, and copies it
off-site when `AIC_BACKUP_OFFSITE_ENABLED` is on. `just deploy-safe` makes a backup first, then pulls,
rebuilds and runs the smoke test. `deploy/scripts/restore-drill.sh <backup set>` restores a set into a
throwaway stack to prove it works. `deploy/systemd/` has a daily timer for a server.

## Responsible use

- Use a person's face only with their consent. The dashboard asks you to confirm you have the rights.
- Label AI-generated content as TikTok requires.
- The extension collects pages from TikTok Shop and Pinterest while you are logged in. Check their terms
  of service before you use it. You are responsible for how you use it.
- Check your music and voice files for licensing. Confirm the licence of `config/default_bgm.wav` and of any voice files you add.

## Development

Run in Docker (ffmpeg and fonts included, same on every machine):

```bash
just test            # or: just test tests/test_stickers.py
just lint
```

Or directly on your machine. The tests need an empty throwaway PostgreSQL database in
`AIC_AI_DATABASE_URL` (every test empties it) and ffmpeg (tests that need it are skipped if it is
missing); do not run two test sessions against the same database:

```bash
uv run ruff check .
uv run pytest
pnpm --dir frontend lint && pnpm --dir frontend test && pnpm --dir frontend build
```

After editing `baml_src/`, regenerate the client with `uv run baml-cli generate` (never edit
`adapters/baml_client` by hand). PostgreSQL migrations are in `migrations/`. Tests need PostgreSQL, so run them with
`just test` (Docker starts a disposable database). See [CONTRIBUTING.md](CONTRIBUTING.md).

## Docs

- [docs/video-ads-pipeline.md](docs/video-ads-pipeline.md): original design of the image → clip → video flow.
- [docs/model-limits.md](docs/model-limits.md): measured limits of the image, video and voice models.
- [docs/reference-corpus-and-content-plan.md](docs/reference-corpus-and-content-plan.md): the reference image library and the plan for several contents per product.
- [frontend/DEVELOPMENT.md](frontend/DEVELOPMENT.md), [extension/README.md](extension/README.md)

## License

[MIT](LICENSE)
