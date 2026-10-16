# OCR-004F — Layout-aware DOCX Rendering

## Scope

Changed only the DOCX rendering boundary and its tests. OCR Engine, Yandex mapper, visual table detector, feature flags and OCR data were not changed. No OCR API request was made.

The baseline and result are local, Git-ignored artifacts in `artifacts/ocr-004f/`:

- `complex-table-before.docx`, `complex-table-before.pdf`, `complex-table-before-preview.png`;
- `complex-table-after.docx`, `complex-table-after.pdf`, `complex-table-after-preview.png`.

PDF was generated with local LibreOffice and PNG preview with `pdftoppm`; neither operation changes the DOCX content.

## Renderer changes

### Page layout

The renderer uses landscape A4 when a table has at least four columns and its source geometry is wide (`width / height >= 1.4`). Landscape pages use 1.0 cm left/right and 1.2 cm top/bottom margins. Other documents retain portrait A4 with the previous 2 cm margins.

This decision is based on Document Model geometry only, never Yandex JSON. A document containing a qualifying table is currently rendered in landscape as a whole; page-specific mixed orientation is not yet implemented.

### Column proportions and merged cells

For a table with cell geometry, each source column receives the median observed width of its non-merged cells. A merged cell contributes its width divided over its span when a single-column observation is unavailable. The calculated proportions are normalized to the usable page width and written both to Word's table grid and column objects with autofit disabled.

Therefore narrow technical columns remain narrow, while merged cells span the sum of their constituent column widths. Tables without geometry retain an even-width fallback so existing native-table documents continue to render.

### Readability

- table font: Arial-compatible document default, 8.5 pt in cells;
- `Table Grid` borders, top vertical alignment, 90 twips (about 0.16 cm) horizontal and 70 twips (about 0.12 cm) vertical cell margins;
- first table row and numeric values are horizontally centered; other content is left-aligned;
- only OCR-provided line breaks are written. The renderer does not add character-level breaks or change OCR text.

## Visual result

The baseline was portrait with uniformly allocated Word columns, producing excessive letter-level wrapping in wide headers and dates. The result is a landscape A4 table with source-derived grid widths:

```text
[1743, 2649, 2892, 878, 1189, 2095, 811, 3446] twips
```

The narrow technical columns remain substantially narrower than the staff/name and notes columns. Visual PNG inspection confirmed readable headers, dates and notes, visible borders, preserved blank columns, row/column numbering order, and merged header/body cells.

## Verification

New `tests/test_layout_aware_docx_renderer.py` creates a synthetic 4-column wide table with source proportions `[100, 300, 50, 350]` and validates:

- landscape A4;
- width ordering `50 < 100 < 300 < 350` after DOCX reopen;
- merged header cell;
- top vertical alignment and 8.5 pt cell text.

The existing local OCR-002B fixture test was strengthened to reopen the generated DOCX and compare OCR-line multisets. It identifies physical Word cells by XML path, because `python-docx` exposes an already merged cell once per covered grid slot.

For the real complex fixture:

| Check | Result |
| --- | --- |
| DOCX table shape | 5×8 |
| Physical Word cells after merges | 29 |
| OCR blocks | 21 |
| OCR text lines | 41 input / 41 rendered |
| Missing or extra text lines | 0 / 0 |
| Editable cells | yes (`python-docx` reopens the table) |

Commands run:

```text
uv run pytest -q tests/test_layout_aware_docx_renderer.py tests/test_visual_table_integration.py  # 8 passed
uv run pytest -q                                                          # 50 passed
git diff --check                                                          # passed
```

## Limitations and follow-up

- Horizontal alignment is a conservative rendering heuristic; OCR response and Document Model do not yet carry true text alignment. Vertical alignment is top-aligned rather than reconstructed from the scan.
- The current orientation is document-wide. A mixed portrait/landscape multi-page layout would require section-aware rendering and additional pagination tests.
- Complex source styling (fonts, bold, colors, borders, exact row heights) is intentionally not recreated.
- A very narrow column can still wrap at natural word boundaries; the renderer does not insert hyphenation or invent text to avoid it.
- Header numbering can be incomplete when Vision did not return the visible number as a separate, reliably assignable OCR block. The renderer preserves returned text and does not invent missing numbering.
- Detected merged cells reflect the available geometric grid, so some merges can differ from the original scan when a border was weak, missing, or interpreted differently by the visual detector. This needs visual review before using the result as a fidelity baseline.
- Other complex table layouts still require validation: the current evidence is one real ruled-table fixture plus synthetic cases, not a broad regression corpus of merged, rotated, low-quality, and multi-page tables.

No Telegram, Email, XLSX, LLM, LangGraph, deployment, or subsequent OCR stage was started.
