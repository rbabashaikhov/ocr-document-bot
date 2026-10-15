# OCR-005A — Telegram Adapter

## Scope and safety

Implemented a local aiogram 3 Telegram transport for JPG and PNG. No deployment, merge to `main`, Email work, LLM, LangGraph, or automatic paid OCR run was performed.

The adapter reads `TELEGRAM_BOT_TOKEN` only from the untracked `.env`. The token is never logged or committed. A read-only Telegram `getWebhookInfo` check found no configured webhook before the local polling smoke test. `deleteWebhook` is not used anywhere: if a webhook exists, polling raises `PollingSafetyError` and exits without altering an n8n deployment.

## Components

- `adapters/telegram.py` — aiogram router, JPG/PNG downloading, long-polling safety check, in-memory DOCX button cache, and transport error messages.
- `telegram_bot.py` — local `python -m` entry point.
- `output_policy.py` — transport-independent decision: simple text up to `OCR_INLINE_TEXT_MAX_CHARS` is inline; tables, candidates, pictures, and long text are DOCX.
- `TelegramOCRService` — validates an incoming file, invokes the existing Yandex Vision client only after a user submission, maps the raw response to the independent Document Model, then invokes Output Policy and the existing DOCX Renderer.

For visual table recovery, the service creates a temporary JPG/PNG only for mapping and deletes it immediately afterwards. The existing `OCR_ENABLE_VISUAL_TABLE_DETECTION` policy remains in effect.

## Delivery behavior

| Input result | Telegram delivery |
| --- | --- |
| Simple text, length ≤ configured threshold | Text in chat with “Получить DOCX” inline button |
| Table, table candidate, picture, or long text | Editable `ocr-result.docx` |
| Unsupported input or failed recognition | Safe Russian error message without provider details or secrets |

The DOCX-button cache is intentionally in-memory, bounded to 100 documents, scoped to the originating chat, and lost at process restart. No database or Redis was introduced.

## Verification

Mock tests cover Yandex OCR orchestration, simple-text output, table DOCX delivery, long-text DOCX delivery, inline button/cache ownership, and webhook safety refusal.

```text
uv run pytest -q tests/test_telegram_adapter.py  # 6 passed
uv run pytest -q                                 # 56 passed
```

Local polling was started successfully after the read-only webhook check and stopped with SIGINT after several seconds. No image was sent during the smoke test, so no Yandex Vision request occurred. The polling process did not change Telegram webhook state.

Manual E2E testing in Telegram was subsequently completed successfully, as confirmed by the user. This acceptance covered the local adapter workflow; no deployment or n8n production change was made.

## Manual E2E procedure

1. Use a dedicated development token in local `.env`; do not share or commit it.
2. Run `uv sync --locked`.
3. Run `uv run python -m ocr_document_bot.telegram_bot`.
4. If the process reports an existing webhook, stop: no webhook was removed. Obtain approval before using that token for polling.
5. In a private chat, send a small JPG/PNG containing only a short text. Confirm that text and paragraph breaks arrive in chat, then press “Получить DOCX” and verify an editable DOCX download.
6. Send a table or a long image. This deliberately triggers a billed OCR call after user submission; confirm that a DOCX arrives and opens in Word/LibreOffice.
7. Try a PDF or unsupported document and confirm a safe format message. Stop the process with `Ctrl+C`.

## Known limitations

- Telegram Bot API downloads are subject to its file limits; the project additionally enforces `OCR_MAX_FILE_SIZE_BYTES` after download.
- Vision is synchronous, so a large image occupies one worker thread until OCR finishes. There is no queue, retry policy, persistence, or per-user rate limit yet.
- Long polling is for local development only. It must not run alongside a webhook consumer for the same token.
- The in-memory DOCX button cache is not durable and does not survive restart.
