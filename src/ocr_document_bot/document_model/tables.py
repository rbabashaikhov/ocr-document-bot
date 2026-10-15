"""Conservative geometry-only table detection for pages without native tables."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import median

from .models import BoundingBox, OCRProvenance, Paragraph, Point, Table, TableCandidate, TableCell, TableRow


@dataclass(frozen=True)
class LayoutDetection:
    table: Table | None
    candidate: TableCandidate | None
    consumed_block_ids: frozenset[str] = frozenset()


class LayoutTableDetector:
    """Detect only dense regular grids; source blocks survive every uncertain case."""
    def detect(self, blocks: list[Paragraph]) -> LayoutDetection:
        blocks = [block for block in blocks if block.geometry is not None]
        if len(blocks) < 4: return LayoutDetection(None, None)
        rows, columns = self._clusters(blocks, "y"), self._clusters(blocks, "x")
        if len(rows) < 2 or len(columns) < 2: return LayoutDetection(None, None)
        grid: dict[tuple[int, int], list[Paragraph]] = defaultdict(list)
        for block in blocks: grid[(self._nearest(block.geometry.top, rows), self._nearest(block.geometry.left, columns))].append(block)
        density, duplicate = len(grid) / (len(rows) * len(columns)), any(len(cell) > 1 for cell in grid.values())
        provenance = OCRProvenance(provider=blocks[0].provenance.provider, source_page_number=blocks[0].provenance.source_page_number, source_order=min(block.provenance.source_order for block in blocks), source_type="layout_table", provider_model=blocks[0].provenance.provider_model)
        geometry, ids = self._union(blocks), [block.id for block in blocks]
        if len(rows) >= 3 and density >= 0.9 and not duplicate and self._regular(rows) and self._regular(columns):
            table_rows = [TableRow(index=row, cells=[TableCell(text=grid[(row, column)][0].text, row_index=row, column_index=column, geometry=grid[(row, column)][0].geometry, provenance=grid[(row, column)][0].provenance) for column in range(len(columns))]) for row in range(len(rows))]
            return LayoutDetection(Table(id=f"page-{provenance.source_page_number}-layout-table-{provenance.source_order}", geometry=geometry, provenance=provenance, row_count=len(rows), column_count=len(columns), rows=table_rows), None, frozenset(ids))
        if density >= 0.5:
            return LayoutDetection(None, TableCandidate(id=f"page-{provenance.source_page_number}-table-candidate-{provenance.source_order}", geometry=geometry, provenance=provenance, source_block_ids=ids, confidence=round(density, 2), reason="grid is incomplete, irregular, or contains ambiguous merged/overlapping cells"))
        return LayoutDetection(None, None)

    @staticmethod
    def _clusters(blocks: list[Paragraph], axis: str) -> list[float]:
        values = sorted(block.geometry.top if axis == "y" else block.geometry.left for block in blocks)
        dimensions = [max(1.0, block.geometry.bottom - block.geometry.top) if axis == "y" else max(1.0, block.geometry.width) for block in blocks]
        tolerance, clusters = median(dimensions) * 0.45, []
        for value in values:
            if not clusters or value - clusters[-1][-1] > tolerance: clusters.append([value])
            else: clusters[-1].append(value)
        return [sum(cluster) / len(cluster) for cluster in clusters]

    @staticmethod
    def _nearest(value: float, centers: list[float]) -> int: return min(range(len(centers)), key=lambda index: abs(value - centers[index]))
    @staticmethod
    def _regular(centers: list[float]) -> bool:
        gaps = [right - left for left, right in zip(centers, centers[1:])]
        return bool(gaps) and min(gaps) > 0 and max(gaps) / min(gaps) <= 1.6
    @staticmethod
    def _union(blocks: list[Paragraph]) -> BoundingBox:
        return BoundingBox(vertices=(Point(x=min(block.geometry.left for block in blocks), y=min(block.geometry.top for block in blocks)), Point(x=max(block.geometry.right for block in blocks), y=max(block.geometry.bottom for block in blocks))))
