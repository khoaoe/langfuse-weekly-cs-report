FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DASHBOARD_RUNTIME_DIR=/app/runtime

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY config/ ./config/

RUN groupadd --gid 10001 dashboard \
    && useradd --uid 10001 --gid dashboard --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin dashboard \
    && python -m pip install --no-cache-dir -e . \
    && install -d -o dashboard -g dashboard -m 700 /app/runtime

USER 10001:10001

EXPOSE 8080

CMD ["weekly-cs-dashboard", "--host", "0.0.0.0", "--port", "8080"]
