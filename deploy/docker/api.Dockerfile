FROM ghcr.io/astral-sh/uv:0.12.10 AS uv

FROM python:3.11.16-slim-bookworm AS builder-dependencies

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM builder-dependencies AS builder

COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.11.16-slim-bookworm AS runtime-base

ENV AIC_AI_CONFIG_DIR=/app/config \
    AIC_AI_DATA_ROOT=/var/lib/aicontent/pilot \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 aic \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin aic \
    && mkdir -p /var/lib/aicontent/pilot/artifacts \
    && chown -R aic:aic /var/lib/aicontent

COPY --from=builder-dependencies /app/.venv /app/.venv
RUN /app/.venv/bin/python -m playwright install --with-deps chromium \
    && chown -R aic:aic /ms-playwright

FROM runtime-base AS runtime

COPY --from=builder /app/.venv /app/.venv
COPY config /app/config
COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations
COPY deploy/scripts/smoke.py /app/deploy/scripts/smoke.py
COPY deploy/scripts/observability_smoke.py /app/deploy/scripts/observability_smoke.py
COPY deploy/scripts/observability_drill.py /app/deploy/scripts/observability_drill.py

USER 10001:10001
EXPOSE 8000

CMD ["uvicorn", "ai_content.entrypoints.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS maintenance

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl --fail --silent --show-error \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001

CMD ["python", "-m", "ai_content.entrypoints.backup", "--help"]
