# Contributing

Thanks for looking. Issues and pull requests are welcome.

## Setup

See the Quick start in [README.md](README.md). The easiest way to run checks is Docker (ffmpeg and fonts
are included):

```bash
just lint
just test
```

## Rules of the repo

- Python 3.11+, Ruff (line length 100) and pytest. Type hints at public APIs.
- Log with `loguru`, never `print()`.
- Code, identifiers, comments and config keys are in English. User-facing text in the dashboard is
  English. Vietnamese is for prompts, the banned-word list, captions and the docs that need it.
- Keep changes small and focused. Add or update tests for changed behavior.
- Do not edit `adapters/baml_client` by hand; edit `baml_src/` and run `uv run baml-cli generate`.
- No keys, tokens or personal data in code, tests, docs or logs.

## Pull requests

1. Branch from `dev`.
2. Make sure `ruff check` and `pytest` pass, and `pnpm lint/test/build` in `frontend/` if you touched it.
3. Describe what changed and why.
