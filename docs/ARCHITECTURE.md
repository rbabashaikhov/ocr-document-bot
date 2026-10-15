# OCR Bot v2 architecture (OCR-001)

## Goal and boundary

One core pipeline accepts a file from an adapter, preserves the OCR provider's useful structural data in a provider-neutral `DocumentModel`, and gives that model to a selected renderer. OCR-001 supplies contracts and state handling only; it has no transport listener, email implementation, renderer implementation, persistence, queue, LLM, production connection, or deployment.

```
Telegram Adapter ─┐
                  ├─> OCR Engine ─> Input Preprocessor ─> Yandex Vision Client
Email Adapter ────┘          │                                      │
                              └──── OCRJob / DocumentModel <─────────┘
                                                    │
                                                    └─> Document Renderer
```

## Components and ownership

| Component | Responsibility | Must not own |
| --- | --- | --- |
| Telegram Adapter | Convert a Telegram update/file into `InputFile`; return the result through Telegram. | OCR request details or document layout decisions. |
| Email Adapter | Extract an allowed attachment into `InputFile`; send a reply. | Mail server, OCR, and renderer internals. |
| OCR Engine | Orchestrate state transitions, preprocessing, provider call, and rendering; map errors to job errors. | HTTP/webhook framework or provider JSON shape. |
| Input Preprocessor | Validate MIME type/size; later normalize orientation and choose sync/async mode. | Recognized-content interpretation. |
| Yandex Vision Client | Authentication headers, request mode, polling, and conversion of official response fields to `DocumentModel`. | Output format and transport-specific behavior. |
| Document Model | Preserve pages, blocks, geometry, layout types, tables/cells/spans, and provider metadata. | API credentials and UI output. |
| Document Renderer | Turn `DocumentModel` into DOCX/Markdown/etc. | Provider JSON and inbound transport. |

## OCRJob lifecycle and errors

`received → preprocessing → recognizing → rendering → completed`

Any nonterminal state can move to `failed`. A terminal job cannot be restarted in place. `OCRJob` records an opaque UUID, timestamps, input metadata, status, optional `DocumentModel`, and safe error code/message. Do not place source bytes, credentials, or raw provider payloads into logs by default.

Suggested OCR-002 error categories:

- `unsupported_input`: MIME, empty file, size/page limit, or malformed document;
- `authentication_failed` / `authorization_failed`: invalid or underprivileged cloud credential;
- `provider_rate_limited` / `provider_unavailable`: retry with bounded backoff only where safe;
- `recognition_failed`: returned provider operation/error;
- `rendering_failed`: a valid model could not be expressed in the requested format;
- `delivery_failed`: output exists but the adapter cannot return it.

Vision OCR does not support idempotency, so do not retry a submission blindly. Persist a caller-side deduplication key or explicit user retry decision before enabling automatic resubmission.

## Why no database, Redis, queue, or LangGraph now

The OCR-001 scope has one process-local use case and no actual concurrent adapters. Introducing infrastructure now would create operational obligations without a demonstrated throughput, retry, or durability requirement. A durable job store plus queue is justified in OCR-002 only if async PDF polling, restarts, multi-user parallelism, or delivery retries require jobs to survive process restarts. LangGraph has no role in deterministic file validation, API calls, or rendering, and an LLM is expressly out of scope.

## Configuration and security

All future configuration comes from environment variables. `.env.example` names expected variables but contains no values. Prefer a service account with a scoped, expiring API key or an IAM-token flow, minimum service role required by current Vision documentation, secret injection on the VPS, and rotation. The exact role and current API endpoint must be rechecked during OCR-002 because Yandex's current API reference has moved to AI Studio.

## Deferred requirement: Smart Output Delivery

This is a product requirement recorded for the renderer stage, not an OCR-002 implementation. A future provider-neutral `OutputPolicy` module will accept a `DocumentModel`, an optional user-selected output format, and `OCR_INLINE_TEXT_MAX_CHARS` (default `2500`). It will return a delivery decision; Telegram and Email adapters will only carry out that decision.

Decision precedence and rules:

1. An explicit user format selection has priority over automatic selection.
2. With no explicit choice, a document containing only simple text of at most the configured character limit is delivered inline. Paragraphs and line breaks must be retained in the Telegram message or email body.
3. A longer document, a document with tables, or a document with complex structure is delivered as a generated DOCX or XLSX. The exact DOCX-versus-XLSX rule requires renderer and product acceptance criteria.
4. An inline Telegram result must offer a “Получить DOCX” action; this is an adapter/UI concern triggered by the policy decision, not a policy dependency.

No `OutputPolicy`, Telegram button, DOCX/XLSX renderer, or delivery implementation exists yet. These will be implemented only after the Document Model and renderers are accepted.
