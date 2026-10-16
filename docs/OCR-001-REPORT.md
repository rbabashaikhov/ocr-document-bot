# OCR-001 — audit and preparation report

Audit date: 15 October 2026. Sources were checked on this date; URLs point to official Yandex documentation.

## Scope result

The repository now has a minimal Python package, explicit model/job contracts, local input validation, test coverage for state transitions and validation, and empty adapter/renderer boundaries. There are no OCR API calls, Telegram/email listeners, Google integrations, LLMs, production connections, deployments, or copied credentials.

## 1. Old n8n workflow audit

Source audited: `13.2_recognize file tg.json` (its filename differs slightly from the task wording; this is the workflow present in the repository). It has 14 nodes and one executable route:

```
Telegram Trigger (message)
  → Switch
     ├→ `/start` → Send a text message → No Operation
     └→ default → Get a file (Telegram)
        → Extract from File (binary → `b64`)
        → Yandex OCR (HTTP POST)
        → Text extraction (Code)
        → Edit Fields → Date & Time
        → Create a document (Google Docs)
        → Update a document (insert plain text)
        → Download file (Google Drive; convert Docs → DOCX)
        → Send a document (Telegram)
```

### Observed parameters

The `Yandex OCR` HTTP node posts to `https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText`, with generic bearer credentials managed in n8n and `Content-Type: application/json`. Its body uses `content = $json.b64`, `mimeType = $binary.data.mimeType || 'image/png'`, `languageCodes = ['ru', 'en']`, and `model = 'page'`. No credential value or credential identifier is carried into this repository.

`Get a file` builds its Telegram `fileId` as the concatenation of `message.document.file_id` and `message.photo[2].file_id`; this is fragile: one expression may be absent and photo index 2 assumes a particular size set. The Switch's default branch accepts every non-`/start` message, without an explicit MIME/size/type gate.

### Exact structure-loss point

The `Text extraction` Code node reads only `result.textAnnotation.blocks[].lines[].text` (falling back to joined `words[].text`), inserts a blank line between blocks, and returns `{text: out.join('\\n')}`. `Update a document` then inserts that single string as plain text. It discards bounding polygons, page dimensions/number, block `layoutType`, word/line geometry, table metadata and cells/spans, detected language, image rotation, and provider Markdown. Consequently, Google Docs never receives enough information to reproduce layout or tables. This is a workflow transformation loss, not evidence that Vision cannot return structure.

### What transfers to Python

- inbound-file handling and a user-facing delivery flow, but as adapter responsibilities;
- MIME/language/model selection, as validated configuration;
- the basic sequence download → validate/preprocess → OCR → render → deliver;
- a local filename/date policy, after its desired product behavior is specified.

### What to remove

- n8n runtime expression/code-node dependence and credential store;
- Google Docs creation/update and Drive export as an implicit renderer;
- the hard-coded Google folder ID and OAuth dependencies;
- the assumption that one flat text field represents a document;
- direct coupling from Telegram update shape to OCR request shape.

## 2. Verified Yandex Vision OCR facts

