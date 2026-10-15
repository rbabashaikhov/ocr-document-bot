"""Checks for the isolated OCR-004D OpenCV research prototype."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from research.table_grid import detect_grid, detect_tables


def _block(x: int, y: int) -> dict[str, object]:
    return {"boundingBox": {"vertices": [{"x": x - 5, "y": y - 5}, {"x": x + 5, "y": y - 5}, {"x": x + 5, "y": y + 5}, {"x": x - 5, "y": y + 5}]}}


def _write(tmp_path: Path, image: np.ndarray, name: str = "sample.png") -> Path:
    path = tmp_path / name
    assert cv2.imwrite(str(path), image)
    return path


def _grid(image: np.ndarray, origin: tuple[int, int] = (10, 10), rows: int = 2, columns: int = 3, cell: tuple[int, int] = (80, 60)) -> None:
    x, y = origin
    cell_width, cell_height = cell
    for column in range(columns + 1):
        cv2.line(image, (x + column * cell_width, y), (x + column * cell_width, y + rows * cell_height), (0, 0, 0), 2)
    for row in range(rows + 1):
        cv2.line(image, (x, y + row * cell_height), (x + columns * cell_width, y + row * cell_height), (0, 0, 0), 2)


def test_detects_ruled_grid_and_a_horizontal_merge(tmp_path: Path) -> None:
    image = np.full((140, 260, 3), 255, dtype=np.uint8)
    _grid(image)
    cv2.line(image, (90, 10), (90, 70), (255, 255, 255), 4)
    payload = {"textAnnotation": {"blocks": [_block(50, 40), _block(130, 40), _block(50, 100), _block(130, 100), _block(210, 100)]}}

    result, _ = detect_grid(_write(tmp_path, image), payload)

    assert result is not None
    assert result.status == "detected"
    assert set(result.mapped_block_indexes) == {0, 1, 2, 3, 4}
    assert any(cell.row == 0 and cell.column == 0 and cell.column_span == 2 for cell in result.cells)


def test_corrects_small_skew_before_mapping_blocks(tmp_path: Path) -> None:
    image = np.full((180, 300, 3), 255, dtype=np.uint8)
    _grid(image, origin=(30, 30))
    matrix = cv2.getRotationMatrix2D((150, 90), 3, 1.0)
    skewed = cv2.warpAffine(image, matrix, (300, 180), borderValue=(255, 255, 255))
    centers = [matrix @ np.array([x, 60, 1.0]) for x in (70, 150, 230)]
    payload = {"textAnnotation": {"blocks": [_block(round(x), round(y)) for x, y in centers]}}

    analysis, _ = detect_tables(_write(tmp_path, skewed), payload)

    assert analysis.status == "detected"
    assert abs(analysis.deskew_degrees) >= 1
    assert len(analysis.tables) == 1
    assert set(analysis.tables[0].mapped_block_indexes) == {0, 1, 2}


def test_marks_broken_outer_rule_as_candidate_without_owning_text(tmp_path: Path) -> None:
    image = np.full((140, 260, 3), 255, dtype=np.uint8)
    _grid(image)
    cv2.line(image, (250, 30), (250, 110), (255, 255, 255), 4)

    analysis, _ = detect_tables(_write(tmp_path, image), {"textAnnotation": {"blocks": [_block(50, 40)]}})

    assert analysis.status == "candidate"
    assert len(analysis.tables) == 1
    assert analysis.tables[0].mapped_block_indexes == ()
    assert analysis.tables[0].unmapped_block_indexes == (0,)
    assert "outer_rule_incomplete" in analysis.tables[0].diagnostics.notes


def test_detects_two_separate_ruled_tables(tmp_path: Path) -> None:
    image = np.full((180, 620, 3), 255, dtype=np.uint8)
    _grid(image, origin=(10, 20))
    _grid(image, origin=(350, 20))

    analysis, _ = detect_tables(_write(tmp_path, image), {"textAnnotation": {"blocks": [_block(50, 50), _block(390, 50)]}})

    assert analysis.status == "detected"
    assert len(analysis.tables) == 2
    assert all(table.status == "detected" for table in analysis.tables)
    assert {index for table in analysis.tables for index in table.mapped_block_indexes} == {0, 1}


def test_does_not_call_multicolumn_text_or_noise_a_table(tmp_path: Path) -> None:
    image = np.full((300, 500, 3), 255, dtype=np.uint8)
    for y in range(40, 260, 35):
        cv2.putText(image, "left words", (25, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
        cv2.putText(image, "right words", (285, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    rng = np.random.default_rng(42)
    points = rng.integers([0, 0], [500, 300], size=(600, 2))
    image[points[:, 1], points[:, 0]] = 0

    analysis, _ = detect_tables(_write(tmp_path, image), {"textAnnotation": {"blocks": [_block(70, 50), _block(330, 50)]}})

    assert analysis.status == "not_detected"
    assert analysis.tables == ()


def test_does_not_call_plain_text_a_ruled_table(tmp_path: Path) -> None:
    image = np.full((200, 300, 3), 255, dtype=np.uint8)
    cv2.putText(image, "plain text", (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)

    result, _ = detect_grid(_write(tmp_path, image), {"textAnnotation": {"blocks": [_block(90, 95)]}})

    assert result is None
