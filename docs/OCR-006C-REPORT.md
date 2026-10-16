# OCR-006C — Mixed-PDF defect correction

## Local reproduction

No Yandex Vision request was made. Both defects were reproduced with a synthetic provider response that has the same relevant response shape and with a synthetic three-page PDF. All mock values are labelled as test data; they are not presented as a real provider response.

The local anonymised source `ocr_test_3pages_mixed.pdf` was inspected read-only:

- it has three pages;
- page 2 has no usable text layer and is correctly routed to rendered-image OCR;
- page 3 has a usable text layer, and PyMuPDF `find_tables()` confirms one `4×3` table.

The visible test source on page 2 contains the three rows `Утренняя / 7 / 4`, `Дневная / 6 / 4`, and `Вечерняя / 5 / 4`. The historical raw Yandex JSON for that manual E2E run is not present locally: the available `fixtures/vision/*.json` belong to prior OCR-002B samples and do not describe this document. Therefore this stage does not claim that a new live Vision result was obtained or that those historical numeric strings were independently re-read from Vision.

## Defect 1: lost numeric values on scanned table page

### Root cause

The loss occurred in the Yandex mapper, before the Document Model and DOCX renderer:

1. Native `tables[].cells[].text` was copied into `TableCell`.
2. All normal OCR blocks located inside the table geometry were then removed to prevent duplicate paragraphs.
3. When a native table cell was empty but its number existed as a separate positioned OCR block, the only copy of that number was removed.

`DocxRenderer` was not the loss point: it writes each `TableCell.text` directly and the new regression test confirms that reopening the generated DOCX preserves every cell value.

### Correction

For a **native cell with empty `text` and a bounding box**, the mapper now copies only OCR block text whose center lies inside that exact cell. It does not synthesize content, alter non-empty native cells, or use neighbouring cells. Non-empty cell behaviour remains unchanged, avoiding regressions where Vision segments cell and block text differently.

The regression fixture uses synthetic blocks for the three reported rows and validates preservation of `7/4`, `6/4`, and `5/4` in both the Document Model and a reopened DOCX.

## Defect 2: native PDF table emitted as plain text

### Root cause

`InputPreprocessor` extracted `page.get_text("text")` for text-layer pages but never called `PyMuPDF.find_tables()`. Consequently table text was passed as ordinary paragraphs and no `Table` entered the internal model.

### Correction

For text-layer PDF pages the preprocessor now obtains confirmed tables through `find_tables()` and passes neutral native-table data to `DocumentOCRService`. The service converts it to the independent `Table`, `TableRow`, and `TableCell` models. Text blocks whose centers fall inside a confirmed table are excluded from paragraph creation; surrounding blocks retain geometry and are ordered together with the table by `ReadingOrderResolver`.

Only `find_tables()` results are converted. No table is inferred from plain text, and `None` cell values become explicit empty strings.

## Verification

The added `tests/test_mixed_pdf_regressions.py` verifies:

- separate numeric OCR blocks reach empty native cells without duplicate paragraphs;
- generated DOCX can be reopened with `python-docx` and has the same cell values;
- a mixed three-page PDF produces source pages `0, 1, 2`;
- the scanned page creates the first editable `4×3` table;
- the text-layer page creates the second editable `4×3` table;
- text after the native table remains after it;
- the reopened DOCX has two tables of `4×3` and two explicit page breaks (three source pages).

Final local regression result:

```text
uv run pytest -q  — 76 passed
git diff --check  — passed
```

## Limitations

- The exact historic Yandex JSON from the manual E2E run was not retained locally, so a live-provider value-by-value assertion is intentionally not claimed. A future approved manual rerun can verify that the now-preserved block values equal the current provider output.
- Cell recovery requires both an empty native `cells[].text` and cell geometry. If either is absent, the mapper preserves the provider cell value unchanged rather than guessing.
- PyMuPDF native tables preserve cell text and order, not visual styling, merged-cell semantics, or arbitrary PDF reading order beyond its confirmed table geometry.
