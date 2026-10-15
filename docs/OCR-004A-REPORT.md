# OCR-004A — DOCX Renderer

## Result

Implemented `DocxRenderer` using `python-docx` and a local CLI `python -m ocr_document_bot.render_docx`. The renderer accepts only the independent `Document` model; the CLI is responsible for the explicit fixture → Yandex mapper → Document Model boundary. No renderer reads provider JSON and no OCR API request is made.

## Rendering behavior

- A4 page size, 2 cm margins, and Arial 11 pt normal text provide a restrained default Word layout.
- `Paragraph` and table-cell text are written run-by-run, converting newline characters to Word line breaks.
- `Heading` uses the matching built-in Word heading level.
- `Table` becomes a Word `Table Grid` table, with row and column counts from the model. Empty cells stay empty.
- `row_span` and `column_span` are applied as native Word cell merges. Bounds or overlapping spans fail loudly rather than silently changing the table.
- Page boundaries in `Document.pages` become Word page breaks.
- Elements are processed in page-model order; a `TableCandidate` has no rendered content because its source paragraphs were deliberately retained by OCR-003B. Pictures have no image bytes in the current Document Model and are likewise not rendered.

The renderer does not attempt pixel-perfect recreation, infer missing data, or recover tables. It renders only semantics supplied by the internal model.

## Local CLI

```bash
uv run python -m ocr_document_bot.render_docx \
  fixtures/vision/ocr-002b-mixed.json \
  --model markdown \
  --output /tmp/ocr-002b-mixed.docx
```

Multiple fixture paths are allowed and become separate source pages. The command does not import credentials or invoke the OCR client.

## Tests

Tests generate a DOCX, reopen it using `python-docx`, and assert its editable structure. Covered cases:

- Cyrillic heading, ordinary paragraphs and explicit line breaks;
- table between paragraphs;
- 2×2 table with a merged cell, empty cell and cell line break;
- invalid overlapping spans rejected instead of silently rendered;
- page break between two Document Model pages;
- locally available real OCR-002B native table (6×2), including no duplicate table text in normal paragraphs.

Verification:

```text
uv run pytest
32 passed in 0.47s
```

No paid OCR request, DOCX/XLSX conversion service, Telegram, Email, LLM, LangGraph or OCR-004B work was performed.

## Known limitations

- Document Model currently preserves picture location/score but not image bytes, so pictures are omitted.
- Word layout is semantic, not an exact reconstruction of source coordinates, fonts, widths or page design.
- Layout-table candidates are intentionally represented through their preserved source paragraphs; they do not render as Word tables.
- A malformed model with overlapping/bounds-violating spans raises `ValueError`; callers should surface this as a rendering failure.
- Page breaks represent source-page boundaries but do not prevent Word pagination within a long source page.
