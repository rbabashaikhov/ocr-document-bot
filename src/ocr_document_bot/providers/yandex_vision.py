"""Minimal synchronous Yandex Vision OCR client and response inspection helpers."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Mapping

import httpx

from ocr_document_bot.domain import BoundingBox, DocumentModel, InputFile, Page, Table, TableCell, TextBlock


class VisionConfigurationError(ValueError):
    """Configuration is missing or selects conflicting authentication methods."""


class VisionAPIError(RuntimeError):
    """A non-successful HTTP response from Vision OCR, without exposing secrets."""


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE settings without overwriting the process environment.

    It supports the project's `.env.example` syntax only; it never evaluates
    shell interpolation or command substitutions.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip("\"'")


@dataclass(frozen=True, slots=True)
class YandexVisionConfig:
    folder_id: str | None
    api_key: str | None
    iam_token: str | None
    endpoint: str = "https://ai.api.cloud.yandex.net/ocr/v1"

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "YandexVisionConfig":
        load_env_file(env_file or Path(".env"))
        return cls(
            folder_id=os.getenv("YANDEX_CLOUD_FOLDER_ID") or os.getenv("YANDEX_FOLDER_ID") or None,
            api_key=os.getenv("YANDEX_VISION_API_KEY") or os.getenv("YANDEX_API_KEY") or None,
            iam_token=os.getenv("YANDEX_VISION_IAM_TOKEN") or None,
            endpoint=os.getenv("YANDEX_OCR_ENDPOINT") or "https://ai.api.cloud.yandex.net/ocr/v1",
        )

    def authorization_header(self) -> dict[str, str]:
        if bool(self.api_key) == bool(self.iam_token):
            raise VisionConfigurationError("Set exactly one of YANDEX_VISION_API_KEY or YANDEX_VISION_IAM_TOKEN")
        if self.api_key:
            return {"Authorization": f"Api-Key {self.api_key}"}
        return {"Authorization": f"Bearer {self.iam_token}"}


class YandexVisionClient:
    """HTTP wrapper for the documented synchronous ``recognizeText`` method."""

    def __init__(self, config: YandexVisionConfig, client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=60.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "YandexVisionClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def recognize(
        self,
        input_file: InputFile,
        *,
        language_codes: tuple[str, ...] = ("ru", "en"),
        model: str = "page",
    ) -> dict[str, Any]:
        payload = {
            "content": base64.b64encode(input_file.content).decode("ascii"),
            "mimeType": input_file.mime_type,
            "languageCodes": list(language_codes),
            "model": model,
        }
        endpoint = self._config.endpoint.rstrip("/")
        url = endpoint if endpoint.endswith("/recognizeText") else f"{endpoint}/recognizeText"
        response = self._client.post(
            url,
            headers={"Content-Type": "application/json", **self._config.authorization_header()},
            json=payload,
        )
        if response.is_error:
            raise VisionAPIError(f"Vision OCR returned HTTP {response.status_code}")
        body = response.json()
        if not isinstance(body, dict):
            raise VisionAPIError("Vision OCR returned a non-object JSON response")
        return body


@dataclass(frozen=True, slots=True)
class VisionResponseSummary:
    page_number: int | None
    block_count: int
    layout_types: tuple[str, ...]
    table_count: int
    table_cell_count: int
    has_markdown: bool
    has_text_confidence: bool
    picture_scores: tuple[float, ...]


def document_from_response(payload: Mapping[str, Any], *, model: str | None = None) -> DocumentModel:
    """Map documented fields into the provider-neutral model.

    Raw JSON remains in the fixture; this mapping retains semantic blocks,
    geometry, tables, spans, and Markdown needed by a later renderer.
    """
    payload = _recognition_payload(payload)
    annotation = payload.get("textAnnotation")
    if not isinstance(annotation, Mapping):
        raise ValueError("Response has no textAnnotation object")
    blocks = tuple(_block_from_json(block) for block in _objects(annotation.get("blocks")))
    tables = tuple(_table_from_json(table) for table in _objects(annotation.get("tables")))
    page = Page(
        number=_to_int(payload.get("page")) or 0,
        width=_to_int(annotation.get("width")),
        height=_to_int(annotation.get("height")),
        blocks=blocks,
        tables=tables,
        markdown=_string_or_none(annotation.get("markdown")),
    )
    return DocumentModel(pages=(page,), provider="yandex-vision-ocr", provider_model=model)


def summarize_response(payload: Mapping[str, Any]) -> VisionResponseSummary:
    payload = _recognition_payload(payload)
    annotation = payload.get("textAnnotation")
    if not isinstance(annotation, Mapping):
        raise ValueError("Response has no textAnnotation object")
    blocks = _objects(annotation.get("blocks"))
    tables = _objects(annotation.get("tables"))
    pictures = _objects(annotation.get("pictures"))
    scores = tuple(score for picture in pictures if (score := _to_float(picture.get("score"))) is not None)
    return VisionResponseSummary(
        page_number=_to_int(payload.get("page")),
        block_count=len(blocks),
        layout_types=tuple(str(block["layoutType"]) for block in blocks if block.get("layoutType")),
        table_count=len(tables),
        table_cell_count=sum(len(_objects(table.get("cells"))) for table in tables),
        has_markdown=bool(annotation.get("markdown")),
        # Official schema specifies picture.score, not word/line/block confidence.
        has_text_confidence=any("confidence" in item for item in blocks),
        picture_scores=scores,
    )


def _block_from_json(value: Mapping[str, Any]) -> TextBlock:
    lines = _objects(value.get("lines"))
    text = "\n".join(str(line.get("text", "")) for line in lines if line.get("text"))
    return TextBlock(text=text, bounding_box=_box_from_json(value.get("boundingBox")), layout_type=_string_or_none(value.get("layoutType")))


def _recognition_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept current root fields and the legacy ``result`` response wrapper.

    The raw response is always retained as captured; this only normalizes the
    mapping layer so both endpoint generations can be inspected safely.
    """
    result = payload.get("result")
    if isinstance(result, Mapping) and isinstance(result.get("textAnnotation"), Mapping):
        return result
    return payload


def _table_from_json(value: Mapping[str, Any]) -> Table:
    cells = tuple(
        TableCell(
            row_index=_to_int(cell.get("rowIndex")) or 0,
            column_index=_to_int(cell.get("columnIndex")) or 0,
            text=str(cell.get("text", "")),
            row_span=_to_int(cell.get("rowSpan")) or 1,
            column_span=_to_int(cell.get("columnSpan")) or 1,
            bounding_box=_box_from_json(cell.get("boundingBox")),
        )
        for cell in _objects(value.get("cells"))
    )
    return Table(
        row_count=_to_int(value.get("rowCount")) or 0,
        column_count=_to_int(value.get("columnCount")) or 0,
        cells=cells,
        bounding_box=_box_from_json(value.get("boundingBox")),
    )


def _box_from_json(value: object) -> BoundingBox | None:
    if not isinstance(value, Mapping):
        return None
    vertices = tuple(
        (x, y)
        for vertex in _objects(value.get("vertices"))
        if (x := _to_int(vertex.get("x"))) is not None and (y := _to_int(vertex.get("y"))) is not None
    )
    return BoundingBox(vertices) if vertices else None


def _objects(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _to_int(value: object) -> int | None:
    try:
        return int(str(value)) if value is not None else None
    except ValueError:
        return None


def _to_float(value: object) -> float | None:
    try:
        return float(str(value)) if value is not None else None
    except ValueError:
        return None


def _string_or_none(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None
