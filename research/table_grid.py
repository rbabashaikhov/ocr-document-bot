"""Experimental ruled-table recovery from pixels plus OCR block geometry.

This module deliberately lives outside the production package. Its quality
values are geometric diagnostics, not probabilities. Only a ``detected`` grid
may be considered by a future integration; a ``candidate`` maps no OCR blocks.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np

GridStatus = Literal["detected", "candidate", "not_detected"]


@dataclass(frozen=True)
class Cell:
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
class GridDiagnostics:
    outer_rule_coverage: float
    intersection_ratio: float
    consistent_cells: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class GridResult:
    horizontal_lines: tuple[int, ...]
    vertical_lines: tuple[int, ...]
    cells: tuple[Cell, ...]
    mapped_block_indexes: tuple[int, ...]
    unmapped_block_indexes: tuple[int, ...]
    status: GridStatus = "detected"
    diagnostics: GridDiagnostics | None = None


@dataclass(frozen=True)
class TableAnalysis:
    status: GridStatus
    tables: tuple[GridResult, ...]
    deskew_degrees: float


def detect_grid(image_path: Path, payload: dict[str, Any]) -> tuple[GridResult | None, np.ndarray]:
    """Backward-compatible helper returning the first confirmed grid."""
    analysis, overlay = detect_tables(image_path, payload)
    return next((table for table in analysis.tables if table.status == "detected"), None), overlay


def detect_tables(image_path: Path, payload: dict[str, Any]) -> tuple[TableAnalysis, np.ndarray]:
    """Find zero or more ruled grids without promoting weak evidence to a table."""
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot load image: {image_path}")
    deskew_degrees = _estimate_deskew(image)
    deskewed, matrix = _rotate(image, deskew_degrees)
    horizontal, vertical = _line_masks(_binary(deskewed))
    overlay = deskewed.copy()
    centers = [_transform_point(_center(block), matrix) for block in _blocks(payload)]
    tables = [table for box in _grid_components(horizontal, vertical) if (table := _detect_component(box, horizontal, vertical, centers))]
    for table in tables:
        _draw_table(overlay, table)
    mapped = {index for table in tables if table.status == "detected" for index in table.mapped_block_indexes}
    for index, point in enumerate(centers):
        if point[0] >= 0 and point[1] >= 0:
            cv2.circle(overlay, (round(point[0]), round(point[1])), 3, (0, 0, 255) if index in mapped else (0, 165, 255), -1)
    status: GridStatus = "detected" if any(table.status == "detected" for table in tables) else "candidate" if tables else "not_detected"
    return TableAnalysis(status, tuple(tables), deskew_degrees), overlay


def _binary(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]


def _line_masks(binary: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    height, width = binary.shape
    # Relative kernels avoid tuning for one specific document size.
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, width // 35), 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, height // 20))))
    return horizontal, vertical


def _estimate_deskew(image: np.ndarray) -> float:
    """Return a conservative correction for small scan skew, otherwise zero."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    minimum = max(30, min(image.shape[:2]) // 5)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50, minLineLength=minimum, maxLineGap=12)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        normalized = ((angle + 90) % 180) - 90
        if abs(normalized) <= 12:
            angles.append(normalized)
    if len(angles) < 2:
        return 0.0
    skew = float(np.median(angles))
    # OpenCV image coordinates grow downward, therefore the normalized Hough
    # slope has the opposite sign to the correction expected by warpAffine.
    return skew if abs(skew) <= 8 else 0.0


def _rotate(image: np.ndarray, degrees: float) -> tuple[np.ndarray, np.ndarray]:
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
    rotated = cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    return rotated, matrix


def _transform_point(point: tuple[float, float], matrix: np.ndarray) -> tuple[float, float]:
    if point[0] < 0 or point[1] < 0:
        return point
    return tuple(float(value) for value in matrix @ np.array([point[0], point[1], 1.0]))


def _grid_components(horizontal: np.ndarray, vertical: np.ndarray) -> list[tuple[int, int, int, int]]:
    count, _, stats, _ = cv2.connectedComponentsWithStats(cv2.bitwise_or(horizontal, vertical))
    components = []
    for x, y, width, height, area in stats[1:count]:
        if width >= 60 and height >= 40 and area >= 100:
            components.append((int(x), int(y), int(width), int(height)))
    return sorted(components, key=lambda item: (item[1], item[0]))


def _detect_component(box: tuple[int, int, int, int], horizontal: np.ndarray, vertical: np.ndarray, centers: list[tuple[float, float]]) -> GridResult | None:
    x, y, width, height = box
    h_mask, v_mask = horizontal[y : y + height, x : x + width], vertical[y : y + height, x : x + width]
    xs = [x + value for value in _line_positions(v_mask.sum(axis=0))]
    ys = [y + value for value in _line_positions(h_mask.sum(axis=1))]
    if len(xs) < 3 or len(ys) < 3:
        return None
    outer = _outer_coverage(xs, ys, horizontal, vertical)
    intersections = _intersection_ratio(xs, ys, horizontal, vertical)
    cells = _merged_cells(xs, ys, horizontal, vertical)
    consistent = _consistent_cells(cells, len(ys) - 1, len(xs) - 1)
    notes = tuple(note for condition, note in ((outer < 0.75, "outer_rule_incomplete"), (intersections < 0.70, "intersections_incomplete"), (not consistent, "merged_cells_inconsistent")) if condition)
    diagnostics = GridDiagnostics(round(outer, 3), round(intersections, 3), consistent, notes)
    status: GridStatus = "detected" if not notes else "candidate"
    # Weak projections alone are common in page furniture and glyphs. A
    # candidate still needs a mostly connected lattice; otherwise it is not a
    # table finding at all.
    if status == "candidate" and not (outer >= 0.25 and intersections >= 0.70 and consistent):
        return None
    if status == "detected":
        mapped_cells, mapped = [], set()
        for cell in cells:
            indexes = tuple(index for index, point in enumerate(centers) if _contains(cell, point))
            mapped.update(indexes)
            mapped_cells.append(Cell(**{**asdict(cell), "block_indexes": indexes}))
        return GridResult(tuple(ys), tuple(xs), tuple(mapped_cells), tuple(sorted(mapped)), tuple(index for index in range(len(centers)) if index not in mapped), status, diagnostics)
    # Candidate geometry owns no source text; a caller must retain all blocks.
    return GridResult(tuple(ys), tuple(xs), tuple(cells), (), tuple(range(len(centers))), status, diagnostics)


