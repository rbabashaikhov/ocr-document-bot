# OCR Bot v2

This repository contains a local, structure-preserving OCR service. The optional Telegram adapter receives files, the shared pipeline builds a provider-neutral Document Model, and it returns inline text or editable DOCX. It has no Email adapter, deployment, LLM, or production n8n integration.

## Layout

- `src/ocr_document_bot/domain` — provider-neutral job and document model.
- `src/ocr_document_bot/preprocessing` — input validation, image normalisation, and per-page PDF/TIFF preparation.
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

`OCR_INLINE_TEXT_MAX_CHARS=2500` controls Smart Output Delivery: simple short documents are returned inline; tables and longer documents are sent as DOCX.

## Supported input formats

Telegram accepts JPG/JPEG, PNG, WEBP, BMP, TIFF/TIF, and PDF. JPG and PNG preserve the existing path. WEBP, BMP, and each TIFF frame are decoded locally and normalised to JPEG before OCR.

PDF is processed page by page in source order. A page whose extracted text layer reaches `OCR_PDF_TEXT_MIN_CHARS` meaningful characters is added directly to the Document Model; a scanned page is rendered to a bounded JPEG (`OCR_PDF_RENDER_DPI`, `OCR_MAX_RENDERED_PIXELS`) and then sent to Vision. Thus mixed text/scan PDFs do not OCR their usable text pages. Encrypted, damaged, over-page-limit, and oversized inputs produce a user-facing Telegram error.

`OCR_MAX_FILE_SIZE_BYTES` limits the uploaded source, `OCR_MAX_PAGES` limits TIFF/PDF page count, and `OCR_MAX_JOB_SIZE_BYTES` limits the sum of generated OCR images. Defaults are in `.env.example` and can be adjusted locally without changing source code.

The current implementation uses synchronous per-page Vision requests. This is deliberately suitable only for bounded interactive jobs. For large documents, OCR-006A recommends a separate asynchronous provider workflow with persistent job state and polling; it is not implemented here because that would require queue/state infrastructure outside this stage.

## OCR research CLI

The minimal `httpx` client calls the documented synchronous Vision endpoint only when explicitly authorized. It loads `.env` without overwriting shell environment values and saves the complete provider JSON under `fixtures/vision/`, which is deliberately ignored because it may contain document data.

```bash
# This validates CLI arguments and intentionally stops before any request.
uv run python -m ocr_document_bot.cli path/to/image.png

# Run only after a separate explicit approval for the billed OCR request.
uv run python -m ocr_document_bot.cli path/to/image.png --allow-billed-request
```

This research CLI calls Vision directly and therefore remains limited to `image/jpeg`, `image/png`, and single-page PDF. The Telegram/service pipeline above is the page-aware path for all supported formats. Use no production or sensitive input for research captures.

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

## Local Telegram bot

The optional aiogram 3 adapter accepts JPG/JPEG, PNG, WEBP, BMP, TIFF/TIF, and PDF as a photo or document. It sends simple results of at most `OCR_INLINE_TEXT_MAX_CHARS` directly to the chat, and sends DOCX for tables or longer content. Inline results include a “Получить DOCX” button. OCR is called only after a user sends a file; starting the bot itself does not invoke Yandex Vision.

Set `TELEGRAM_BOT_TOKEN` in the untracked `.env`. Before long polling, the adapter calls Telegram `getWebhookInfo` and refuses to start if a webhook is configured. It does not call `deleteWebhook`, so it does not alter a running n8n integration.

```bash
uv sync --locked
uv run python -m ocr_document_bot.telegram_bot
```

Use a dedicated development bot token for manual testing. Stop the local process with `Ctrl+C`; the optional DOCX button cache is in memory and is cleared when the process stops.

See [architecture](docs/ARCHITECTURE.md) and the [OCR-001 report](docs/OCR-001-REPORT.md).
