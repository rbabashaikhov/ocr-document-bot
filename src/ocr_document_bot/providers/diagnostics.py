"""Opt-in, privacy-minimised Vision response diagnostics for local debugging."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import re
from typing import Any, Protocol
from uuid import uuid4

from ocr_document_bot.domain import InputFile


class VisionClient(Protocol):
    def recognize(self, input_file: InputFile, *, language_codes: tuple[str, ...], model: str) -> dict[str, Any]: ...

    def close(self) -> None: ...


class DiagnosticVisionClient:
    """Write numeric/structural evidence only after an explicitly enabled OCR call.

    Raw OCR JSON and source-file names are deliberately not persisted. This
    record is sufficient to determine whether a missing number was returned in
    full text, a block, a table cell, or Markdown.
    """

    def __init__(self, client: VisionClient, directory: Path) -> None:
        self._client = client
        self._directory = directory

    def recognize(self, input_file: InputFile, *, language_codes: tuple[str, ...], model: str) -> dict[str, Any]:
        response = self._client.recognize(input_file, language_codes=language_codes, model=model)
        self._directory.mkdir(parents=True, exist_ok=True)
        output = self._directory / f"vision-diagnostic-{uuid4().hex}.json"
        output.write_text(json.dumps(redact_response(response), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return response

    def close(self) -> None:
        self._client.close()


def redact_response(payload: Mapping[str, Any]) -> dict[str, object]:
    """Keep response structure, geometry, and numeric tokens; redact all text."""
    response = _mapping(payload.get("result")) or payload
    annotation = _mapping(response.get("textAnnotation"))
    return {
        "schema": "ocr-document-bot/vision-diagnostic-v1",
        "page": _scalar(response.get("page")),
        "fullText": _text_evidence(response.get("fullText")),
        "textAnnotation": {
            "width": _scalar(annotation.get("width")),
            "height": _scalar(annotation.get("height")),
            "fullText": _text_evidence(annotation.get("fullText")),
            "markdown": _text_evidence(annotation.get("markdown")),
            "blocks": [_block_evidence(index, block) for index, block in enumerate(_mappings(annotation.get("blocks")))],
            "tables": [_table_evidence(index, table) for index, table in enumerate(_mappings(annotation.get("tables")))],
        },
    }


def _block_evidence(index: int, block: Mapping[str, Any]) -> dict[str, object]:
    return {
        "index": index,
        "layoutType": _scalar(block.get("layoutType")),
        "boundingBox": _box(block.get("boundingBox")),
        "lines": [_text_evidence(line.get("text")) for line in _mappings(block.get("lines"))],
    }


def _table_evidence(index: int, table: Mapping[str, Any]) -> dict[str, object]:
    return {
        "index": index,
        "rowCount": _scalar(table.get("rowCount")),
        "columnCount": _scalar(table.get("columnCount")),
        "boundingBox": _box(table.get("boundingBox")),
        "cells": [
            {
                "rowIndex": _scalar(cell.get("rowIndex")),
                "columnIndex": _scalar(cell.get("columnIndex")),
                "rowSpan": _scalar(cell.get("rowSpan")),
                "columnSpan": _scalar(cell.get("columnSpan")),
                "boundingBox": _box(cell.get("boundingBox")),
                "text": _text_evidence(cell.get("text")),
            }
            for cell in _mappings(table.get("cells"))
        ],
    }


def _text_evidence(value: object) -> dict[str, object]:
    text = value if isinstance(value, str) else ""
    return {"character_count": len(text), "numeric_tokens": re.findall(r"\d+(?:[.,]\d+)?", text)}


def _box(value: object) -> list[dict[str, object]]:
    box = _mapping(value)
    return [{"x": _scalar(vertex.get("x")), "y": _scalar(vertex.get("y"))} for vertex in _mappings(box.get("vertices"))]


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _scalar(value: object) -> str | int | float | bool | None:
    return value if isinstance(value, (str, int, float, bool)) or value is None else None
