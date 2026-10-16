# OCR-003B — table recovery from Yandex Vision OCR

## Result

Implemented two table paths without new OCR requests or renderers:

- **Native Table Parser** maps provider `tables[]` into provider-neutral `Table`, `TableRow`, and `TableCell` objects. It preserves cell text (including an empty string), row/column indexes, spans, cell/table geometry and provenance.
- **Layout Table Detector** runs only if a page contains no native tables. It is deliberately conservative: only a dense, regular grid of at least three rows becomes a `Table`. An incomplete or irregular but grid-like layout becomes a non-destructive `table_candidate`; source paragraphs remain. Geometry-free blocks produce neither a table nor a candidate.

`TableCandidate` is the only public-model extension. It is justified because an ambiguity must be represented without claiming a table exists; it contains source block IDs, geometry, a bounded confidence and a reason, but no duplicated text.

## Native parsing and duplicate prevention

Native tables are assembled row-by-row in numeric row order. The mapper creates an empty `TableRow` for every row declared by `rowCount`, even if the provider supplies no cells. This preserves empty rows as well as cells whose OCR text is empty. Directly supplied cell spans are retained unchanged; no inferred merge is created.

When a native table has geometry, a paragraph or heading whose bounding-box centre lies inside it is removed from normal page elements. Its text remains in the native table cell, preventing double delivery. Blocks outside the table remain in the page and Reading Order Resolver positions the table among surrounding paragraphs. If table geometry is missing, no source block is discarded.

## Geometric detector

For paragraphs with geometry, the detector:

1. clusters top coordinates into prospective rows and left coordinates into prospective columns using a tolerance derived from median block size;
2. maps every block to its nearest row/column cluster and calculates grid occupancy;
3. produces a recovered table only with at least three rows, 90% occupancy, one block per grid cell, and regular row/column spacing;
4. produces `table_candidate` for a grid-like, but incomplete/irregular/overlapping arrangement (50%+ occupancy);
5. otherwise leaves every block as an ordinary paragraph.

Recovered layout tables always use `row_span=column_span=1`: geometry alone does not establish a merged cell. No block is deleted unless the strict path has converted every consumed source block into exactly one cell.

## Real fixture results

All fixtures were already present locally from OCR-002B and remain ignored by Git. No text or raw JSON is reproduced here.

| Fixture | Result |
| --- | --- |
| Mixed document, native 6×2 | Parsed as one `Table` with 6 rows, 2 columns and 12 cells. Source paragraphs geometrically inside the table were removed, so table text is not duplicated. |
| Complex table, 21 blocks, `tables[]` absent | Kept as 21 paragraphs. Its geometry did not satisfy the strict grid test and was not promoted to a false table. |
| Ordinary text document | Kept as paragraphs; no table/candidate produced. |

The complex-table result is intentional: OCR-002B already showed multi-level headers and likely merged cells, while no native cell spans were returned. The current detector cannot prove a reliable grid from those blocks, so it preserves text rather than fabricating a table.

## Tests and verification

Covered cases:

- native 6×2 fixture, no duplicate table paragraphs;
- synthetic native table with a merged cell, empty cell and empty rows;
- multiple native tables separated by a paragraph;
- dense coordinate grid reconstructed as a table;
- incomplete/ambiguous grid yields `table_candidate` and leaves blocks intact;
- ordinary multi-column prose not promoted to a table;
- missing geometry;
- previously implemented reading-order, empty-block, page-boundary and real-fixture tests.

Verification completed locally:

```text
uv run pytest
28 passed in 0.15s
```

`uv run python -m compileall -q src` and `git diff --check` also passed. No OCR API call occurred.

## Limitations and DOCX renderer guidance

The detector is not a visual table recognizer: it will miss irregular tables, merged headers, borderless tables and tables mixed with multi-column prose. It may create a `table_candidate` for some unusually regular layout text; candidates must be surfaced as warnings, never rendered as factual tables automatically. Reading order inside a recovered cell comes from its single source block; multi-block cells are deliberately treated as ambiguous.

For DOCX rendering, render native or strict recovered tables as semantic tables, apply spans only when supplied natively, and keep cell geometry only as optional sizing evidence. Preserve `table_candidate` source paragraphs in the document and expose the ambiguity in metadata/logging. Before expanding heuristics, create a labelled corpus with merged headers and evaluate grid detection, cell assignment, span accuracy and false-positive rate.

OCR-004, renderer work, adapters and external calls are out of scope and have not been started.
