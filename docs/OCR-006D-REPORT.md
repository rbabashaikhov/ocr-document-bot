# OCR-006D — Diagnosis of missing numeric cells

## Evidence available for this run

The historical raw Yandex Vision response and generated DOCX from the repeated manual E2E run were not saved locally. A read-only scan found only OCR-002B fixtures, which describe different documents; they cannot establish whether Vision returned the missing numbers for `ocr_test_3pages_mixed.pdf`.

The anonymised source PDF itself was inspected locally without upload:

- it has three source pages;
- page 2 is a scan with no usable PDF text layer and is routed to Vision;
- page 3 has a text layer and `PyMuPDF.find_tables()` confirms one `4×3` table, consistent with the repaired result.

The visible page-2 test table contains the reported morning/day/evening numeric values. This is source-document evidence only, not a claim about the unavailable historic Vision response.

## Numeric-cell diagnosis

### Proven historical loss path

OCR-006C established a concrete loss path in the mapper:

1. It built `TableCell.text` from `tables[].cells[].text`.
2. It then removed positioned OCR blocks inside the accepted native table to avoid duplicate paragraphs.
3. An empty native cell whose number was supplied only by a positioned block therefore became empty in the Document Model and DOCX.

The correction remains deliberately narrow: an **empty** native cell is filled only from OCR blocks whose centre lies inside that cell's bounding box. Non-empty native cells remain provider-authoritative. No expected value, neighbouring-cell value, or source-image text is used by the mapper.

Synthetic regression coverage reproduces the reported three rows and proves that numeric blocks appear once in the model and in a DOCX reopened by `python-docx`. This is a test of the loss mechanism, not a substitute for the missing raw response.

### What cannot yet be concluded

Without the response from the latest E2E run, it is not possible to distinguish these two cases for its missing values:

1. Vision returned numbers in `fullText`, `blocks[].lines[].text`, `tables[].cells[].text`, or `markdown`, and a remaining mapping issue lost them.
2. Vision did not return the numbers, so no safe application-side reconstruction is possible.

No values were added from the source PDF to production output.

## Safe diagnostic recording for the next approved manual run

Set this value only in the local, ignored `.env` when diagnosing an anonymised test document:

```dotenv
OCR_DIAGNOSTICS_DIR=local-diagnostics/vision
```

When an already authorised OCR request succeeds, `DiagnosticVisionClient` writes an ignored `vision-diagnostic-*.json` record. It contains:

- page/table/cell structure and bounding-box coordinates;
- character counts and numeric tokens from root/annotation `fullText`, `blocks[].lines[].text`, `tables[].cells[].text`, and `markdown`;
- no raw OCR text, file names, source image/PDF bytes, credentials, or request headers.

The next diagnostic checklist is therefore:

1. Run only with the user's explicit paid-call approval and a dedicated development bot without webhook.
2. Send the anonymised `ocr_test_3pages_mixed.pdf`.
3. Inspect the resulting ignored diagnostic record for `7`, `6`, `5`, and the hour values in the relevant block/cell paths.
4. If the tokens exist in blocks but not cells, compare their recorded boxes with the target cell boxes; that is evidence for mapper behaviour.
5. If tokens are absent from all recorded fields, record a provider-recognition limitation. A safe fallback is to keep the cells empty and present the existing source image/PDF alongside the editable DOCX; do not manufacture numbers. A provider-approved alternative OCR mode can be evaluated separately.

## Fourth DOCX page diagnosis

`DocxRenderer` adds one explicit page break between Document Model pages. A three-page model therefore contains exactly two explicit Word page-break elements. Local reproduction using the provided three-page source PDF, an `8×4` mocked scanned-page table, and conversion through LibreOffice produced:

```text
Document Model pages: 3
DOCX explicit page breaks: 2
Rendered PDF pages: 3
```

This rules out an unconditional extra page break in the current renderer. The fourth page reported by manual E2E is consequently most consistent with Word/LibreOffice reflow caused by the actual page-2 content exceeding available page height before the required break for source page 3. The historic DOCX was not saved, so this remains a reasoned diagnosis rather than a byte-for-byte reproduction.

No renderer change is made at this stage: shrinking fonts, margins, or table rows without the actual overflowing DOCX would mask the cause and can reduce readability. Save the next generated DOCX locally with the diagnostic record; then identify which paragraph/table row crossed the page boundary before making a layout-specific change.

## Verification

```text
uv run pytest -q  — 78 passed
git diff --check  — passed
```

No new paid OCR requests, table-algorithm changes, deployment, Email work, or Telegram transport behaviour changes were made. The only Telegram startup addition is the disabled-by-default diagnostic-client wrapper activated by `OCR_DIAGNOSTICS_DIR`.
