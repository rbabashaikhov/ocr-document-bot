# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1

# Resolve exactly the committed lock before application sources are copied.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev

FROM python:3.12-slim AS production

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# A non-empty /data is copied into a newly created named volume, preserving
# UID 10001 ownership for the Email SQLite database.
RUN groupadd --gid 10001 ocrbot \
    && useradd --uid 10001 --gid ocrbot --create-home --home-dir /home/ocrbot --shell /usr/sbin/nologin ocrbot \
    && mkdir /app /data \
    && touch /data/.volume-owner \
    && chown -R ocrbot:ocrbot /app /data

WORKDIR /app
COPY --from=builder --chown=ocrbot:ocrbot /app/.venv ./.venv
COPY --chown=ocrbot:ocrbot src ./src

USER ocrbot
STOPSIGNAL SIGTERM

# compose.yaml supplies the process command; the same image runs both adapters.
CMD ["python", "-m", "ocr_document_bot.telegram_bot"]
