# OCR-006B — Local E2E verification of multi-page inputs

## Scope and result

OCR-006B was verified locally with synthetic, non-confidential files and a recording mock of Yandex Vision. No Telegram polling was started, no credentials were read into test data, and no billed OCR request was made.

The tests exercise the same route used by Telegram:

```text
Telegram InputFile → InputPreprocessor → DocumentOCRService
                  → Yandex mapper / Document Model → OutputPolicy
```

For delivery, the existing Telegram adapter remains responsible only for downloading a file and returning inline text or DOCX. It contains no PDF/TIFF OCR branch.

## Configuration and limits checked

The local defaults are consistent with `.env.example`:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `OCR_MAX_FILE_SIZE_BYTES` | 10 MiB | Original uploaded file limit |
| `OCR_MAX_PAGES` | 20 | PDF/TIFF page limit |
| `OCR_MAX_JOB_SIZE_BYTES` | 25 MiB | Sum of images generated for OCR |
| `OCR_PDF_RENDER_DPI` | 150 | Scan-page rasterisation resolution |
| `OCR_MAX_RENDERED_PIXELS` | 16,000,000 | Per-page rendering upper bound |
| `OCR_PDF_TEXT_MIN_CHARS` | 20 | Minimum meaningful text-layer size |

Existing preprocessing tests cover page and generated-image limits, corrupt PDF, encrypted PDF, and image decoding errors. The transport maps these validation failures to non-technical Telegram messages.

## Synthetic scenarios

| Scenario | Expected route | Verified result |
| --- | --- | --- |
| Text PDF, two pages | PyMuPDF text extraction only | Source order and both texts preserved; zero Vision calls |
| Text PDF through `TelegramOCRService` | Same, then OutputPolicy | Inline result; zero Vision calls |
| Mixed PDF: text / scan / text | Extract / OCR / extract | Page order `0,1,2`; exactly one Vision call |
| Scanned PDF with native `tables[]` | Rendered JPEG → mapper | Editable 2×2 `Table`; table-cell text not duplicated as paragraphs |
| Two-page TIFF | Pillow frame iteration → OCR | Two JPEG inputs and two model pages in frame order |
| Scanned PDF with visual detection enabled | Rendered JPEG → visual detector | Detector received a non-empty JPEG rendered from the scanned source page |
| OCR timeout on second TIFF page | Provider failure boundary | Exception propagates; no `Document` is returned or delivered as a complete result |

The mock table response intentionally includes a normal OCR block within its table bounds. The mapper removes that duplicate paragraph when it accepts the native table, so only the four table-cell values remain in the table structure.

## Error semantics

Processing is sequential and atomic from the adapter’s perspective: `DocumentOCRService.process()` returns a `Document` only after all pages finish. If a page errors or times out, it propagates the failure; the Telegram handler emits its existing generic failure message and does not call the result-delivery path. This is not resumable processing and does not expose a partial document as complete.

## Manual Telegram check

Do this only with a dedicated development bot token and explicit approval for any billed Vision calls. Do **not** run polling when `getWebhookInfo` shows a webhook: the application intentionally refuses to remove it.

1. Run `uv sync --locked` and set the bounded PDF/TIFF limits from `.env.example` in a local, untracked `.env`.
2. Confirm the token has no existing webhook, then start the local adapter with `uv run python -m ocr_document_bot.telegram_bot`.
3. Send a small, non-confidential text-layer PDF as a Telegram Document. Confirm its text is returned in source-page order and the inline response has **«Получить DOCX»**.
4. Send an anonymised scanned PDF and a multipage TIFF within the limits. Confirm processing ends in one result, and multi-page output preserves page order. Tables or long text should arrive as DOCX.
5. Send a mixed PDF. Confirm native-text pages and scanned pages occur in their original order in the generated DOCX.
6. Optionally send a password-protected or intentionally damaged local copy. Confirm the bot reports a concise input error and sends no result.
7. Stop the local process with `Ctrl+C`. It does not modify Telegram webhooks.

## Limitations

- These are deterministic local E2E tests. They verify routing, page isolation, and model assembly, but not OCR accuracy against live Yandex Vision.
- A simulated page timeout proves that no partial successful document is delivered. It does not introduce cancellation, retry, persistence, or async polling; those remain outside OCR-006B.
- Native PDF text is accepted by a threshold, not by visual fidelity analysis. A long but defective text layer may require a future user-controlled “force OCR” choice.
- Manual Telegram testing with scanned pages can incur provider charges and therefore remains deliberately opt-in.
