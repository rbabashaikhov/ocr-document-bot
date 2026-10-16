import json
from pathlib import Path

import pytest

from ocr_document_bot.document_model import LayoutTableDetector, OCRProvenance, Paragraph, Point, BoundingBox, Table, TableCandidate
from ocr_document_bot.providers.yandex_document_mapper import document_from_yandex_responses


def paragraph(identifier: str, row: int, column: int, text: str = "x", *, width: int = 30, height: int = 10) -> Paragraph:
    left, top = column * 80, row * 30
    return Paragraph(
        id=identifier, text=text,
        geometry=BoundingBox(vertices=(Point(x=left, y=top), Point(x=left + width, y=top + height))),
        provenance=OCRProvenance(provider="test", source_page_number=0, source_order=row * 10 + column, source_type="block"),
    )


def test_layout_detector_reconstructs_dense_grid_and_consumes_each_source_block_once() -> None:
    blocks = [paragraph(f"{row}-{column}", row, column) for row in range(3) for column in range(2)]
    result = LayoutTableDetector().detect(blocks)
    assert result.table is not None
    assert result.table.row_count == 3 and result.table.column_count == 2
    assert len(result.consumed_block_ids) == 6
    assert [cell.text for cell in result.table.rows[2].cells] == ["x", "x"]


def test_irregular_or_incomplete_grid_becomes_candidate_and_preserves_source_blocks() -> None:
    blocks = [paragraph("0-0", 0, 0), paragraph("0-1", 0, 1), paragraph("1-0", 1, 0), paragraph("2-0", 2, 0), paragraph("2-1", 2, 1)]
    result = LayoutTableDetector().detect(blocks)
    assert result.table is None
    assert isinstance(result.candidate, TableCandidate)
    assert result.consumed_block_ids == frozenset()
    assert set(result.candidate.source_block_ids) == {block.id for block in blocks}


def test_two_column_prose_is_not_promoted_to_a_table() -> None:
    blocks = [paragraph("left-1", 0, 0, width=65), paragraph("right-1", 0, 1, width=65), paragraph("left-2", 1, 0, width=65), paragraph("right-2", 1, 1, width=65), paragraph("left-3", 2, 0, width=65)]
    result = LayoutTableDetector().detect(blocks)
    assert result.table is None


def test_missing_geometry_never_creates_a_table() -> None:
    blocks = [Paragraph(id=str(index), text="x", provenance=OCRProvenance(provider="test", source_page_number=0, source_order=index, source_type="block")) for index in range(6)]
    result = LayoutTableDetector().detect(blocks)
    assert result.table is None and result.candidate is None


def test_native_table_preserves_empty_cells_spans_and_removes_overlapping_paragraphs() -> None:
    payload = {"result": {"page": "0", "textAnnotation": {"width": "200", "height": "100", "blocks": [
        {"layoutType": "LAYOUT_TYPE_TEXT", "boundingBox": {"vertices": [{"x": "10", "y": "10"}, {"x": "90", "y": "40"}]}, "lines": [{"text": "duplicated-cell"}]},
        {"layoutType": "LAYOUT_TYPE_TEXT", "boundingBox": {"vertices": [{"x": "10", "y": "80"}]}, "lines": [{"text": "after"}]},
    ], "tables": [{"boundingBox": {"vertices": [{"x": "0", "y": "0"}, {"x": "100", "y": "60"}]}, "rowCount": "2", "columnCount": "2", "cells": [
        {"rowIndex": "0", "columnIndex": "0", "rowSpan": "1", "columnSpan": "2", "text": "heading"},
        {"rowIndex": "1", "columnIndex": "0", "rowSpan": "1", "columnSpan": "1", "text": ""},
        {"rowIndex": "1", "columnIndex": "1", "rowSpan": "1", "columnSpan": "1", "text": "value"}
    ]}]}}}
    page = document_from_yandex_responses([payload]).pages[0]
    table = next(element for element in page.elements if isinstance(element, Table))
    assert table.rows[0].cells[0].column_span == 2
    assert table.rows[1].cells[0].text == ""
    assert [element.text for element in page.elements if isinstance(element, Paragraph)] == ["after"]


def test_multiple_native_tables_keep_page_boundaries_and_paragraph_between_them() -> None:
    def native_table(top: int):
        return {"boundingBox": {"vertices": [{"x": "0", "y": str(top)}, {"x": "50", "y": str(top + 20)}]}, "rowCount": "1", "columnCount": "1", "cells": [{"rowIndex": "0", "columnIndex": "0", "text": ""}]}
    payload = {"textAnnotation": {"width": "100", "height": "200", "blocks": [{"boundingBox": {"vertices": [{"x": "0", "y": "50"}]}, "lines": [{"text": "between"}]}], "tables": [native_table(0), native_table(100)]}}
    page = document_from_yandex_responses([payload]).pages[0]
    assert [element.kind for element in page.elements] == ["table", "paragraph", "table"]


def test_real_native_6x2_fixture_has_no_duplicate_paragraphs_inside_table() -> None:
    fixture = Path("fixtures/vision/ocr-002b-mixed.json")
    if not fixture.exists(): pytest.skip("local OCR-002B fixture unavailable")
    page = document_from_yandex_responses([json.loads(fixture.read_text())], model="markdown").pages[0]
    table = next(element for element in page.elements if isinstance(element, Table))
    assert (table.row_count, table.column_count) == (6, 2)
    assert sum(len(row.cells) for row in table.rows) == 12
    assert not any(
        isinstance(element, Paragraph) and element.geometry and table.geometry
        and table.geometry.left <= (element.geometry.left + element.geometry.right) / 2 <= table.geometry.right
        and table.geometry.top <= (element.geometry.top + element.geometry.bottom) / 2 <= table.geometry.bottom
        for element in page.elements
    )
