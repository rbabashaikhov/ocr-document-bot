import json
from pathlib import Path

import pytest

from ocr_document_bot.document_model import BoundingBox, Document, Heading, OCRProvenance, Page, Paragraph, Point, ReadingOrderResolver
from ocr_document_bot.providers.yandex_document_mapper import document_from_yandex_responses


def block(identifier: str, text: str, source_order: int, left: float | None, top: float | None, right: float | None = None, bottom: float | None = None, heading: bool = False):
    geometry = None if left is None else BoundingBox(vertices=(Point(x=left, y=top), Point(x=right or left + 20, y=bottom or top + 10)))
    provenance = OCRProvenance(provider="test", source_page_number=0, source_order=source_order, source_type="block")
    return Heading(id=identifier, text=text, level=1, geometry=geometry, provenance=provenance) if heading else Paragraph(id=identifier, text=text, geometry=geometry, provenance=provenance)


def ids(elements):
    return [element.id for element in elements]


def test_resolves_permuted_blocks_by_coordinates_without_loss_or_duplicates() -> None:
    elements = [block("third", "c", 0, 10, 300), block("first", "a", 1, 10, 10), block("second", "b", 2, 10, 100)]
    resolved = ReadingOrderResolver().resolve(elements, page_width=200)
    assert ids(resolved) == ["first", "second", "third"]
    assert sorted(ids(resolved)) == sorted(ids(elements))


def test_reads_two_columns_top_to_bottom_then_left_to_right() -> None:
    elements = [block("r2", "r2", 0, 120, 50), block("l2", "l2", 1, 10, 50), block("r1", "r1", 2, 120, 10), block("l1", "l1", 3, 10, 10)]
    assert ids(ReadingOrderResolver().resolve(elements, page_width=200)) == ["l1", "l2", "r1", "r2"]


def test_wide_heading_precedes_columns_and_empty_block_is_preserved() -> None:
    elements = [
        block("right", "right", 0, 120, 50),
        block("empty", "", 1, 10, 50),
        block("heading", "Title", 2, 0, 0, 200, 20, heading=True),
    ]
    resolved = ReadingOrderResolver().resolve(elements, page_width=200)
    assert ids(resolved) == ["heading", "empty", "right"]
    assert resolved[1].text == ""


def test_overlapping_boxes_and_missing_geometry_have_deterministic_source_fallback() -> None:
    elements = [block("overlap-b", "b", 2, 10, 10, 60, 40), block("unknown", "u", 0, None, None), block("overlap-a", "a", 1, 10, 10, 60, 40)]
    assert ids(ReadingOrderResolver().resolve(elements, page_width=100)) == ["overlap-a", "overlap-b", "unknown"]


def test_identical_coordinates_on_distinct_pages_do_not_cross_order_boundaries() -> None:
    first = Page(number=0, width=100, elements=ReadingOrderResolver().resolve([block("page-0", "a", 0, 10, 10)], 100))
    second = Page(number=1, width=100, elements=ReadingOrderResolver().resolve([block("page-1", "b", 0, 10, 10)], 100))
    document = Document(pages=[first, second], source_provider="test")
    assert [[element.id for element in page.elements] for page in document.pages] == [["page-0"], ["page-1"]]
    assert '"source_provider":"test"' in document.model_dump_json()


def test_yandex_mapper_maps_headings_paragraphs_and_tables_without_provider_json_in_model() -> None:
    payload = {"result": {"page": "0", "textAnnotation": {"width": "200", "height": "100", "blocks": [
        {"layoutType": "LAYOUT_TYPE_SECTION_HEADER", "boundingBox": {"vertices": [{"x": "0", "y": "0"}]}, "lines": [{"text": "H"}]},
        {"layoutType": "LAYOUT_TYPE_TEXT", "boundingBox": {"vertices": [{"x": "0", "y": "30"}]}, "lines": [{"text": "P"}]},
    ], "tables": [{"rowCount": "1", "columnCount": "1", "cells": [{"rowIndex": "0", "columnIndex": "0", "rowSpan": "1", "columnSpan": "1", "text": "cell"}]}]}}}
    document = document_from_yandex_responses([payload], model="page")
    page = document.pages[0]
    assert isinstance(page.elements[0], Heading)
    assert isinstance(page.elements[1], Paragraph)
    assert page.elements[2].rows[0].cells[0].text == "cell"
    assert page.elements[0].provenance.source_order == 0


@pytest.mark.parametrize("fixture_name", ["ocr-002b-text.json", "ocr-002b-table.json", "ocr-002b-mixed.json"])
def test_real_local_ocr_fixtures_map_without_loss(fixture_name: str) -> None:
    fixture = Path("fixtures/vision") / fixture_name
    if not fixture.exists():
        pytest.skip("OCR-002B local fixture is unavailable")
    document = document_from_yandex_responses([json.loads(fixture.read_text())])
    page = document.pages[0]
    source_orders = [element.provenance.source_order for element in page.elements]
    assert len(source_orders) == len(set(element.id for element in page.elements))
    assert page.elements
