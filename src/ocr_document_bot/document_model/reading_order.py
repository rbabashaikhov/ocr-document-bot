"""Coordinate-based resolver which is deterministic and never drops elements."""

from __future__ import annotations

from collections.abc import Iterable

from .models import PageElement


class ReadingOrderResolver:
    """Resolve wide separators, then columns, retaining every source element once."""

    def resolve(self, elements: Iterable[PageElement], page_width: float | None = None) -> list[PageElement]:
        values = list(elements)
        positioned = [item for item in values if item.geometry is not None]
        unknown = [item for item in values if item.geometry is None]
        if not positioned:
            return sorted(values, key=self._source_key)
        effective_width = page_width or (max(item.geometry.right for item in positioned) - min(item.geometry.left for item in positioned))
        spanners = [item for item in positioned if effective_width > 0 and item.geometry.width / effective_width >= 0.75]
        remaining = [item for item in positioned if item not in spanners]
        ordered: list[PageElement] = []
        for spanner in sorted(spanners, key=self._position_key):
            before = [item for item in remaining if item.geometry.top < spanner.geometry.top]
            ordered.extend(self._resolve_band(before))
            remaining = [item for item in remaining if item not in before]
            ordered.append(spanner)
        return ordered + self._resolve_band(remaining) + sorted(unknown, key=self._source_key)

    def _resolve_band(self, elements: list[PageElement]) -> list[PageElement]:
        columns: list[list[PageElement]] = []
        right_edges: list[float] = []
        for item in sorted(elements, key=lambda value: (value.geometry.left, value.geometry.top, self._source_key(value))):
            matching = next((index for index, edge in enumerate(right_edges) if item.geometry.left <= edge), None)
            if matching is None:
                columns.append([item]); right_edges.append(item.geometry.right)
            else:
                columns[matching].append(item); right_edges[matching] = max(right_edges[matching], item.geometry.right)
        return [item for column in columns for item in sorted(column, key=self._position_key)]

    @staticmethod
    def _source_key(item: PageElement) -> tuple[int, str]:
        return item.provenance.source_order, item.id

    def _position_key(self, item: PageElement) -> tuple[float, float, int, str]:
        return item.geometry.top, item.geometry.left, *self._source_key(item)
