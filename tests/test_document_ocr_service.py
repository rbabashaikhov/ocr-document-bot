"""Tests for mixed native/PDF OCR orchestration using a local mock provider."""

from __future__ import annotations

from io import BytesIO

import fitz
from PIL import Image

from ocr_document_bot.domain import InputFile
from ocr_document_bot.ocr_engine import DocumentOCRService
from ocr_document_bot.preprocessing import InputPreprocessor


def _mixed_pdf() -> bytes:
    image = BytesIO()
    Image.new("RGB", (60, 40), "white").save(image, format="PNG")
    document = fitz.open()
    text_page = document.new_page()
    text_page.insert_text((72, 72), "Native PDF text is long enough for safe extraction in this test.")
    scan_page = document.new_page()
    scan_page.insert_image(scan_page.rect, stream=image.getvalue())
    result = document.tobytes()
    document.close()
    return result


class MockVision:
    def __init__(self) -> None:
        self.calls: list[InputFile] = []

    def recognize(self, input_file: InputFile, *, language_codes: tuple[str, ...], model: str) -> dict[str, object]:
        self.calls.append(input_file)
        return {
            "textAnnotation": {
                "width": "100",
                "height": "100",
                "blocks": [{"lines": [{"text": "Текст со сканированной страницы"}]}],
                "tables": [],
            }
        }


def test_mixed_pdf_uses_vision_only_for_scanned_page_and_preserves_text() -> None:
    vision = MockVision()
    service = DocumentOCRService(vision, preprocessor=InputPreprocessor())

    document = service.process(InputFile("mixed.pdf", "application/pdf", _mixed_pdf(), "api"))

    assert [page.number for page in document.pages] == [0, 1]
    assert len(vision.calls) == 1
    assert vision.calls[0].mime_type == "image/jpeg"
    texts = [element.text for page in document.pages for element in page.elements if hasattr(element, "text")]
    assert any("Native PDF text" in text for text in texts)
    assert texts.count("Текст со сканированной страницы") == 1
