# OCR-006A — PDF and additional image formats

## Result

The shared Input Preprocessor now accepts JPEG/JPG, PNG, WEBP, BMP, TIFF/TIF, and PDF. No OCR request was made while implementing or testing this stage. The Telegram adapter delegates every supported input to that same boundary and does not contain format-specific OCR logic.

## Processing model

| Input | Local processing | Vision use |
| --- | --- | --- |
| JPEG/PNG | Decode validation; preserved as the first page | One request per input page |
| WEBP/BMP | Decode with Pillow and encode JPEG | One request |
| TIFF/TIF | Iterate every Pillow frame and encode each JPEG | One request per frame |
| PDF with usable text layer | Extract text per page with PyMuPDF | None for that page |
| Scanned PDF page | Render bounded JPEG using PyMuPDF | One request for that page |
| Mixed PDF | Decide independently for every source page | Only scanned pages |

`DocumentOCRService` assembles resulting `Page` objects in their original order. Native PDF paragraphs have `pdf-native-text` provenance; OCR pages retain the existing Yandex mapper, table detection, and renderer path. The renderer consequently receives one independent `Document`, without reading PDF or Yandex payloads itself.

## Limits and safety

Configuration is environment-based and documented in `.env.example`:

- `OCR_MAX_FILE_SIZE_BYTES` limits the original upload.
- `OCR_MAX_PAGES` caps TIFF/PDF page count.
- `OCR_MAX_JOB_SIZE_BYTES` caps generated JPEGs for pages that require OCR.
- `OCR_PDF_RENDER_DPI` and `OCR_MAX_RENDERED_PIXELS` bound rendering work.
- `OCR_PDF_TEXT_MIN_CHARS` prevents tiny or non-meaningful text fragments from bypassing OCR.

Password-protected PDF, corrupt image/PDF, unsupported type, and size/page-limit errors are translated to concise Telegram messages. The adapter also uses a filename extension when Telegram supplies `application/octet-stream` for a supported document.

## Tests

Local tests cover WEBP, BMP, multi-page TIFF, scanned/text/mixed PDF, page order, corrupt PDF, limits, and mixed-PDF orchestration. The Vision client is a mock; the mixed-PDF test proves only the scanned page is sent to it and that each source text occurs once. Telegram unit tests cover generic MIME fallback and safe error strings.

Run the full suite with:

```bash
uv run pytest -q
```

## Limitations and OCR-006B considerations

- OCR requests are synchronous and sequential per page. This keeps interactive jobs bounded but is not appropriate for long PDFs. A later async workflow needs persistent job state, polling, retry/idempotency rules, and delivery status before it is introduced.
- Text-layer suitability is intentionally conservative and based on extracted meaningful-character count. It does not assess semantic quality, reading order, or visual correspondence; a poor but long text layer may still need a user-selectable “force OCR” mode later.
- Native PDF extraction currently creates paragraphs from blank-line separation and does not recover PDF headings, tables, or styling. It must not be represented as a visual-layout reconstruction.
- Image pages are rasterised for Vision; page-level DPI reduction can reduce very small text quality. Limits should be tuned with representative, non-confidential test data.
- TIFF/PDF source artifacts and Vision fixtures remain ignored by Git. No secrets, real documents, or raw OCR responses were added.
