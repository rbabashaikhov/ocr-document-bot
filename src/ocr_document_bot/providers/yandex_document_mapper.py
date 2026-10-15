"""Yandex-specific translation into the provider-neutral Document Model."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from ocr_document_bot.document_model import BoundingBox, Document, Heading, LayoutTableDetector, OCRProvenance, Page, Paragraph, Picture, Point, ReadingOrderResolver, Table, TableCell, TableRow


def document_from_yandex_responses(responses: Sequence[Mapping[str, Any]], *, model: str | None = None) -> Document:
    pages = [_page_from_response(response, model=model) for response in responses]
    return Document(pages=sorted(pages, key=lambda page: page.number), source_provider="yandex-vision-ocr", source_model=model)


def _page_from_response(raw: Mapping[str, Any], *, model: str | None) -> Page:
    response = _unwrap_response(raw)
    annotation = _mapping(response.get("textAnnotation"))
    page_number = _int(response.get("page"), 0)
    elements = []
    for index, block in enumerate(_mappings(annotation.get("blocks"))):
        provenance = _origin(page_number, index, "block", model)
        text = "\n".join(str(line.get("text", "")) for line in _mappings(block.get("lines")))
        layout = str(block.get("layoutType", ""))
        common = {"id": f"page-{page_number}-block-{index}", "geometry": _bbox(block.get("boundingBox")), "provenance": provenance}
        if layout == "LAYOUT_TYPE_TITLE":
            elements.append(Heading(**common, text=text, level=1))
        elif layout == "LAYOUT_TYPE_SECTION_HEADER":
            elements.append(Heading(**common, text=text, level=2))
        else:
            elements.append(Paragraph(**common, text=text))
    table_offset = len(elements)
    for table_index, table in enumerate(_mappings(annotation.get("tables"))):
        provenance = _origin(page_number, table_offset + table_index, "table", model)
        rows: defaultdict[int, list[TableCell]] = defaultdict(list)
        for cell_index, cell in enumerate(_mappings(table.get("cells"))):
            row_index = _int(cell.get("rowIndex"), 0)
            rows[row_index].append(TableCell(
                text=str(cell.get("text", "")), row_index=row_index, column_index=_int(cell.get("columnIndex"), 0),
                row_span=_int(cell.get("rowSpan"), 1), column_span=_int(cell.get("columnSpan"), 1),
                geometry=_bbox(cell.get("boundingBox")), provenance=_origin(page_number, cell_index, "table_cell", model),
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
    width = _float(annotation.get("width"))
    return Page(number=page_number, width=width, height=_float(annotation.get("height")), elements=ReadingOrderResolver().resolve(elements, page_width=width))


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
