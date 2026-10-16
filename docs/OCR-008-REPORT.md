# OCR-008 — Production packaging, launch and acceptance

## Scope completed

OCR-008 prepared the Docker image and Compose topology, performed a controlled
VPS smoke test, configured the production directory and environment, and
launched the independent Telegram and Email adapters on Beget.  No merge to
`main` was performed.

## Production state at acceptance

The operator confirmed successful manual production E2E for both channels:

- Telegram processed the previously failing scanned-PDF workflow.
- Email processed a supported attachment after its configuration correction.

The final read-only container check found both services running and healthy.
`ocr-email` has no restarts.  `ocr-telegram` has one historical restart and
historical transient Telegram long-poll request-timeout tracebacks; it is
currently healthy and the accepted Telegram E2E completed afterwards.  No
Vision HTTP 4xx/5xx, diagnostic-write failure, filesystem permission failure,
or Email authentication error appeared in the filtered operational logs.

## OCR-008C incident and correction

Both production failures had the same root cause: an enabled relative
`OCR_DIAGNOSTICS_DIR` was resolved below the intentionally read-only `/app`
filesystem.  The optional diagnostic writer failed after a successful Vision
response, and the adapter returned a generic processing error.

The production `.env` now leaves this variable empty.  Only the affected
container was recreated in each correction:

- Telegram was recreated for OCR-008C/2.
- Email was recreated for OCR-008C/4; the named SQLite volume, IMAP baseline,
  and delivery ledger were preserved and no prior mail was replayed.

No image rebuild was required for either configuration correction.

## Local resilience fix awaiting deployment

The local working tree now makes Vision diagnostics best-effort.  If an
`OSError` prevents creation or writing of a redacted diagnostic record,
`DiagnosticVisionClient` logs a sanitised warning and returns the already
received provider response.  The accompanying regression test proves that
such a persistence failure cannot discard a successful mocked OCR response.

This code change is deliberately **not deployed** by OCR-008C/5.  It should be
reviewed, committed, and released through a separate approved deployment.

## Verification

- `uv run pytest -q` — passed (94 tests).
- `git diff --check` — passed.
- No secrets, `.env`, SQLite files, user documents, raw OCR JSON, or local
  diagnostics are tracked or staged by this work.

See `OCR-008C-REPORT.md` for the incident timeline and per-container evidence.
