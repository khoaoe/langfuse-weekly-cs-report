FROM node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS frontend

# The frontend is built and verified here. Only the emitted static bundle
# crosses into the runtime image: no Node, no npm, no node_modules and no
# source map ever reaches production.
WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY tsconfig.json tsconfig.app.json vite.config.ts playwright.config.ts ./
COPY frontend/ ./frontend/
COPY assets/ ./assets/
RUN npm run typecheck \
    && npm run test:unit \
    && npm run build \
    && find src/weekly_cs_report/static/spa -name '*.map' -delete

FROM python:3.11.15-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba AS python-deps

COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY --from=frontend /build/src/weekly_cs_report/static/spa/ ./src/weekly_cs_report/static/spa/

# The project remains editable because its governed taxonomy is intentionally
# resolved relative to /app. Every third-party runtime package still comes
# from the reviewed lock, and the dependency graph is checked before handoff.
RUN UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --locked --no-dev --compile-bytecode \
    && uv pip check --python /opt/venv/bin/python

FROM python:3.11.15-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DASHBOARD_RUNTIME_DIR=/app/runtime \
    DASHBOARD_FRONTEND_MODE=spa \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

COPY --from=python-deps /opt/venv/ /opt/venv/
COPY --from=python-deps /app/src/ ./src/
COPY config/ ./config/
COPY entrypoint.sh /app/entrypoint.sh

RUN groupadd --gid 10001 dashboard \
    && useradd --uid 10001 --gid dashboard --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin dashboard \
    && install -d -o dashboard -g dashboard -m 700 /app/runtime \
    && install -d -o dashboard -g dashboard -m 700 /app/artifacts \
    && chown dashboard:dashboard /app/config \
    && chmod 755 /app/entrypoint.sh

USER 10001:10001

EXPOSE 8080

# Decodes the PO-approved Freshdesk agent rosters (config/freshdesk_agents.v1.json,
# config/freshdesk_reconciliation_agents.v1.json, artifacts/freshdesk_discovery/
# human_agent_candidates.v1.json) from base64 env vars at container start. These
# files are gitignored (real agent identity data) and never reach the git remote,
# so they cannot be baked into the image at build time.
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["weekly-cs-dashboard", "--host", "0.0.0.0", "--port", "8080"]