The current REST reference uses service base `https://ai.api.cloud.yandex.net`; the legacy workflow endpoint should be validated/migrated in OCR-002 rather than copied unchanged. The official REST reference exposes synchronous `POST /ocr/v1/recognizeText` and asynchronous `POST /ocr/v1/recognizeTextAsync`; async results are retrieved using `GET /ocr/v1/getRecognition?operationId=...`. Synchronous OCR supports only a single-page PDF. Async submission returns an Operation with `id`, `done`, and exactly one of `error`/`response` once complete. [REST overview](https://aistudio.yandex.ru/en/docs/vision/ocr/api-ref/), [synchronous Recognize](https://aistudio.yandex.ru/en/docs/vision/ocr/api-ref/TextRecognition/recognize), [asynchronous Recognize](https://aistudio.yandex.ru/en/docs/vision/ocr/api-ref/TextRecognitionAsync/recognize), [GetRecognition](https://aistudio.yandex.ru/en/docs/vision/ocr/api-ref/TextRecognitionAsync/getRecognition).

Supported formats listed by both methods are JPEG, PNG, and PDF. Current published limits are 10 MB per OCR file, images up to 20 megapixels, and up to 200 PDF pages in async mode. Published Vision quotas are 1 synchronous request/sec, 10 async requests/sec, and 50 requests/sec each for async-operation status/result reads; recognition results are retained for 3 days. [Yandex quotas and limits](https://yandex.cloud/en/docs/overview/concepts/quotas-limits).

The documented result has `textAnnotation` plus `page`. `textAnnotation` can include dimensions, `blocks` with bounding boxes, lines/words and `layoutType`, `tables` with row/column counts and cells (including indices, spans, text and geometry), `fullText`, rotation, picture locations, and `markdown`. `markdown` is documented as available only for `markdown` and `math-markdown` models and excludes pictures. Therefore it is an optional rendering input, not an assumed field for the legacy `page` model. [Recognize response schema](https://aistudio.yandex.ru/en/docs/vision/ocr/api-ref/TextRecognition/recognize), [async result schema](https://aistudio.yandex.ru/en/docs/vision/ocr/api-ref/TextRecognitionAsync/getRecognition).

For a service account, the current AI Studio authentication reference permits an IAM token (`Authorization: Bearer …`) or API key (`Authorization: Api-Key …`). Yandex's API-key documentation identifies `yc.ai.vision.execute` as the Vision OCR scope and supports limiting key scope and validity. The legacy workflow uses bearer authentication but does not prove how its token is minted. [AI Studio authentication](https://aistudio.yandex.ru/en/docs/ai-studio/api-ref/authentication), [API keys and scopes](https://yandex.cloud/en/docs/iam/concepts/authorization/api-key).

## 3. Proposed architecture

See [ARCHITECTURE.md](ARCHITECTURE.md). The central rule is that adapters hand `InputFile` to `OCREngine`, Yandex-specific code maps official provider responses into `DocumentModel`, and renderers consume only that model. `DocumentModel` intentionally represents pages, text blocks, geometry, table cells/spans, and optional Markdown so renderer choice cannot destroy the information before it is considered.

`OCRJob` lifecycle is `received → preprocessing → recognizing → rendering → completed`, with failure from any nonterminal state. It makes error ownership visible without imposing persistence yet. No queue, database, Redis, or LangGraph is warranted in this scoped foundation; async OCR and durability may justify them after OCR-002 defines workload/retry requirements.

## 4. Risks and decisions required

1. **API migration risk:** workflow uses the older `ocr.api.cloud.yandex.net` endpoint, while current docs show `ai.api.cloud.yandex.net`. Run a non-production contract test with sanctioned credentials in OCR-002 before switching.
2. **Render fidelity is not guaranteed by OCR:** tables/layout need a renderer policy (native DOCX tables, positioned layout, Markdown fallback) and acceptance samples.
3. **Input policy is incomplete:** product owners must choose maximum PDF pages, supported input formats beyond currently documented JPEG/PNG/PDF, output formats, filenames, and handling of corrupt/password-protected PDFs.
4. **Async durability:** multi-page PDFs need operation polling. Decide whether a VPS restart may lose a job; if not, specify a persistent store/queue and deduplication strategy. Vision OCR does not support idempotency, so retries must be controlled.
5. **Security:** choose IAM-token refresh vs a scoped/rotated service-account API key; validate the least required role with current docs. Do not reuse n8n credentials.
6. **Privacy/retention:** set logging/redaction, source-file/output retention, access control, and whether Yandex request logging is allowed before handling customer documents.

## 5. OCR-002 recommendation

1. Obtain a non-production service account and perform a small, explicitly authorized contract test against the current endpoint—no production credentials or files.
2. Implement `YandexVisionClient`: auth injection, request construction, sync/async selection, bounded polling, official response mapping, and classified errors.
3. Add fixtures only from documented/sanitized API examples or an explicitly labelled test fixture; never present a fixture as a real OCR response.
4. Implement a renderer after agreeing fidelity criteria, beginning with semantic DOCX (headings/lists/tables) and documenting unsupported positioning.
5. Implement one adapter at a time (Telegram first if prioritized), with MIME/size checks, safe delivery, observability, and integration tests.
6. Reassess durable job storage/queue after the async, restart, and throughput requirements are accepted; then deploy to Beget in a separate approved task.
