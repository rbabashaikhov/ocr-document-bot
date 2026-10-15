# OCR Bot v2 — OCR-001 foundation

This repository is the analysis and infrastructure baseline for a structure-preserving OCR service. It does **not** start a Telegram bot, receive email, call Yandex Vision, use an LLM, or deploy anything.

## Layout

- `src/ocr_document_bot/domain` — provider-neutral job and document model.
- `src/ocr_document_bot/preprocessing` — input validation boundary.
- `src/ocr_document_bot/ocr_engine` — use-case orchestration.
- `src/ocr_document_bot/providers` — Yandex configuration boundary only.
- `src/ocr_document_bot/adapters` — reserved Telegram and Email entry points.
- `src/ocr_document_bot/renderers` — reserved output boundary.
- `docs/OCR-001-REPORT.md` — workflow audit, verified API research, risks, and OCR-002 handoff.

## Local setup and checks

This project uses [uv](https://docs.astral.sh/uv/) for Python 3.12, dependency resolution, the local `.venv/`, and command execution. Install `uv`, then synchronize the locked development environment:

```bash
uv sync
uv run pytest
```

`uv sync` creates or updates `.venv/` from `pyproject.toml` and the committed `uv.lock`; do not manually install project dependencies with `pip`. To upgrade a dependency deliberately, update `pyproject.toml`, run `uv lock`, review the lock-file change, then run `uv sync`.

Copy `.env.example` to `.env` only when a later implementation needs credentials. Never commit `.env`, tokens, API keys, OAuth credentials, or service-account keys.

See [architecture](docs/ARCHITECTURE.md) and the [OCR-001 report](docs/OCR-001-REPORT.md).
