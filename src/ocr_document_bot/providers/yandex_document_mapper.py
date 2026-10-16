"""Yandex-specific translation into the provider-neutral Document Model."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
import os
from pathlib import Path
from typing import Any

from ocr_document_bot.document_model import BoundingBox, Document, Heading, LayoutTableDetector, OCRProvenance, Page, Paragraph, Picture, Point, ReadingOrderResolver, Table, TableCell, TableRow, VisualTableDetector


def document_from_yandex_responses(
    responses: Sequence[Mapping[str, Any]], *, model: str | None = None,
    source_images: Sequence[Path | None] | None = None, enable_visual_table_detection: bool | None = None,
) -> Document:
    visual_enabled = _visual_detection_enabled() if enable_visual_table_detection is None else enable_visual_table_detection
    pages = [_page_from_response(response, model=model, image_path=source_images[index] if source_images and index < len(source_images) else None, visual_enabled=visual_enabled) for index, response in enumerate(responses)]
    return Document(pages=sorted(pages, key=lambda page: page.number), source_provider="yandex-vision-ocr", source_model=model)


def _page_from_response(raw: Mapping[str, Any], *, model: str | None, image_path: Path | None, visual_enabled: bool) -> Page:
    response = _unwrap_response(raw)
    annotation = _mapping(response.get("textAnnotation"))
    page_number = _int(response.get("page"), 0)
    width = _float(annotation.get("width"))
    elements = []
    source_blocks: dict[int, Paragraph | Heading] = {}
    for index, block in enumerate(_mappings(annotation.get("blocks"))):
        provenance = _origin(page_number, index, "block", model)
        text = "\n".join(str(line.get("text", "")) for line in _mappings(block.get("lines")))
        layout = str(block.get("layoutType", ""))
        common = {"id": f"page-{page_number}-block-{index}", "geometry": _bbox(block.get("boundingBox")), "provenance": provenance}
        if layout == "LAYOUT_TYPE_TITLE":
            element = Heading(**common, text=text, level=1)
        elif layout == "LAYOUT_TYPE_SECTION_HEADER":
            element = Heading(**common, text=text, level=2)
        else:
            element = Paragraph(**common, text=text)
        elements.append(element)
        source_blocks[index] = element
    table_offset = len(elements)
    for table_index, table in enumerate(_mappings(annotation.get("tables"))):
        provenance = _origin(page_number, table_offset + table_index, "table", model)
        rows: defaultdict[int, list[TableCell]] = defaultdict(list)
        for cell_index, cell in enumerate(_mappings(table.get("cells"))):
            row_index = _int(cell.get("rowIndex"), 0)
            cell_geometry = _bbox(cell.get("boundingBox"))
            rows[row_index].append(TableCell(
                text=_cell_text(cell.get("text"), cell_geometry, source_blocks), row_index=row_index, column_index=_int(cell.get("columnIndex"), 0),
                row_span=_int(cell.get("rowSpan"), 1), column_span=_int(cell.get("columnSpan"), 1),
                geometry=cell_geometry, provenance=_origin(page_number, cell_index, "table_cell", model),
            ))
        row_count = _int(table.get("rowCount"), 0)
        elements.append(Table(
            id=f"page-{page_number}-table-{table_index}", geometry=_bbox(table.get("boundingBox")), provenance=provenance,
            row_count=row_count, column_count=_int(table.get("columnCount"), 0),
            rows=[TableRow(index=index, cells=rows[index]) for index in range(row_count)],
        ))
    native_tables = [element for element in elements if isinstance(element, Table)]
    if native_tables:
        elements = [element for element in elements if not isinstance(element, (Paragraph, Heading)) or not any(_inside(element.geometry, table.geometry) for table in native_tables)]
    else:
        visual_tables, visual_consumed = _visual_tables(image_path, width, _float(annotation.get("height")), source_blocks, page_number, model) if visual_enabled and image_path else ([], set())
        if visual_tables:
            # The visual table is authoritative only here, so the geometric
            # block detector cannot create a second table.
            elements = [element for element in elements if element.id not in visual_consumed]
            elements.extend(visual_tables)
        else:
            detection = LayoutTableDetector().detect([element for element in elements if isinstance(element, Paragraph)])
            if detection.table:
                elements = [element for element in elements if element.id not in detection.consumed_block_ids]
                elements.append(detection.table)
            elif detection.candidate:
                elements.append(detection.candidate)
    picture_offset = len(elements)
    for index, picture in enumerate(_mappings(annotation.get("pictures"))):
        elements.append(Picture(
            id=f"page-{page_number}-picture-{index}", geometry=_bbox(picture.get("boundingBox")),
            provenance=_origin(page_number, picture_offset + index, "picture", model), score=_float(picture.get("score")),
        ))
    return Page(number=page_number, width=width, height=_float(annotation.get("height")), elements=ReadingOrderResolver().resolve(elements, page_width=width))


def _visual_tables(
    image_path: Path, width: float | None, height: float | None, source_blocks: Mapping[int, Paragraph | Heading], page_number: int, model: str | None,
) -> tuple[list[Table], set[str]]:
    """Convert only confirmed pixel grids; candidates deliberately own nothing."""
    if not image_path.is_file():
        return [], set()
    centers = [
        ((element.geometry.left + element.geometry.right) / 2, (element.geometry.top + element.geometry.bottom) / 2) if element.geometry else (-1.0, -1.0)
        for _, element in sorted(source_blocks.items())
    ]
    detection = VisualTableDetector().detect(image_path, centers, ocr_width=width, ocr_height=height)
    if detection.status != "detected":
        return [], set()
    scale_x = width / detection.image_width if width else 1.0
    scale_y = height / detection.image_height if height else 1.0
    tables: list[Table] = []
    consumed: set[str] = set()
    for table_index, visual in enumerate(table for table in detection.tables if table.status == "detected"):
        indexes = [index for index in visual.mapped_block_indexes if index in source_blocks]
        source_order = min((source_blocks[index].provenance.source_order for index in indexes), default=len(source_blocks) + table_index)
        provenance = _origin(page_number, source_order, "visual_table", model)
        rows: defaultdict[int, list[TableCell]] = defaultdict(list)
        for visual_cell in visual.cells:
            block_indexes = [index for index in visual_cell.block_indexes if index in source_blocks]
            text = "\n".join(source_blocks[index].text for index in block_indexes)
            consumed.update(source_blocks[index].id for index in block_indexes)
            cell_provenance = source_blocks[block_indexes[0]].provenance if block_indexes else provenance
            rows[visual_cell.row].append(TableCell(
                text=text, row_index=visual_cell.row, column_index=visual_cell.column,
                row_span=visual_cell.row_span, column_span=visual_cell.column_span,
                geometry=_visual_bbox(visual_cell.x1, visual_cell.y1, visual_cell.x2, visual_cell.y2, scale_x, scale_y), provenance=cell_provenance,
            ))
        tables.append(Table(
            id=f"page-{page_number}-visual-table-{table_index}",
            geometry=_visual_bbox(visual.vertical_lines[0], visual.horizontal_lines[0], visual.vertical_lines[-1], visual.horizontal_lines[-1], scale_x, scale_y),
            provenance=provenance, row_count=len(visual.horizontal_lines) - 1, column_count=len(visual.vertical_lines) - 1,
            rows=[TableRow(index=row, cells=rows[row]) for row in range(len(visual.horizontal_lines) - 1)],
        ))
    return tables, consumed


def _visual_bbox(x1: float, y1: float, x2: float, y2: float, scale_x: float, scale_y: float) -> BoundingBox:
    return BoundingBox(vertices=(Point(x=x1 * scale_x, y=y1 * scale_y), Point(x=x2 * scale_x, y=y2 * scale_y)))


def _visual_detection_enabled() -> bool:
    return os.getenv("OCR_ENABLE_VISUAL_TABLE_DETECTION", "false").strip().lower() in {"1", "true", "yes", "on"}


def _unwrap_response(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    result = raw.get("result")
    return result if isinstance(result, Mapping) else raw


def _origin(page: int, order: int, source_type: str, model: str | None) -> OCRProvenance:
    return OCRProvenance(provider="yandex-vision-ocr", source_page_number=page, source_order=order, source_type=source_type, provider_model=model)


def _bbox(value: object) -> BoundingBox | None:
    if not isinstance(value, Mapping): return None
    points = [Point(x=_float(vertex.get("x")) or 0, y=_float(vertex.get("y")) or 0) for vertex in _mappings(value.get("vertices"))]
    return BoundingBox(vertices=points) if points else None


def _inside(block: BoundingBox | None, container: BoundingBox | None) -> bool:
    if block is None or container is None:
        return False
    center_x = (block.left + block.right) / 2
    center_y = (block.top + block.bottom) / 2
    return container.left <= center_x <= container.right and container.top <= center_y <= container.bottom


def _cell_text(value: object, geometry: BoundingBox | None, blocks: Mapping[int, Paragraph | Heading]) -> str:
    """Fill only empty native cells from OCR blocks placed inside that cell."""
    text = str(value or "").strip()
    if text or geometry is None:
        return text
    for block in blocks.values():
        if _inside(block.geometry, geometry):
            text = _merge_text(text, block.text)
    return text


def _merge_text(existing: str, candidate: str) -> str:
    """Append non-duplicate OCR lines without inventing or normalising content."""
    result = existing
    normalized = _normalize_text(result)
    for line in candidate.splitlines():
        line = line.strip()
        line_normalized = _normalize_text(line)
        if line_normalized and line_normalized not in normalized:
            result = f"{result}\n{line}" if result else line
            normalized = _normalize_text(result)
    return result


def _normalize_text(value: str) -> str:
    return "".join(value.split()).casefold()


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int(value: object, default: int) -> int:
    try: return int(str(value))
    except (TypeError, ValueError): return default


def _float(value: object) -> float | None:
    try: return float(str(value)) if value is not None else None
    except (TypeError, ValueError): return None
