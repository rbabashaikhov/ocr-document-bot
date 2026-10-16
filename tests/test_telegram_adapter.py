"""Telegram adapter tests with mock OCR and outbound Telegram objects."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
from ocr_document_bot.adapters.telegram import DocumentStore, PollingSafetyError, ProcessedOCR, TelegramAdapter, TelegramOCRService, _download_input, _friendly_input_error, assert_polling_safe
from ocr_document_bot.domain import InputFile
from ocr_document_bot.document_model import Document, OCRProvenance, Page, Paragraph
from ocr_document_bot.output_policy import OutputFormat, OutputPolicy


def _raw_response(*, table: bool = False) -> dict[str, object]:
    response: dict[str, object] = {"textAnnotation": {"width": "100", "height": "100", "blocks": [
        {"boundingBox": {"vertices": [{"x": "10", "y": "10"}, {"x": "90", "y": "30"}]}, "lines": [{"text": "Короткий текст"}]},
    ], "tables": []}}
    if table:
        response["textAnnotation"]["tables"] = [{"rowCount": "1", "columnCount": "1", "cells": [{"rowIndex": "0", "columnIndex": "0", "text": "cell"}]}]
    return response


class MockVision:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.received: InputFile | None = None

    def recognize(self, input_file: InputFile, *, language_codes: tuple[str, ...], model: str) -> dict[str, object]:
        self.received = input_file
        assert language_codes == ("ru", "en") and model == "page"
        return self.payload


@dataclass
class FakeMessage:
    chat: object = field(default_factory=lambda: SimpleNamespace(id=42))
    answers: list[tuple[str, object]] = field(default_factory=list)
    documents: list[tuple[object, str]] = field(default_factory=list)

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append((text, kwargs.get("reply_markup")))

    async def answer_document(self, document: object, *, caption: str) -> None:
        self.documents.append((document, caption))


def _document(text: str = "Короткий текст") -> Document:
    provenance = OCRProvenance(provider="test", source_page_number=0, source_order=0, source_type="block")
    return Document(source_provider="test", pages=[Page(number=0, elements=[Paragraph(id="p", text=text, provenance=provenance)])])


def _image_bytes(image_format: str = "JPEG") -> bytes:
    content = BytesIO()
    Image.new("RGB", (20, 20), "white").save(content, format=image_format)
    return content.getvalue()


def test_mock_ocr_maps_short_image_to_inline_result(monkeypatch) -> None:
    monkeypatch.setenv("OCR_ENABLE_VISUAL_TABLE_DETECTION", "false")
    vision = MockVision(_raw_response())
    processed = TelegramOCRService(vision, policy=OutputPolicy(2500)).process(InputFile("input.jpg", "image/jpeg", _image_bytes(), "telegram"))

    assert vision.received is not None
    assert processed.decision.format is OutputFormat.INLINE_TEXT
    assert processed.decision.text == "Короткий текст"


def test_mock_ocr_table_requires_docx() -> None:
    processed = TelegramOCRService(MockVision(_raw_response(table=True)), policy=OutputPolicy(2500)).process(InputFile("input.png", "image/png", _image_bytes("PNG"), "telegram"))

    assert processed.decision.format is OutputFormat.DOCX
    assert TelegramOCRService.render_docx(processed.document).startswith(b"PK")


def test_mock_telegram_inline_reply_has_docx_button() -> None:
    adapter = TelegramAdapter(TelegramOCRService(MockVision(_raw_response())))
    message = FakeMessage()
    processed = ProcessedOCR(_document(), OutputPolicy(2500).decide(_document()))

    asyncio.run(adapter._deliver(message, processed))

    assert message.answers[0][0] == "Короткий текст"
    markup = message.answers[0][1]
    assert markup.inline_keyboard[0][0].text == "Получить DOCX"
    key = markup.inline_keyboard[0][0].callback_data.removeprefix("docx:")
    assert adapter._documents.get(key, 42) == processed.document


def test_document_store_does_not_leak_between_chats() -> None:
    store = DocumentStore(maximum_items=1)
    key = store.put(1, _document())

    assert store.get(key, 2) is None
    assert store.get(key, 1) is not None


def test_long_simple_text_requires_docx() -> None:
    assert OutputPolicy(10).decide(_document("x" * 11)).format is OutputFormat.DOCX


def test_polling_safety_refuses_existing_webhook_without_mutation() -> None:
    class WebhookBot:
        async def get_webhook_info(self):
            return SimpleNamespace(url="https://n8n.example/webhook")

    try:
        asyncio.run(assert_polling_safe(WebhookBot()))
    except PollingSafetyError:
        pass
    else:
        raise AssertionError("Webhook must block polling")


def test_document_extension_is_used_when_telegram_reports_generic_mime_type() -> None:
    class DownloadBot:
        async def get_file(self, file_id: str):
            return SimpleNamespace(file_path="files/source")

        async def download_file(self, file_path: str):
            return BytesIO(_image_bytes("WEBP"))

    message = SimpleNamespace(
        photo=None,
        document=SimpleNamespace(file_name="scan.webp", mime_type="application/octet-stream", file_id="id", file_unique_id="unique"),
    )

    downloaded = asyncio.run(_download_input(message, DownloadBot()))

    assert downloaded.filename == "scan.webp"
    assert downloaded.mime_type == "image/webp"


def test_input_errors_are_safe_for_telegram_users() -> None:
    assert "паролем" in _friendly_input_error("PDF is encrypted and cannot be processed")
    assert "лимит" in _friendly_input_error("Prepared document exceeds configured job size limit")
    assert "повреждён" in _friendly_input_error("PDF is damaged or cannot be opened")
