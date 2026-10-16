# OCR-006F — Targeted OCR Recovery

## Result

An opt-in second OCR pass can now recover text from visually non-empty, empty cells of a **confirmed visual table**. It is disabled by default and was tested only with mocks; no billed Vision request was made.

## Guardrails

| Control | Behaviour |
| --- | --- |
| `OCR_ENABLE_CELL_RECOVERY=false` | Default; no crop or extra request is made |
| Table scope | Only `Table` elements with `provenance.source_type == visual_table` |
| Cell scope | Only empty cells with geometry whose inset image crop has at least minimal dark-pixel evidence |
| `OCR_MAX_CELL_RECOVERY_REQUESTS=6` | Hard per-page cap on attempted second-pass requests |
| Provider result | A cell changes only when the second pass returns non-empty provider text |
| Error/empty result | Original cell, text, geometry, and first-pass provenance remain unchanged |

The crop removes a small border inset to avoid counting table rules as content, then enlarges the interior threefold before it is sent to the supplied Vision client. The implementation does not read an expected value, neighbouring cell, source PDF text, or diagnostic record.

## Pipeline placement

```text
first-page OCR → Yandex mapper → confirmed visual table
                                  ↓
              empty cell + visible ink → enlarged crop → optional second OCR
                                  ↓                         ↓
                          leave unchanged          provider text only
                                                        ↓
                                      TableCell(source_type=visual_table_cell_recovery)
```

The recovery stage runs inside `DocumentOCRService` while the rendered source page is still available. It does not change table detection, native Vision tables, Telegram transport, or the DOCX renderer.

## Provenance

Recovered text receives `OCRProvenance` with:

- `provider=yandex-vision-ocr`;
- original source page and source order;
- `source_type=visual_table_cell_recovery`;
- `provider_model=<initial-model>:cell-recovery`.

This makes a second-pass value distinguishable in the serialised Document Model and in diagnostics/review code.

## Tests

`tests/test_cell_recovery.py` uses mock clients and generated local images to verify:

- the disabled flag makes zero calls;
- only a visibly non-empty empty cell is sent as a crop;
- the crop is enlarged;
- recovered value and provenance are retained;
- blank cells and provider timeout preserve the original result;
- the request cap leaves later cells untouched;
- `DocumentOCRService` invokes recovery after the first mapping pass.

Full verification:

```text
uv run pytest -q  — 85 passed
git diff --check  — passed
```

## Limitations and next evaluation

- The crop-level call is synchronous and may be billed when explicitly enabled.
- The dark-pixel check is a conservative content signal, not a confidence score; faint text can be skipped and noise can still qualify.
- Recovery currently treats the provider crop text as a cell value. It does not apply numeric validation or infer expected values.
- Skewed/merged-cell crop accuracy and real-provider quality require a separately approved evaluation on anonymised fixtures before this flag is enabled operationally.

## Final real-E2E audit

The local diagnostic records from the approved E2E run establish the remaining `Дневная → Участники` outcome without another provider call.

The visual table is `8×4`. Replaying only the diagnostic geometry and the local test image through the selection logic gives this deterministic crop order:

```text
cell-1-1 → 7
cell-1-2 → 4
cell-2-1 → empty provider response   ← Дневная → Участники
cell-2-2 → 4
cell-3-1 → 5
cell-3-2 → 4
```

`cell-2-1` was the third attempted crop, so the configured limit of six requests did not suppress it. Its recorded Vision response has empty root/annotation full text, no blocks, no tables, and empty Markdown. Consequently the recovery correctly kept the first-pass empty cell: no provider text existed to put in the Document Model or DOCX.

The limit did stop further visually non-empty empty cells after the first six attempts, but that is unrelated to this cell. The remaining absence is a crop-level Vision recognition limitation, not a detector-selection, mapper, provenance, or renderer defect. No algorithm change is justified without a separately approved evaluation of another OCR approach or crop preprocessing strategy.
