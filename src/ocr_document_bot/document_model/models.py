"""Provider-neutral, serializable document representation for OCR recovery."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Point(BaseModel):
    model_config = ConfigDict(frozen=True)
    x: float
    y: float


class BoundingBox(BaseModel):
    model_config = ConfigDict(frozen=True)
    vertices: tuple[Point, ...] = Field(min_length=1)

    @property
    def left(self) -> float: return min(vertex.x for vertex in self.vertices)
    @property
    def right(self) -> float: return max(vertex.x for vertex in self.vertices)
    @property
    def top(self) -> float: return min(vertex.y for vertex in self.vertices)
    @property
    def bottom(self) -> float: return max(vertex.y for vertex in self.vertices)
    @property
    def width(self) -> float: return self.right - self.left


class OCRProvenance(BaseModel):
    provider: str
    source_page_number: int
    source_order: int
    source_type: str
    provider_model: str | None = None


class ElementBase(BaseModel):
    id: str
    geometry: BoundingBox | None = None
    provenance: OCRProvenance


class Paragraph(ElementBase):
    kind: Literal["paragraph"] = "paragraph"
    text: str


class Heading(ElementBase):
    kind: Literal["heading"] = "heading"
    text: str
    level: int = Field(ge=1, le=9)


class Picture(ElementBase):
    kind: Literal["picture"] = "picture"
    score: float | None = None


class TableCell(BaseModel):
    text: str
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    geometry: BoundingBox | None = None
    provenance: OCRProvenance


class TableRow(BaseModel):
    index: int = Field(ge=0)
    cells: list[TableCell] = Field(default_factory=list)


class Table(ElementBase):
    kind: Literal["table"] = "table"
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    rows: list[TableRow] = Field(default_factory=list)


class TableCandidate(ElementBase):
    """A non-destructive warning that geometry looks tabular but is ambiguous."""
    kind: Literal["table_candidate"] = "table_candidate"
    source_block_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    reason: str


PageElement = Annotated[Paragraph | Heading | Table | TableCandidate | Picture, Field(discriminator="kind")]


class Page(BaseModel):
    number: int
    width: float | None = Field(default=None, ge=0)
    height: float | None = Field(default=None, ge=0)
    elements: list[PageElement] = Field(default_factory=list)


class Document(BaseModel):
    pages: list[Page] = Field(default_factory=list)
    source_provider: str
    source_model: str | None = None
