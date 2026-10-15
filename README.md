# OCR Bot v2 — OCR-001 foundation

This repository is the analysis and infrastructure baseline for a structure-preserving OCR service. It does **not** start a Telegram bot, receive email, call Yandex Vision, use an LLM, or deploy anything.

## Layout

- `src/ocr_document_bot/domain` — provider-neutral job and document model.
- `src/ocr_document_bot/preprocessing` — input validation boundary.
- `src/ocr_document_bot/ocr_engine` — use-case orchestration.
- `src/ocr_document_bot/providers` — Yandex configuration boundary only.
- `src/ocr_document_bot/cli.py` — guarded local research CLI; it never calls OCR without an explicit opt-in flag.
- `src/ocr_document_bot/adapters` — reserved Telegram and Email entry points.
- `src/ocr_document_bot/renderers` — reserved output boundary.
- `docs/OCR-001-REPORT.md` — workflow audit, verified API research, risks, and OCR-002 handoff.
- `docs/OCR-002-REPORT.md` — structured-response research and restoration strategy.

## Local setup and checks

This project uses [uv](https://docs.astral.sh/uv/) for Python 3.12, dependency resolution, the local `.venv/`, and command execution. Install `uv`, then synchronize the locked development environment:

```bash
uv sync
uv run pytest
```

`uv sync` creates or updates `.venv/` from `pyproject.toml` and the committed `uv.lock`; do not manually install project dependencies with `pip`. To upgrade a dependency deliberately, update `pyproject.toml`, run `uv lock`, review the lock-file change, then run `uv sync`.

Copy `.env.example` to `.env` only when a later implementation needs credentials. Never commit `.env`, tokens, API keys, OAuth credentials, or service-account keys.

`OCR_INLINE_TEXT_MAX_CHARS=2500` records the planned Smart Output Delivery threshold. It is not consumed by code yet; see the deferred requirement in [architecture](docs/ARCHITECTURE.md).

## OCR research CLI

The minimal `httpx` client calls the documented synchronous Vision endpoint only when explicitly authorized. It loads `.env` without overwriting shell environment values and saves the complete provider JSON under `fixtures/vision/`, which is deliberately ignored because it may contain document data.

```bash
# This validates CLI arguments and intentionally stops before any request.
uv run python -m ocr_document_bot.cli path/to/image.png

# Run only after a separate explicit approval for the billed OCR request.
uv run python -m ocr_document_bot.cli path/to/image.png --allow-billed-request
```

Supported input types for this CLI are `image/jpeg`, `image/png`, and `application/pdf`. The synchronous API is limited to a single-page PDF; use no production or sensitive input for research captures.

## Local DOCX rendering

Render one or more already captured local fixtures without calling Yandex Vision:

```bash
uv run python -m ocr_document_bot.render_docx \
  fixtures/vision/ocr-002b-mixed.json \
  --model markdown \
  --output /tmp/ocr-002b-mixed.docx
```

Each fixture becomes one source page in the DOCX. The renderer accepts only the internal Document Model after the mapper boundary; it does not read Yandex JSON itself.

Visual recovery of ruled tables is disabled by default. Native Yandex `tables[]` always has priority. To evaluate a local image and fixture without an API call, explicitly enable the feature flag and provide the matching source image:

```bash
OCR_ENABLE_VISUAL_TABLE_DETECTION=true uv run python -m ocr_document_bot.render_docx \
  fixtures/vision/ocr-002b-table.json \
  --source-image tests/samples/table.png \
  --output artifacts/ocr-004e/complex-table-visual.docx
```

Only geometrically confirmed (`detected`) grids become Word tables. Ambiguous or absent grids preserve the existing OCR block flow.

See [architecture](docs/ARCHITECTURE.md) and the [OCR-001 report](docs/OCR-001-REPORT.md).
