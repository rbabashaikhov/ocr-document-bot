"""Conservative ruled-table detection for the optional production path.

The detector returns geometric diagnostics, not a probability.  It never owns
OCR blocks unless all strict checks produce ``detected``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

import cv2
import numpy as np

VisualStatus = Literal["detected", "candidate", "not_detected"]


@dataclass(frozen=True)
class VisualCell:
    row: int
    column: int
    row_span: int
    column_span: int
    x1: int
    y1: int
    x2: int
    y2: int
    block_indexes: tuple[int, ...] = ()


@dataclass(frozen=True)
class VisualTable:
    horizontal_lines: tuple[int, ...]
    vertical_lines: tuple[int, ...]
    cells: tuple[VisualCell, ...]
    mapped_block_indexes: tuple[int, ...]
    status: VisualStatus
    outer_rule_coverage: float
    intersection_ratio: float


@dataclass(frozen=True)
class VisualTableDetection:
    status: VisualStatus
    tables: tuple[VisualTable, ...]
    deskew_degrees: float
    image_width: int
    image_height: int


class VisualTableDetector:
    """Detect tables with visible rules; ambiguous geometry is non-destructive."""

    def detect(
        self,
        image_path: Path,
        block_centers: Sequence[tuple[float, float]],
        *,
        ocr_width: float | None = None,
        ocr_height: float | None = None,
    ) -> VisualTableDetection:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Cannot load image: {image_path}")
        image_height, image_width = image.shape[:2]
        scale_x = image_width / ocr_width if ocr_width else 1.0
        scale_y = image_height / ocr_height if ocr_height else 1.0
        correction = _estimate_deskew(image)
        deskewed, matrix = _rotate(image, correction)
        horizontal, vertical = _line_masks(_binary(deskewed))
        centers = [_transform((point[0] * scale_x, point[1] * scale_y), matrix) for point in block_centers]
        tables = tuple(table for box in _components(horizontal, vertical) if (table := _table(box, horizontal, vertical, centers)))
        status: VisualStatus = "detected" if any(table.status == "detected" for table in tables) else "candidate" if tables else "not_detected"
        return VisualTableDetection(status, tables, correction, image_width, image_height)


def _binary(image: np.ndarray) -> np.ndarray:
    return cv2.threshold(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]


def _line_masks(binary: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    height, width = binary.shape
    return (
        cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, width // 35), 1))),
        cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, height // 20)))),
    )


def _estimate_deskew(image: np.ndarray) -> float:
    edges = cv2.Canny(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50, minLineLength=max(30, min(image.shape[:2]) // 5), maxLineGap=12)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = ((math.degrees(math.atan2(y2 - y1, x2 - x1)) + 90) % 180) - 90
        if abs(angle) <= 12:
            angles.append(angle)
    skew = float(np.median(angles)) if len(angles) >= 2 else 0.0
    return skew if abs(skew) <= 8 else 0.0


def _rotate(image: np.ndarray, degrees: float) -> tuple[np.ndarray, np.ndarray]:
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
    return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255)), matrix


def _transform(point: tuple[float, float], matrix: np.ndarray) -> tuple[float, float]:
    if point[0] < 0 or point[1] < 0:
        return point
    return tuple(float(value) for value in matrix @ np.array([point[0], point[1], 1.0]))


def _components(horizontal: np.ndarray, vertical: np.ndarray) -> list[tuple[int, int, int, int]]:
    count, _, stats, _ = cv2.connectedComponentsWithStats(cv2.bitwise_or(horizontal, vertical))
    return sorted([(int(x), int(y), int(width), int(height)) for x, y, width, height, area in stats[1:count] if width >= 60 and height >= 40 and area >= 100], key=lambda value: (value[1], value[0]))


def _table(box: tuple[int, int, int, int], horizontal: np.ndarray, vertical: np.ndarray, centers: Sequence[tuple[float, float]]) -> VisualTable | None:
    x, y, width, height = box
    xs = [x + value for value in _positions(vertical[y : y + height, x : x + width].sum(axis=0))]
    ys = [y + value for value in _positions(horizontal[y : y + height, x : x + width].sum(axis=1))]
    if len(xs) < 3 or len(ys) < 3:
        return None
    outer, intersections = _outer(xs, ys, horizontal, vertical), _intersections(xs, ys, horizontal, vertical)
    cells = _merge(xs, ys, horizontal, vertical)
    consistent = _consistent(cells, len(ys) - 1, len(xs) - 1)
    status: VisualStatus = "detected" if outer >= 0.75 and intersections >= 0.70 and consistent else "candidate"
    if status == "candidate" and not (outer >= 0.25 and intersections >= 0.70 and consistent):
        return None
    if status == "candidate":
        return VisualTable(tuple(ys), tuple(xs), tuple(cells), (), status, outer, intersections)
    mapped, rendered = set(), []
    for cell in cells:
        indexes = tuple(index for index, point in enumerate(centers) if cell.x1 <= point[0] <= cell.x2 and cell.y1 <= point[1] <= cell.y2)
        mapped.update(indexes)
        rendered.append(VisualCell(**{**cell.__dict__, "block_indexes": indexes}))
    return VisualTable(tuple(ys), tuple(xs), tuple(rendered), tuple(sorted(mapped)), status, outer, intersections)


def _positions(projection: np.ndarray) -> list[int]:
    active = np.flatnonzero(projection >= projection.max() * 0.18) if projection.max() else np.array([], dtype=int)
    groups: list[list[int]] = []
    for value in active.tolist():
        if not groups or value > groups[-1][-1] + 1:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [round(sum(group) / len(group)) for group in groups]


def _coverage(mask: np.ndarray, fixed: int, start: int, end: int, vertical_axis: bool) -> float:
    values = mask[start : end + 1, max(0, fixed - 1) : fixed + 2] if vertical_axis else mask[max(0, fixed - 1) : fixed + 2, start : end + 1]
    if not values.size:
        return 0.0
    present = np.any(values > 0, axis=1 if vertical_axis else 0)
    return float(np.count_nonzero(present)) / present.size


def _outer(xs: list[int], ys: list[int], horizontal: np.ndarray, vertical: np.ndarray) -> float:
    return min(_coverage(vertical, xs[0], ys[0], ys[-1], True), _coverage(vertical, xs[-1], ys[0], ys[-1], True), _coverage(horizontal, ys[0], xs[0], xs[-1], False), _coverage(horizontal, ys[-1], xs[0], xs[-1], False))


def _intersections(xs: list[int], ys: list[int], horizontal: np.ndarray, vertical: np.ndarray) -> float:
    hits = 0
    for x in xs:
        for y in ys:
            hits += bool(np.any(horizontal[max(0, y - 2) : y + 3, max(0, x - 5) : x + 6]) and np.any(vertical[max(0, y - 5) : y + 6, max(0, x - 2) : x + 3]))
    return hits / (len(xs) * len(ys))


def _merge(xs: list[int], ys: list[int], horizontal: np.ndarray, vertical: np.ndarray) -> list[VisualCell]:
    rows, columns = len(ys) - 1, len(xs) - 1
    parent = list(range(rows * columns))
    def root(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value
    def join(first: int, second: int) -> None:
        first, second = root(first), root(second)
        if first != second:
            parent[second] = first
    for row in range(rows):
        for column in range(columns):
            item = row * columns + column
            if column + 1 < columns and _coverage(vertical, xs[column + 1], ys[row], ys[row + 1], True) < 0.65:
                join(item, item + 1)
            if row + 1 < rows and _coverage(horizontal, ys[row + 1], xs[column], xs[column + 1], False) < 0.65:
                join(item, item + columns)
    groups: dict[int, list[tuple[int, int]]] = {}
    for row in range(rows):
        for column in range(columns):
            groups.setdefault(root(row * columns + column), []).append((row, column))
    cells: list[VisualCell] = []
    for group in groups.values():
        min_row, max_row = min(row for row, _ in group), max(row for row, _ in group)
        min_col, max_col = min(column for _, column in group), max(column for _, column in group)
        if len(group) == (max_row - min_row + 1) * (max_col - min_col + 1):
            cells.append(VisualCell(min_row, min_col, max_row - min_row + 1, max_col - min_col + 1, xs[min_col], ys[min_row], xs[max_col + 1], ys[max_row + 1]))
        else:
            cells.extend(VisualCell(row, column, 1, 1, xs[column], ys[row], xs[column + 1], ys[row + 1]) for row, column in group)
    return sorted(cells, key=lambda item: (item.row, item.column))


def _consistent(cells: Sequence[VisualCell], rows: int, columns: int) -> bool:
    covered: set[tuple[int, int]] = set()
    for cell in cells:
        for row in range(cell.row, cell.row + cell.row_span):
            for column in range(cell.column, cell.column + cell.column_span):
                if not (0 <= row < rows and 0 <= column < columns) or (row, column) in covered:
                    return False
                covered.add((row, column))
    return len(covered) == rows * columns
