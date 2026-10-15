# OCR-003A — Document Model and reading-order recovery

## Result

Implemented a provider-neutral Pydantic v2 document model in `src/ocr_document_bot/document_model/` and a separate Yandex mapper in `providers/yandex_document_mapper.py`. The internal model is independent of the Yandex JSON names and serializes through Pydantic's `model_dump_json()`.

The model contains `Document`, `Page`, `Paragraph`, `Heading`, `Table`, `TableRow`, `TableCell`, and `Picture`. Every element preserves a stable ID, optional polygon geometry, source page, source-array order, source type, provider, and optional provider model through `OCRProvenance`. `TableCell` retains indexes, spans, text and geometry. No renderer, adapter, API request, LLM, queue, or table-reconstruction heuristic was added.

## Mapping and multi-page input

`document_from_yandex_responses()` accepts a sequence of raw OCR response bodies, so an asynchronous/multi-page caller can map one response per page without changing the internal model. The mapper accepts both the current root `textAnnotation` response and the legacy `result.textAnnotation` wrapper observed in OCR-002B. That compatibility remains at the provider boundary; `Document` does not expose Yandex-shaped fields.

Blocks are mapped one-to-one to text elements, including blocks with no lines (`text=""`). `LAYOUT_TYPE_TITLE` maps to heading level 1 and `LAYOUT_TYPE_SECTION_HEADER` maps to level 2; other values map to `Paragraph`. These are conservative classification choices, not a claim that OCR determines an exact document heading hierarchy. Directly supplied `tables[]` map to `Table`/`TableRow`/`TableCell`; the task intentionally adds no geometry-based table fallback.

## Reading Order Resolver

The resolver runs independently for each `Page`:

1. It partitions elements into those with and without geometry. Geometry-free elements are retained—never dropped or duplicated—and placed at the end in original source order because their visual position is unknowable.
2. It identifies wide elements (at least 75% of page width) as spanning separators, such as a title above columns.
3. Between separators, it groups horizontally disjoint bounding boxes into columns. It sorts columns left-to-right, then sorts within each column top-to-bottom and left-to-right.
4. Equal/overlapping coordinates use source order then element ID as deterministic tie breakers. All elements remain present exactly once.

This corrects the OCR-002B observation that provider array order is not necessarily reading order. It is deliberately conservative: overlapping, irregular, or magazine-like layouts may require a later configurable layout policy rather than an assumption that a universal geometric rule is correct.

## Tested cases

- ordinary reordered blocks: coordinate order replaces source-array order;
- two columns: complete left column before right column;
- wide heading followed by columns and an empty text block;
- overlapping boxes and missing geometry: deterministic fallback with no loss;
- separate pages with identical coordinates: no cross-page reordering;
- headings, paragraphs, direct tables and cell spans from a Yandex-shaped payload;
- locally available, Git-ignored real OCR-002B fixtures (`text`, `table`, `mixed`) with no new paid OCR calls.

The real fixtures are read only by tests and are excluded from Git. This report contains no extracted document text or raw provider JSON.

Verification: `uv run pytest` completed successfully with **21 passed**. `uv run python -m compileall -q src` and `git diff --check` also completed successfully. No OCR API call was made during OCR-003A.

## Limitations and OCR-003 recommendation

The resolver cannot infer the correct visual position of an element lacking geometry, distinguish all multi-column layouts from complex overlapping designs, or reconstruct tables when `tables[]` is absent. Heading levels are heuristic mappings of two provider layout types. No confidence-based quality decision is possible because the observed responses do not expose documented text confidence.

For OCR-003, agree on a representative labelled layout corpus and expected reading sequence before evolving the resolver. Add measurement around reading-order accuracy, ambiguous-column handling, and direct-table span integrity. Implement a renderer only after that policy is accepted.