def _line_positions(projection: np.ndarray) -> list[int]:
    active = np.flatnonzero(projection >= projection.max() * 0.18) if projection.max() else np.array([], dtype=int)
    groups: list[list[int]] = []
    for value in active.tolist():
        if not groups or value > groups[-1][-1] + 1:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [round(sum(group) / len(group)) for group in groups]


def _merged_cells(xs: list[int], ys: list[int], horizontal: np.ndarray, vertical: np.ndarray) -> list[Cell]:
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
            identifier = row * columns + column
            if column + 1 < columns and _coverage(vertical, xs[column + 1], ys[row], ys[row + 1], vertical_axis=True) < 0.65:
                join(identifier, identifier + 1)
            if row + 1 < rows and _coverage(horizontal, ys[row + 1], xs[column], xs[column + 1], vertical_axis=False) < 0.65:
                join(identifier, identifier + columns)
    groups: dict[int, list[tuple[int, int]]] = {}
    for row in range(rows):
        for column in range(columns):
            value = row * columns + column
            groups.setdefault(root(value), []).append((row, column))
    cells: list[Cell] = []
    for group in groups.values():
        row_values, column_values = [value[0] for value in group], [value[1] for value in group]
        first_row, last_row = min(row_values), max(row_values)
        first_column, last_column = min(column_values), max(column_values)
        if len(group) != (last_row - first_row + 1) * (last_column - first_column + 1):
            cells.extend(Cell(row, column, 1, 1, xs[column], ys[row], xs[column + 1], ys[row + 1]) for row, column in group)
        else:
            cells.append(Cell(first_row, first_column, last_row - first_row + 1, last_column - first_column + 1, xs[first_column], ys[first_row], xs[last_column + 1], ys[last_row + 1]))
    return sorted(cells, key=lambda cell: (cell.row, cell.column))


def _coverage(mask: np.ndarray, fixed: int, start: int, end: int, *, vertical_axis: bool) -> float:
    values = mask[start : end + 1, max(0, fixed - 1) : fixed + 2] if vertical_axis else mask[max(0, fixed - 1) : fixed + 2, start : end + 1]
    if not values.size:
        return 0.0
    present = np.any(values > 0, axis=1 if vertical_axis else 0)
    return float(np.count_nonzero(present)) / present.size


def _outer_coverage(xs: list[int], ys: list[int], horizontal: np.ndarray, vertical: np.ndarray) -> float:
    return min(_coverage(vertical, xs[0], ys[0], ys[-1], vertical_axis=True), _coverage(vertical, xs[-1], ys[0], ys[-1], vertical_axis=True), _coverage(horizontal, ys[0], xs[0], xs[-1], vertical_axis=False), _coverage(horizontal, ys[-1], xs[0], xs[-1], vertical_axis=False))


def _intersection_ratio(xs: list[int], ys: list[int], horizontal: np.ndarray, vertical: np.ndarray) -> float:
    hits = 0
    for x in xs:
        for y in ys:
            h_window = horizontal[max(0, y - 2) : y + 3, max(0, x - 5) : x + 6]
            v_window = vertical[max(0, y - 5) : y + 6, max(0, x - 2) : x + 3]
            hits += bool(np.any(h_window) and np.any(v_window))
    return hits / (len(xs) * len(ys))


def _consistent_cells(cells: list[Cell], rows: int, columns: int) -> bool:
    covered: set[tuple[int, int]] = set()
    for cell in cells:
        for row in range(cell.row, cell.row + cell.row_span):
            for column in range(cell.column, cell.column + cell.column_span):
                if not (0 <= row < rows and 0 <= column < columns) or (row, column) in covered:
                    return False
                covered.add((row, column))
    return len(covered) == rows * columns


def _draw_table(overlay: np.ndarray, table: GridResult) -> None:
    color = (0, 160, 0) if table.status == "detected" else (0, 165, 255)
    for cell in table.cells:
        cv2.rectangle(overlay, (cell.x1, cell.y1), (cell.x2, cell.y2), color, 1)


def _blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = payload.get("result", payload)
    return root.get("textAnnotation", {}).get("blocks", [])


def _center(block: dict[str, Any]) -> tuple[float, float]:
    vertices = block.get("boundingBox", {}).get("vertices", [])
    if not vertices:
        return -1, -1
    return sum(float(vertex["x"]) for vertex in vertices) / len(vertices), sum(float(vertex["y"]) for vertex in vertices) / len(vertices)


def _contains(cell: Cell, point: tuple[float, float]) -> bool:
    return cell.x1 <= point[0] <= cell.x2 and cell.y1 <= point[1] <= cell.y2


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Experimental visual grid detection; not production code.")
    parser.add_argument("image", type=Path)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    analysis, overlay = detect_tables(args.image, json.loads(args.fixture.read_text(encoding="utf-8")))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output_dir / "grid-overlay.png"), overlay)
    (args.output_dir / "grid-analysis.json").write_text(json.dumps(asdict(analysis), ensure_ascii=False, indent=2), encoding="utf-8")
    print(analysis.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
