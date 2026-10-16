# OCR-007A — Email Adapter (IMAP/SMTP)

## Result

Implemented a separate standard-library IMAP/SMTP adapter that delegates OCR to `DocumentOCRService` through `EmailOCRService` and chooses delivery using the existing `OutputPolicy`. No real mailbox, SMTP server, or Vision endpoint was contacted during this stage.

## Design and safeguards

- `EmailAdapter` is a transport coordinator: it parses a message, authorizes its sender, passes supported attachment bytes as `InputFile(source="email")`, and constructs a reply. It has no Vision JSON parsing or document-rendering logic.
- `EmailOCRService` is a narrow application service wrapping the shared OCR service, `OutputPolicy`, and `DocxRenderer`. Short simple results go in the body; tables and long/complex documents become individually named DOCX attachments.
- `EmailConfig` reads IMAP/SMTP endpoint, TLS mode, credentials, mailbox, exact allowlist, polling interval, limits, and state path only from environment variables. The allowlist is required by default.
- Sender matching normalizes one full RFC-style mailbox address with case folding and compares it exactly. It does not use `Reply-To`, a domain, or a substring to choose the output recipient. `From` remains forgeable, so host-level authentication controls are still required.
- Automatic/list messages (`Auto-Submitted`, `Precedence`) and messages marked by this adapter are ignored. The adapter also does not answer itself.
- File type is selected from a safe filename extension allowlist, not the MIME declaration. The existing preprocessor subsequently decodes and validates actual contents. Attachment count and byte limits are enforced before OCR. No attachment is executed or written as a working file by the adapter.
- `EmailStateStore` uses an ignored local SQLite file. It claims a message before work, enters `sending` immediately before SMTP, and writes `sent` only after SMTP returns. An SMTP timeout/disconnect becomes `uncertain` and is never automatically resent, preventing a duplicate answer if the remote SMTP server accepted it before the process failed. This intentionally favors at-most-once reply delivery; uncertain records require manual reconciliation.

## IMAP polling

`IMAPMailbox` supports implicit TLS by default and STARTTLS for non-SSL IMAP. `SMTPMailer` likewise supports implicit TLS or explicit STARTTLS. `EmailAdapter.poll_once()` reconnects after an IMAP abort/socket error. The executable `python -m ocr_document_bot.email_bot` is available for a later manually authorized test mailbox connection; it was not run for OCR-007A.

## Tests

Mock-only coverage verifies one inline attachment, mixed multiple attachments with DOCX output, unsupported files, forbidden and automatic senders, persistent deduplication after restart, SMTP timeout handling, IMAP reconnect, exact address normalization, reply threading, recipient routing, and in-memory attachment handling.

## Known limitations / next validation

- SQLite has no operator UI for inspecting or clearing an `uncertain` delivery record.
- `From` allowlisting is authorization policy, not cryptographic authentication; configure mail-host controls before exposure.
- The polling loop is intentionally single-process MVP behavior. Run only one adapter process per state database.
- OCR/provider failures are reported per attachment in a single allowed-sender reply; no partial OCR result is represented as a complete result for a failed attachment.
- A live dedicated mailbox E2E test remains outside OCR-007A and requires explicit authorization.
