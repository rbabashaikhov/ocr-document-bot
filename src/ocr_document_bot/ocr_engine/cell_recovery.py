"""Opt-in second OCR pass for visibly non-empty cells in confirmed visual tables."""

from __future__ import annotations

from collections.abc import Mapping
from io import BytesIO
import os
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageOps

from ocr_document_bot.document_model import OCRProvenance, Page, Table, TableCell, TableRow
from ocr_document_bot.domain import InputFile


class RawVisionClient(Protocol):
    def recognize(self, input_file: InputFile, *, language_codes: tuple[str, ...], model: str) -> dict[str, Any]: ...


class CellRecoveryService:
    """Recover only provider-returned text; failures leave the first pass intact."""

    def __init__(self, *, enabled: bool = False, max_requests: int = 6) -> None:
        if max_requests < 1:
            raise ValueError("OCR_MAX_CELL_RECOVERY_REQUESTS must be positive")
        self.enabled = enabled
        self.max_requests = max_requests

    @classmethod
    def from_environment(cls) -> "CellRecoveryService":
        enabled = os.getenv("OCR_ENABLE_CELL_RECOVERY", "false").strip().lower() in {"1", "true", "yes", "on"}
        try:
            maximum = int(os.getenv("OCR_MAX_CELL_RECOVERY_REQUESTS", "6"))
        except ValueError as error:
            raise ValueError("OCR_MAX_CELL_RECOVERY_REQUESTS must be an integer") from error
        return cls(enabled=enabled, max_requests=maximum)

    def recover(
        self,
        page: Page,
        *,
        image_path: Path,
        vision: RawVisionClient,
        language_codes: tuple[str, ...],
        model: str,
    ) -> Page:
        if not self.enabled or page.width is None or page.height is None:
            return page
        try:
            with Image.open(image_path) as source:
                image = source.convert("RGB")
        except OSError:
            return page

        recovered: dict[tuple[int, int, int], str] = {}
        attempted = 0
        for element_index, element in enumerate(page.elements):
            if not isinstance(element, Table) or element.provenance.source_type != "visual_table":
                continue
            for row_index, row in enumerate(element.rows):
                for cell_index, cell in enumerate(row.cells):
                    if attempted >= self.max_requests:
                        return _with_recovered_cells(page, recovered, model)
                    crop = _cell_crop(image, page, cell)
                    if cell.text.strip() or crop is None or not _has_ink(crop):
                        continue
                    attempted += 1
                    try:
                        payload = vision.recognize(_crop_input(crop, cell), language_codes=language_codes, model=model)
                        text = _provider_text(payload)
                    except Exception:
                        # A failed second pass must never discard the first pass.
                        continue
                    if text:
                        recovered[(element_index, row_index, cell_index)] = text
        return _with_recovered_cells(page, recovered, model)


def _with_recovered_cells(page: Page, recovered: Mapping[tuple[int, int, int], str], model: str) -> Page:
    if not recovered:
        return page
    elements = []
    for element_index, element in enumerate(page.elements):
        if not isinstance(element, Table):
            elements.append(element)
            continue
        rows = []
        for row_index, row in enumerate(element.rows):
            cells = []
            for cell_index, cell in enumerate(row.cells):
                text = recovered.get((element_index, row_index, cell_index))
                if text is None:
                    cells.append(cell)
                    continue
                cells.append(cell.model_copy(update={
                    "text": text,
                    "provenance": OCRProvenance(
                        provider="yandex-vision-ocr",
                        source_page_number=cell.provenance.source_page_number,
                        source_order=cell.provenance.source_order,
                        source_type="visual_table_cell_recovery",
                        provider_model=f"{model}:cell-recovery",
                    ),
                }))
            rows.append(TableRow(index=row.index, cells=cells))
        elements.append(element.model_copy(update={"rows": rows}))
    return page.model_copy(update={"elements": elements})


def _cell_crop(image: Image.Image, page: Page, cell: TableCell) -> Image.Image | None:
    if cell.geometry is None or page.width is None or page.height is None:
        return None
    scale_x, scale_y = image.width / page.width, image.height / page.height
    left, top = round(cell.geometry.left * scale_x), round(cell.geometry.top * scale_y)
    right, bottom = round(cell.geometry.right * scale_x), round(cell.geometry.bottom * scale_y)
    inset = max(2, round(min(right - left, bottom - top) * 0.08))
    left, top, right, bottom = left + inset, top + inset, right - inset, bottom - inset
    if right <= left or bottom <= top:
        return None
    return image.crop((left, top, right, bottom))


def _has_ink(crop: Image.Image) -> bool:
    """Ignore grid rules by testing only the already-inset cell interior."""
    grayscale = ImageOps.grayscale(crop)
    dark_pixels = sum(pixel < 200 for pixel in grayscale.getdata())
    return dark_pixels >= 8


def _crop_input(crop: Image.Image, cell: TableCell) -> InputFile:
    width, height = crop.size
    enlarged = crop.resize((max(1, width * 3), max(1, height * 3)), Image.Resampling.LANCZOS)
    output = BytesIO()
    enlarged.save(output, format="JPEG", quality=95)
    return InputFile(
        filename=f"cell-{cell.row_index}-{cell.column_index}.jpg",
        mime_type="image/jpeg",
        content=output.getvalue(),
        source="api",
    )


def _provider_text(payload: Mapping[str, Any]) -> str:
    response = _mapping(payload.get("result")) or payload
    annotation = _mapping(response.get("textAnnotation"))
    lines = [
        str(line.get("text", "")).strip()
        for block in _mappings(annotation.get("blocks"))
        for line in _mappings(block.get("lines"))
        if str(line.get("text", "")).strip()
    ]
    if lines:
        return "\n".join(lines)
    cells = [
        str(cell.get("text", "")).strip()
        for table in _mappings(annotation.get("tables"))
        for cell in _mappings(table.get("cells"))
        if str(cell.get("text", "")).strip()
    ]
    if cells:
        return "\n".join(cells)
    for value in (annotation.get("fullText"), response.get("fullText"), annotation.get("markdown")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
