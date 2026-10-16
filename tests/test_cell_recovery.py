"""Mock-only tests for opt-in targeted OCR recovery of visual-table cells."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from ocr_document_bot.document_model import BoundingBox, OCRProvenance, Page, Point, Table, TableCell, TableRow
from ocr_document_bot.document_model import Document
from ocr_document_bot.domain import InputFile
from ocr_document_bot.ocr_engine import CellRecoveryService, DocumentOCRService
from ocr_document_bot.preprocessing import InputPreprocessor


def _box(left: float, top: float, right: float, bottom: float) -> BoundingBox:
    return BoundingBox(vertices=(Point(x=left, y=top), Point(x=right, y=bottom)))


def _page(columns: int = 2) -> Page:
    origin = OCRProvenance(provider="yandex-vision-ocr", source_page_number=0, source_order=0, source_type="visual_table")
    cells = [
        TableCell(text="", row_index=0, column_index=index, geometry=_box(index * 50, 0, (index + 1) * 50, 50), provenance=origin)
        for index in range(columns)
    ]
    table = Table(id="table", geometry=_box(0, 0, columns * 50, 50), provenance=origin, row_count=1, column_count=columns, rows=[TableRow(index=0, cells=cells)])
    return Page(number=0, width=columns * 50, height=50, elements=[table])


def _image(tmp_path: Path, *, columns: int = 2, values: tuple[str, ...] = ("7", "")) -> Path:
    image = Image.new("RGB", (columns * 50, 50), "white")
    draw = ImageDraw.Draw(image)
    for index, value in enumerate(values):
        if value:
            draw.text((index * 50 + 20, 18), value, fill="black")
    path = tmp_path / "cells.png"
    image.save(path)
    return path


class MockVision:
    def __init__(self, responses: list[dict[str, object]] | None = None, *, failure: bool = False) -> None:
        self.responses = responses or []
        self.failure = failure
        self.calls = []

    def recognize(self, input_file, *, language_codes: tuple[str, ...], model: str):
        self.calls.append(input_file)
        if self.failure:
            raise TimeoutError("mock recovery timeout")
        return self.responses[len(self.calls) - 1]


def _response(text: str) -> dict[str, object]:
    return {"textAnnotation": {"blocks": [{"lines": [{"text": text}]}], "tables": []}}


def test_disabled_recovery_makes_no_call(tmp_path: Path) -> None:
    vision = MockVision([_response("7")])

    result = CellRecoveryService(enabled=False).recover(_page(), image_path=_image(tmp_path), vision=vision, language_codes=("ru",), model="page")

    assert result.model_dump() == _page().model_dump()
    assert vision.calls == []


def test_recovers_only_visibly_nonempty_empty_cell_and_records_provenance(tmp_path: Path) -> None:
    vision = MockVision([_response("7")])

    result = CellRecoveryService(enabled=True, max_requests=2).recover(_page(), image_path=_image(tmp_path), vision=vision, language_codes=("ru",), model="page")

    cells = result.elements[0].rows[0].cells
    assert [cell.text for cell in cells] == ["7", ""]
    assert cells[0].provenance.source_type == "visual_table_cell_recovery"
    assert cells[0].provenance.provider_model == "page:cell-recovery"
    assert len(vision.calls) == 1
    crop = Image.open(BytesIO(vision.calls[0].content))
    assert crop.size[0] > 100 and crop.size[1] > 100


def test_blank_cell_and_failed_second_pass_leave_original_cells_unchanged(tmp_path: Path) -> None:
    blank = CellRecoveryService(enabled=True).recover(_page(), image_path=_image(tmp_path, values=("", "")), vision=MockVision([_response("7")]), language_codes=("ru",), model="page")
    failed_vision = MockVision(failure=True)
    failed = CellRecoveryService(enabled=True).recover(_page(), image_path=_image(tmp_path), vision=failed_vision, language_codes=("ru",), model="page")

    assert [cell.text for cell in blank.elements[0].rows[0].cells] == ["", ""]
    assert [cell.text for cell in failed.elements[0].rows[0].cells] == ["", ""]
    assert len(failed_vision.calls) == 1


def test_request_limit_leaves_later_empty_cells_untouched(tmp_path: Path) -> None:
    vision = MockVision([_response("1"), _response("2")])

    result = CellRecoveryService(enabled=True, max_requests=2).recover(_page(3), image_path=_image(tmp_path, columns=3, values=("1", "2", "3")), vision=vision, language_codes=("ru",), model="page")

    assert [cell.text for cell in result.elements[0].rows[0].cells] == ["1", "2", ""]
    assert len(vision.calls) == 2


def test_recovery_rejects_nonpositive_request_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        CellRecoveryService(enabled=True, max_requests=0)


def test_environment_flag_is_disabled_by_default_and_reads_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCR_ENABLE_CELL_RECOVERY", raising=False)
    monkeypatch.delenv("OCR_MAX_CELL_RECOVERY_REQUESTS", raising=False)
    assert CellRecoveryService.from_environment().enabled is False
    monkeypatch.setenv("OCR_ENABLE_CELL_RECOVERY", "true")
    monkeypatch.setenv("OCR_MAX_CELL_RECOVERY_REQUESTS", "2")
    configured = CellRecoveryService.from_environment()
    assert configured.enabled is True and configured.max_requests == 2


def test_document_service_runs_recovery_after_first_mapping(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from ocr_document_bot.ocr_engine import document_service

    image_path = _image(tmp_path)
    vision = MockVision([{}, _response("7")])
    monkeypatch.setattr(
        document_service,
        "document_from_yandex_responses",
        lambda *args, **kwargs: Document(pages=[_page()], source_provider="yandex-vision-ocr"),
    )
    service = DocumentOCRService(
        vision,
        preprocessor=InputPreprocessor(),
        cell_recovery=CellRecoveryService(enabled=True),
    )

    result = service.process(InputFile("table.png", "image/png", image_path.read_bytes(), "api"))

    assert len(vision.calls) == 2
    table = result.pages[0].elements[0]
    assert isinstance(table, Table)
    assert table.rows[0].cells[0].text == "7"
