"""Local-only validation for ignored OCR-004B artifacts and real OCR fixtures."""

import json
from pathlib import Path

import pytest
from docx import Document as WordDocument
from docx.table import Table as WordTable
from docx.text.paragraph import Paragraph as WordParagraph

from ocr_document_bot.document_model import Heading, Paragraph, Table
from ocr_document_bot.providers.yandex_document_mapper import document_from_yandex_responses


SCENARIOS = {
    "ordinary-text.docx": "ocr-002b-text.json",
    "native-table-6x2.docx": "ocr-002b-mixed.json",
    "mixed-document.docx": "ocr-002b-mixed.json",
    "complex-table-no-native.docx": "ocr-002b-table.json",
}


def _body_items(document: WordDocument):
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            yield "paragraph", WordParagraph(child, document).text
        elif child.tag.endswith("}tbl"):
            table = WordTable(child, document)
            yield "table", [[cell.text for cell in row.cells] for row in table.rows]


@pytest.mark.parametrize(("artifact_name", "fixture_name"), SCENARIOS.items())
def test_real_docx_artifact_matches_document_model(artifact_name: str, fixture_name: str) -> None:
    artifact = Path("artifacts/ocr-004b") / artifact_name
    fixture = Path("fixtures/vision") / fixture_name
    if not artifact.exists() or not fixture.exists():
        pytest.skip("local OCR-004B artifact or fixture unavailable")

    model = document_from_yandex_responses([json.loads(fixture.read_text())])
    output = WordDocument(artifact)
    expected = []
    for element in model.pages[0].elements:
        if isinstance(element, (Paragraph, Heading)):
            expected.append(("paragraph", element.text))
        elif isinstance(element, Table):
            expected.append(("table", [[cell.text for cell in row.cells] for row in element.rows]))

    actual = list(_body_items(output))
    assert actual == expected
    assert sum(kind == "table" for kind, _ in actual) == sum(isinstance(element, Table) for element in model.pages[0].elements)
