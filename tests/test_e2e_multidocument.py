"""Local E2E coverage for multi-page inputs through the shared OCR service.

Every provider response is a mock: these tests must never make a billed OCR
request or require a Telegram token.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageDraw

from ocr_document_bot.adapters.telegram import TelegramOCRService
from ocr_document_bot.document_model import Table
from ocr_document_bot.domain import InputFile
from ocr_document_bot.ocr_engine import DocumentOCRService
from ocr_document_bot.output_policy import OutputFormat
from ocr_document_bot.preprocessing import InputPreprocessor


def _scanned_png(*, ruled_table: bool = False) -> bytes:
    image = Image.new("RGB", (240, 120), "white")
    draw = ImageDraw.Draw(image)
    if ruled_table:
        for x in (20, 120, 220):
            draw.line((x, 20, x, 100), fill="black", width=2)
        for y in (20, 60, 100):
            draw.line((20, y, 220, y), fill="black", width=2)
    else:
        draw.rectangle((10, 10, 230, 110), outline="black", width=1)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _pdf(*, pages: tuple[str, ...]) -> bytes:
    document = fitz.open()
    scan = _scanned_png()
    for source in pages:
        page = document.new_page()
        if source == "scan":
            page.insert_image(page.rect, stream=scan)
        else:
            page.insert_text((72, 72), source)
    output = document.tobytes()
    document.close()
    return output


def _tiff() -> bytes:
    first = Image.new("RGB", (100, 60), "lightblue")
    second = Image.new("RGB", (100, 60), "lightyellow")
    output = BytesIO()
    first.save(output, format="TIFF", save_all=True, append_images=[second])
    return output.getvalue()


def _response(text: str, *, table: bool = False) -> dict[str, object]:
    blocks = [
        {
            "boundingBox": {"vertices": [{"x": "10", "y": "10"}, {"x": "90", "y": "25"}]},
            "lines": [{"text": text}],
        }
    ]
    tables: list[dict[str, object]] = []
    if table:
        tables = [
            {
                "rowCount": "2",
                "columnCount": "2",
                "boundingBox": {"vertices": [{"x": "0", "y": "0"}, {"x": "100", "y": "100"}]},
                "cells": [
                    {"rowIndex": "0", "columnIndex": "0", "text": "H1"},
                    {"rowIndex": "0", "columnIndex": "1", "text": "H2"},
                    {"rowIndex": "1", "columnIndex": "0", "text": "A"},
                    {"rowIndex": "1", "columnIndex": "1", "text": "B"},
                ],
            }
        ]
    return {"textAnnotation": {"width": "100", "height": "100", "blocks": blocks, "tables": tables}}


class RecordingVision:
    def __init__(self, responses: list[dict[str, object]], *, failure_at: int | None = None) -> None:
        self.responses = responses
        self.failure_at = failure_at
        self.calls: list[InputFile] = []

    def recognize(self, input_file: InputFile, *, language_codes: tuple[str, ...], model: str) -> dict[str, object]:
        self.calls.append(input_file)
        if self.failure_at == len(self.calls):
            raise TimeoutError("simulated page timeout")
        return self.responses[len(self.calls) - 1]


def _service(vision: RecordingVision) -> DocumentOCRService:
    return DocumentOCRService(vision, preprocessor=InputPreprocessor(), language_codes=("ru", "en"))


def test_e2e_text_pdf_never_calls_vision_and_preserves_page_order() -> None:
    native_one = "Native first page has enough meaningful text for extraction."
    native_two = "Native second page also has enough meaningful text here."
    vision = RecordingVision([])

    document = _service(vision).process(InputFile("text.pdf", "application/pdf", _pdf(pages=(native_one, native_two)), "telegram"))

    assert [page.number for page in document.pages] == [0, 1]
    assert vision.calls == []
    text = [element.text for page in document.pages for element in page.elements if hasattr(element, "text")]
    assert text == [native_one, native_two]


def test_e2e_telegram_service_returns_text_pdf_inline_without_vision() -> None:
    native = "Native PDF sent through Telegram has enough text for local extraction."
    vision = RecordingVision([])
    service = TelegramOCRService(vision, preprocessor=InputPreprocessor())

    processed = service.process(InputFile("telegram-text.pdf", "application/pdf", _pdf(pages=(native,)), "telegram"))

    assert vision.calls == []
    assert processed.decision.format is OutputFormat.INLINE_TEXT
    assert processed.decision.text == native


def test_e2e_mixed_pdf_keeps_native_text_and_native_table_without_duplicates() -> None:
    native_one = "Native first page has enough meaningful text for extraction."
    native_three = "Native third page has enough meaningful text for extraction."
    vision = RecordingVision([_response("Block inside native table", table=True)])

    document = _service(vision).process(InputFile("mixed.pdf", "application/pdf", _pdf(pages=(native_one, "scan", native_three)), "telegram"))

    assert [page.number for page in document.pages] == [0, 1, 2]
    assert len(vision.calls) == 1
    assert isinstance(document.pages[1].elements[0], Table)
    table = document.pages[1].elements[0]
    assert [[cell.text for cell in row.cells] for row in table.rows] == [["H1", "H2"], ["A", "B"]]
    all_text = [element.text for page in document.pages for element in page.elements if hasattr(element, "text")]
    assert all_text == [native_one, native_three]
    assert sum(cell.text == "A" for row in table.rows for cell in row.cells) == 1


def test_e2e_multipage_tiff_calls_vision_once_per_page_in_order() -> None:
    vision = RecordingVision([_response("TIFF page one"), _response("TIFF page two")])

    document = _service(vision).process(InputFile("pages.tiff", "image/tiff", _tiff(), "telegram"))

    assert [page.number for page in document.pages] == [0, 1]
    assert [call.filename for call in vision.calls] == ["pages-page-1.jpg", "pages-page-2.jpg"]
    assert [page.elements[0].text for page in document.pages] == ["TIFF page one", "TIFF page two"]


def test_e2e_scanned_pdf_passes_rendered_page_to_visual_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    from ocr_document_bot.providers import yandex_document_mapper as mapper
    from ocr_document_bot.document_model.visual_table_detector import VisualTableDetection

    captured: list[tuple[str | None, tuple[int, int], tuple[float, ...]]] = []

    class SpyDetector:
        def detect(self, image_path: Path, block_centers, *, ocr_width=None, ocr_height=None):
            with Image.open(image_path) as image:
                captured.append((image.format, image.size, tuple(value for point in block_centers for value in point)))
            return VisualTableDetection("not_detected", (), 0.0, image.width, image.height)

    monkeypatch.setenv("OCR_ENABLE_VISUAL_TABLE_DETECTION", "true")
    monkeypatch.setattr(mapper, "VisualTableDetector", SpyDetector)
    vision = RecordingVision([_response("Scanned ruled table text")])

    document = _service(vision).process(InputFile("scan.pdf", "application/pdf", _pdf(pages=("scan",)), "telegram"))

    assert len(vision.calls) == 1
    assert vision.calls[0].mime_type == "image/jpeg"
    assert captured and captured[0][0] == "JPEG"
    assert captured[0][1][0] > 0 and captured[0][1][1] > 0
    assert captured[0][2] == (50.0, 17.5)
    assert document.pages[0].number == 0


def test_e2e_page_timeout_returns_no_partial_document() -> None:
    vision = RecordingVision([_response("first"), _response("second")], failure_at=2)

    with pytest.raises(TimeoutError, match="page timeout"):
        _service(vision).process(InputFile("pages.tiff", "image/tiff", _tiff(), "telegram"))

    assert len(vision.calls) == 2
