# OCR-006E — Diagnosis of the real mixed-PDF E2E run

## Evidence analysed

The manually enabled local diagnostic record `local-diagnostics/vision/vision-diagnostic-*.json` was inspected read-only. It contains one Vision response: the scanned second page of `ocr_test_3pages_mixed.pdf`. Text-layer pages did not call Vision, as designed.

The record is redacted by design, but preserves response structure, bounding boxes, character counts, and numeric tokens. It is sufficient to distinguish provider recognition from mapper loss.

## Numeric-token result

| Response location | Missing `7`, `6`, `5` row values | Evidence |
| --- | --- | --- |
| Root `fullText` | Absent | Root field is empty |
| `textAnnotation.fullText` | Absent | Tokens contain only `4`, `0`, `18`, `12`, `0`, `18`, `12`, `2` |
| `blocks[].lines[].text` | Absent | The same set of available numeric tokens; no `7`, `6`, or `5` |
| `tables[].cells[].text` | Absent | Vision returned `tables: []` |
| `markdown` | Absent | Empty |

Therefore the missing numeric values never reach the Yandex mapper, Document Model, or DOCX renderer. The current mapper cannot preserve text that the provider did not return, and it must not fill cells from source-document expectations.

## Geometry check

The exact scanned page was rendered through the normal preprocessing route and evaluated with the OCR-block coordinates from the diagnostic record:

```text
Visual table status: detected
Grid: 8 rows × 4 columns
Mapped OCR blocks: 23
```

The Vision response did recognise some later numeric values (`0`, `18`, `12`). Their block centres fall into the expected visual-table cells, which confirms coordinate scale and visual-table mapping are working for present tokens. There are no blocks at all with the missing `7`, `6`, or `5` tokens to assign to the earlier rows. This rules out the OCR-006C empty-cell mapper path for this E2E response.

## Document Model and DOCX consequence

Because the tokens are absent upstream, the Document Model table cells for those positions remain empty, and the DOCX renderer faithfully writes those empty values. This is correct non-fabrication behaviour, not a downstream loss.

No mapper or renderer change is made in OCR-006E.

## Fourth physical page

The generated DOCX from this exact manual run was not retained, so a byte-for-byte layout inspection is unavailable. Existing renderer behaviour is nevertheless verified:

- a three-page Document Model produces exactly two explicit Word page-break elements;
- a local reproduction with the source three-page PDF and an `8×4` table renders as three physical LibreOffice PDF pages;
- no unconditional fourth-page break exists in the renderer.

The remaining explanation is reflow of the exact E2E content before the required break for source page 3. Retain the next generated DOCX locally and inspect its PDF conversion/page XML before changing margins, font sizes, or table row behaviour. No layout change is justified from the available evidence.

## Recommended, testable fallback

For a confirmed ruled table where critical cells are empty after a first OCR pass:

1. Use the already-confirmed visual grid to crop only empty cells, adding a small padding.
2. Upscale and contrast-normalise each crop locally.
3. Submit those crops to Vision only after explicit user approval, or to an independently evaluated local OCR engine.
4. Replace a cell only when the fallback itself returns text; retain provenance that identifies the second pass and crop geometry.
5. Keep a cell empty when fallback OCR has no result. Never copy numbers from neighbouring/expected rows.

This is a proposal only. It has not been implemented, does not alter current table detection, and requires a separate cost/quality evaluation before adoption.

## Verification

No code was changed after inspecting the real diagnostic response. Existing regression suite remains green:

```text
uv run pytest -q  — 78 passed
git diff --check  — passed
```
