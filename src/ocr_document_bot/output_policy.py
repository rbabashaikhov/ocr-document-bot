"""Provider-neutral decision about inline text versus an editable document."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os

from ocr_document_bot.document_model import Document, Heading, Paragraph, Picture, Table, TableCandidate


class OutputFormat(StrEnum):
    INLINE_TEXT = "inline_text"
    DOCX = "docx"


@dataclass(frozen=True)
class OutputDecision:
    format: OutputFormat
    text: str | None = None
    reason: str = ""


class OutputPolicy:
    """Keep transport choices outside OCR and rendering implementations."""

    def __init__(self, inline_text_max_chars: int | None = None) -> None:
        configured = inline_text_max_chars if inline_text_max_chars is not None else _max_inline_chars()
        if configured < 1:
            raise ValueError("OCR_INLINE_TEXT_MAX_CHARS must be positive")
        self._inline_text_max_chars = configured

    def decide(self, document: Document, *, requested_format: OutputFormat | None = None) -> OutputDecision:
        if requested_format is OutputFormat.DOCX:
            return OutputDecision(OutputFormat.DOCX, reason="requested_docx")
        elements = [element for page in document.pages for element in page.elements]
        if any(isinstance(element, (Table, TableCandidate, Picture)) for element in elements):
            return OutputDecision(OutputFormat.DOCX, reason="complex_structure")
        if not all(isinstance(element, (Paragraph, Heading)) for element in elements):
            return OutputDecision(OutputFormat.DOCX, reason="unsupported_structure")
        text = "\n\n".join(element.text for element in elements).strip()
        if len(text) <= self._inline_text_max_chars:
            return OutputDecision(OutputFormat.INLINE_TEXT, text=text, reason="short_simple_text")
        return OutputDecision(OutputFormat.DOCX, reason="text_too_long")


def _max_inline_chars() -> int:
    try:
        return int(os.getenv("OCR_INLINE_TEXT_MAX_CHARS", "2500"))
    except ValueError as error:
        raise ValueError("OCR_INLINE_TEXT_MAX_CHARS must be an integer") from error
