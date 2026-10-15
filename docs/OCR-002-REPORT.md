# OCR-002 — structured Yandex Vision OCR response research

Research date: 15 October 2026. No Vision OCR network request was made, no paid operation was initiated, and no response in this repository is represented as a real provider response. `tests/data/mock_yandex_vision_response.json` is a deliberately labelled synthetic mock used only for unit tests.

## Delivered research tooling

- `YandexVisionClient` uses `httpx` and only the documented synchronous endpoint `POST https://ai.api.cloud.yandex.net/ocr/v1/recognizeText`.
- `YandexVisionConfig.from_env()` loads `.env` (without overwriting existing process variables); credentials remain external to source code. Exactly one of `YANDEX_VISION_API_KEY` and `YANDEX_VISION_IAM_TOKEN` is required at request time.
- `python -m ocr_document_bot.cli <file> --allow-billed-request` is the future research command. The acknowledgement flag is mandatory, so invoking the CLI normally cannot make a billed call.
- A successful future call writes the unmodified full JSON response to `fixtures/vision/<input>.json`. These captures are intentionally ignored by Git because they may contain user content.
- `document_from_response()` maps only documented structural fields into the provider-neutral model; `summarize_response()` gives a compact inspection summary while raw JSON stays available for analysis.

## Verified response structure

The current synchronous request accepts `content`, `mimeType`, `languageCodes`, and `model`; it accepts JPEG, PNG, and PDF, while sync mode supports only a one-page PDF. The current response has `textAnnotation` and `page`. [Synchronous REST reference](https://aistudio.yandex.ru/en/docs/vision/ocr/api-ref/TextRecognition/recognize).

| Area | Documented fields useful for recovery | OCR-002 handling |
| --- | --- | --- |
| Page | `page`, `width`, `height`, `rotate` | Preserve page number and dimensions in `Page`; rotation remains in raw fixture pending a renderer decision. |
| Text and paragraphs | `blocks`, `lines`, `words`, `fullText`, `textSegments` | Preserve a block per provider block, its joined line text and geometry. Use block separation—not a flat `fullText`—as the paragraph boundary baseline. |
| Semantic hierarchy | `layoutType` with title, section header, header, footer, list, caption, footnote and text values | Preserve `layoutType`. It is a classification signal, not proof of an exact DOCX heading level. |
| Geometry | `boundingBox.vertices` on blocks, lines, words, tables and cells | Preserve block/table/cell coordinates. Coordinates are source-page pixels; normalize only in a later layout policy. |
| Tables | `rowCount`, `columnCount`, `cells[]`, `rowIndex`, `columnIndex`, `rowSpan`, `columnSpan`, `text`, geometry | Preserve cell address and spans exactly; do not infer a table from line spacing when `tables` is absent. |
| Markdown | `markdown` only in `markdown` and `math-markdown` models; pictures excluded | Treat as optional alternate semantic representation, never as a substitute for tables/geometry. |
| Pictures / quality | picture `boundingBox`, `score` | `score` is documented only as confidence for picture location. |

The documented REST schema does **not** list an OCR confidence field for blocks, lines, words, or table cells. Therefore this project does not calculate or invent recognition-confidence metrics. Its summary reports only documented picture-location scores and whether an unexpected `confidence` key was present in mock/captured payload; that observation is not a quality metric. [Synchronous schema](https://aistudio.yandex.ru/en/docs/vision/ocr/api-ref/TextRecognition/recognize), [async result schema](https://aistudio.yandex.ru/en/docs/vision/ocr/api-ref/TextRecognitionAsync/getRecognition).

## Table recovery strategy

1. Prefer `tables[]` over OCR text ordering: allocate a logical grid with `rowCount × columnCount`.
2. Place each cell at its documented `(rowIndex, columnIndex)`, retain `rowSpan` and `columnSpan`, and validate that spans do not overlap or exceed bounds.
3. Use a cell's own `text` as its content. Preserve cell/table geometry for later column-width and reading-order decisions.
4. Keep table blocks and surrounding text separate. In OCR-003, choose whether output requires semantic DOCX tables, a Markdown fallback, or a layout-preserving format; no renderer is implemented here.
5. If `tables[]` is empty or inconsistent, report a recovery warning rather than fabricate a table from visual alignment. A future approved test corpus should measure detection and span accuracy against ground truth.

## Limits, risks, and unanswered questions

- Published limits: 10 MB input, 20 megapixels per image, and a maximum of 200 PDF pages in async mode. Results are retained by the service for three days. [Yandex quotas and limits](https://yandex.cloud/en/docs/overview/concepts/quotas-limits).
- Multi-page PDFs need the async API (`recognizeTextAsync` followed by `getRecognition`); this client intentionally implements only the sync research path. [Async request](https://aistudio.yandex.ru/en/docs/vision/ocr/api-ref/TextRecognitionAsync/recognize), [async result](https://aistudio.yandex.ru/en/docs/vision/ocr/api-ref/TextRecognitionAsync/getRecognition).
- Current documentation confirms semantic block types, but it does not define a mapping from `LAYOUT_TYPE_SECTION_HEADER` to a particular output heading level.
- OCR ordering, overlapping tables/text, rotated scans, language mixing, malformed cell spans, and actual effectiveness of `markdown`/`math-markdown` require a separately approved non-production corpus and paid-call authorization.
- The legacy n8n workflow used an older endpoint/response shape. Do not treat its `result.textAnnotation` traversal as the current response contract.

## OCR-003 handoff

Before implementing any renderer, approve a sanitized evaluation corpus and success measures (text accuracy, block classification, table grid and merged-cell accuracy). Then capture authorised real JSON fixtures, validate the mapper against them, and decide a semantic-document fidelity policy. This task does not implement DOCX, Telegram, Email, async processing, a queue, database, or deployment.
