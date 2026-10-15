"""aiogram 3 Telegram transport for the local OCR service.

Polling never removes a webhook.  ``run_polling`` refuses to start when a
webhook is configured, protecting an existing n8n bot that shares the token.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
import mimetypes
import os
from pathlib import Path
import tempfile
from typing import Any, Protocol
from uuid import uuid4

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Document as TelegramDocument, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ocr_document_bot.document_model import Document
from ocr_document_bot.output_policy import OutputDecision, OutputFormat, OutputPolicy
from ocr_document_bot.preprocessing import InputPreprocessor
from ocr_document_bot.providers import YandexVisionClient, YandexVisionConfig
from ocr_document_bot.providers.yandex_document_mapper import document_from_yandex_responses
from ocr_document_bot.renderers import DocxRenderer
from ocr_document_bot.domain import InputFile
from ocr_document_bot.providers.yandex_vision import load_env_file


SUPPORTED_IMAGES = frozenset({"image/jpeg", "image/png"})


class PollingSafetyError(RuntimeError):
    """Polling would conflict with an existing webhook consumer."""


class VisionRawClient(Protocol):
    def recognize(self, input_file: InputFile, *, language_codes: tuple[str, ...], model: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ProcessedOCR:
    document: Document
    decision: OutputDecision


class TelegramOCRService:
    """Synchronous OCR orchestration invoked in a worker thread by aiogram."""

    def __init__(self, vision: VisionRawClient, *, preprocessor: InputPreprocessor | None = None, policy: OutputPolicy | None = None) -> None:
        self._vision = vision
        self._preprocessor = preprocessor or InputPreprocessor(_max_file_size())
        self._policy = policy or OutputPolicy()

    def process(self, input_file: InputFile) -> ProcessedOCR:
        prepared = self._preprocessor.prepare(input_file)
        raw = self._vision.recognize(prepared, language_codes=_languages(), model="page")
        source_image = _temporary_source_image(prepared)
        try:
            document = document_from_yandex_responses([raw], model="page", source_images=[source_image] if source_image else None)
        finally:
            if source_image:
                source_image.unlink(missing_ok=True)
        return ProcessedOCR(document=document, decision=self._policy.decide(document))

    @staticmethod
    def render_docx(document: Document) -> bytes:
        stream = BytesIO()
        DocxRenderer().render(document).save(stream)
        return stream.getvalue()


@dataclass(frozen=True)
class _StoredDocument:
    chat_id: int
    document: Document


class DocumentStore:
    """Small in-memory store for the optional “Получить DOCX” button."""

    def __init__(self, maximum_items: int = 100) -> None:
        self._maximum_items = maximum_items
        self._items: OrderedDict[str, _StoredDocument] = OrderedDict()

    def put(self, chat_id: int, document: Document) -> str:
        key = uuid4().hex
        self._items[key] = _StoredDocument(chat_id, document)
        self._items.move_to_end(key)
        while len(self._items) > self._maximum_items:
            self._items.popitem(last=False)
        return key

    def get(self, key: str, chat_id: int) -> Document | None:
        item = self._items.get(key)
        return item.document if item and item.chat_id == chat_id else None


class TelegramAdapter:
    def __init__(self, service: TelegramOCRService, *, documents: DocumentStore | None = None) -> None:
        self._service = service
        self._documents = documents or DocumentStore()
        self.router = Router(name="ocr-telegram")
        self.router.message.register(self._start, CommandStart())
        self.router.message.register(self._handle_input, F.photo | F.document)
        self.router.callback_query.register(self._send_requested_docx, F.data.startswith("docx:"))

    async def _start(self, message: Message) -> None:
        await message.answer("Отправьте изображение JPG или PNG. Распознавание начнётся после отправки файла.")

    async def _handle_input(self, message: Message, bot: Bot) -> None:
        try:
            input_file = await _download_input(message, bot)
        except ValueError as error:
            await message.answer(str(error))
            return
        await message.answer("Распознаю изображение…")
        try:
            processed = await asyncio.to_thread(self._service.process, input_file)
            await self._deliver(message, processed)
        except Exception:
            # Provider and file errors stay server-side; never expose tokens or
            # implementation details to a chat.
            await message.answer("Не удалось распознать файл. Проверьте формат изображения и попробуйте ещё раз.")

    async def _deliver(self, message: Message, processed: ProcessedOCR) -> None:
        if processed.decision.format is OutputFormat.INLINE_TEXT:
            key = self._documents.put(message.chat.id, processed.document)
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Получить DOCX", callback_data=f"docx:{key}")]])
            await message.answer(processed.decision.text or "", reply_markup=markup)
            return
        await self._send_docx(message, processed.document)

    async def _send_requested_docx(self, callback: CallbackQuery) -> None:
        if callback.message is None or not callback.data:
            await callback.answer("Документ недоступен", show_alert=True)
            return
        document = self._documents.get(callback.data.removeprefix("docx:"), callback.message.chat.id)
        if document is None:
            await callback.answer("Документ больше недоступен. Отправьте изображение заново.", show_alert=True)
            return
        await callback.answer()
        await self._send_docx(callback.message, document)

    async def _send_docx(self, message: Message, document: Document) -> None:
        content = await asyncio.to_thread(self._service.render_docx, document)
        await message.answer_document(BufferedInputFile(content, filename="ocr-result.docx"), caption="Редактируемый DOCX")


async def run_polling() -> None:
    """Run local polling only after proving that no webhook owns the token."""
    load_env_file(Path(".env"))
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured")
    vision = YandexVisionClient(YandexVisionConfig.from_env())
    bot = Bot(token=token)
    try:
        await assert_polling_safe(bot)
        dispatcher = Dispatcher()
        dispatcher.include_router(TelegramAdapter(TelegramOCRService(vision)).router)
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        vision.close()
        await bot.session.close()


async def assert_polling_safe(bot: Bot) -> None:
    """Check only: this intentionally never calls deleteWebhook."""
    webhook = await bot.get_webhook_info()
    if webhook.url:
        raise PollingSafetyError("Telegram webhook is configured; polling was not started and webhook was not changed")


async def _download_input(message: Message, bot: Bot) -> InputFile:
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        stream = await bot.download_file(file.file_path or "")
        return InputFile(filename=f"telegram-{photo.file_unique_id}.jpg", mime_type="image/jpeg", content=stream.read(), source="telegram")
    document: TelegramDocument | None = message.document
    if document is None:
        raise ValueError("Отправьте JPG или PNG изображение.")
    mime_type = document.mime_type or mimetypes.guess_type(document.file_name or "")[0]
    if mime_type not in SUPPORTED_IMAGES:
        raise ValueError("Поддерживаются только изображения JPG и PNG.")
    file = await bot.get_file(document.file_id)
    stream = await bot.download_file(file.file_path or "")
    return InputFile(filename=document.file_name or f"telegram-{document.file_unique_id}", mime_type=mime_type, content=stream.read(), source="telegram")


def _temporary_source_image(input_file: InputFile) -> Path | None:
    if input_file.mime_type not in SUPPORTED_IMAGES:
        return None
    suffix = ".jpg" if input_file.mime_type == "image/jpeg" else ".png"
    with tempfile.NamedTemporaryFile(prefix="ocr-telegram-", suffix=suffix, delete=False) as handle:
        handle.write(input_file.content)
        return Path(handle.name)


def _languages() -> tuple[str, ...]:
    configured = os.getenv("OCR_LANGUAGE_CODES", "ru,en")
    return tuple(value.strip() for value in configured.split(",") if value.strip())


def _max_file_size() -> int:
    try:
        return int(os.getenv("OCR_MAX_FILE_SIZE_BYTES", str(10 * 1024 * 1024)))
    except ValueError as error:
        raise ValueError("OCR_MAX_FILE_SIZE_BYTES must be an integer") from error
