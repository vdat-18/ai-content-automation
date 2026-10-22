FROM node:24.21.0-bookworm-slim AS frontend-dependencies

WORKDIR /app/frontend
RUN corepack enable && corepack prepare pnpm@11.19.0 --activate
RUN pnpm config set store-dir /pnpm/store

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile

FROM frontend-dependencies AS development

COPY --chown=node:node frontend/ ./
RUN chown -R node:node /app/frontend/node_modules
USER node
EXPOSE 8080
CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "8080"]

FROM frontend-dependencies AS builder

ARG VITE_ENABLE_LEGACY_LOCAL_MODELS=
ENV VITE_ENABLE_LEGACY_LOCAL_MODELS=${VITE_ENABLE_LEGACY_LOCAL_MODELS}

COPY frontend/ ./
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.30.4-alpine3.24 AS runtime

COPY --chown=101:101 deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=builder --chown=101:101 /app/frontend/dist /usr/share/nginx/html/dashboard

USER 101:101
EXPOSE 8080
