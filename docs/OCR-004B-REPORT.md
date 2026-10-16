# OCR-004B — verification of DOCX on real OCR results

## Scope and safety

Used only local, Git-ignored OCR-002B fixtures. No Yandex Vision request was made. Four DOCX files, their PDF conversions and PNG page previews were created under the Git-ignored `artifacts/ocr-004b/` directory. This report contains aggregate structure only; it does not reproduce document text or raw OCR JSON.

## Produced artifacts

| DOCX | Source fixture | Paragraphs | Tables | Table shape |
| --- | --- | ---: | ---: | --- |
| `ordinary-text.docx` | `ocr-002b-text.json` | 8 | 0 | — |
| `native-table-6x2.docx` | `ocr-002b-mixed.json` | 5 | 1 | 6×2 |
| `mixed-document.docx` | `ocr-002b-mixed.json` | 5 | 1 | 6×2 |
| `complex-table-no-native.docx` | `ocr-002b-table.json` | 21 | 0 | — |

The native-table and mixed-document artifacts are intentionally structurally identical: both use the only available mixed fixture, which contains the real native 6×2 table plus surrounding paragraphs/headings.

## Programmatic verification

For each artifact, local test code reopened the DOCX through `python-docx`, traversed the Word body in document order, and compared it exactly with the matching Document Model sequence:

- paragraph and table sequence matches the model;
- paragraph text including line breaks matches the model;
- table row/cell text matches the model;
- table count, rows and columns match the model;
- there is no extra paragraph/table item in the DOCX;
- the 6×2 native table contains 12 model cells and no source paragraph geometrically inside the table was rendered separately.

The complete suite result:

```text
uv run pytest
36 passed in 0.33s
```

## Visual verification

LibreOffice converted each DOCX to a local PDF and `pdftoppm` generated PNG previews. Visual inspection found:

- ordinary text is readable, uses normal paragraph flow and retains OCR line breaks;
- the mixed fixture renders headings, surrounding text and a visible 6×2 Word table in the correct broad sequence;
- the complex-table fixture renders as readable paragraph flow across two Word pages, without a fabricated table;
- the output is semantic Word formatting, not a pixel reproduction of the source scan.

The preview conversion emitted a non-blocking `javaldx` warning from LibreOffice; PDFs and PNGs were produced successfully. DOCX files were not modified during preview generation.

## Known limitations

- A fixture without native `tables[]` cannot become a guaranteed editable table. The complex source remains text until an accepted, evidence-backed table recovery policy handles it.
- Page flow is governed by Word, so a long source page may span multiple DOCX pages.
- The model has picture locations but no picture bytes; images are not rendered.
- There is no visual regression baseline or human semantic proofreading of OCR text in this phase; validation is model-to-DOCX fidelity.
- Artifacts may contain original document content and must remain local. `artifacts/ocr-004b/`, source samples and raw fixtures are excluded from Git.

No XLSX, adapters, OCR algorithm changes, new infrastructure, external OCR calls, or later-stage work was performed.
