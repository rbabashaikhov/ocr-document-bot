"""Provider-neutral models. Keep geometry and table semantics until rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4


class JobStatus(str, Enum):
    RECEIVED = "received"
    PREPROCESSING = "preprocessing"
    RECOGNIZING = "recognizing"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class OCRJobError(RuntimeError):
    """Raised for an invalid job-state transition."""


@dataclass(frozen=True, slots=True)
class InputFile:
    filename: str
    mime_type: str
    content: bytes
    source: Literal["telegram", "email", "api"]


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Polygon vertices in source-page pixel coordinates."""
    vertices: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str
    bounding_box: BoundingBox | None = None
    layout_type: str | None = None


@dataclass(frozen=True, slots=True)
class TableCell:
    row_index: int
    column_index: int
    text: str
    row_span: int = 1
    column_span: int = 1
    bounding_box: BoundingBox | None = None


@dataclass(frozen=True, slots=True)
class Table:
    row_count: int
    column_count: int
    cells: tuple[TableCell, ...]
    bounding_box: BoundingBox | None = None


@dataclass(frozen=True, slots=True)
class Page:
    number: int
    width: int | None = None
    height: int | None = None
    blocks: tuple[TextBlock, ...] = ()
    tables: tuple[Table, ...] = ()
    markdown: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentModel:
    pages: tuple[Page, ...]
    provider: str
    provider_model: str | None = None


@dataclass(slots=True)
class OCRJob:
    input_file: InputFile
    id: UUID = field(default_factory=uuid4)
    status: JobStatus = JobStatus.RECEIVED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    document: DocumentModel | None = None
    error_code: str | None = None
    error_message: str | None = None

    _TRANSITIONS = {
        JobStatus.RECEIVED: {JobStatus.PREPROCESSING, JobStatus.FAILED},
        JobStatus.PREPROCESSING: {JobStatus.RECOGNIZING, JobStatus.FAILED},
        JobStatus.RECOGNIZING: {JobStatus.RENDERING, JobStatus.FAILED},
        JobStatus.RENDERING: {JobStatus.COMPLETED, JobStatus.FAILED},
        JobStatus.COMPLETED: set(),
        JobStatus.FAILED: set(),
    }

    def transition_to(self, target: JobStatus) -> None:
        if target not in self._TRANSITIONS[self.status]:
            raise OCRJobError(f"Cannot transition {self.status} -> {target}")
        self.status = target
        self.updated_at = datetime.now(timezone.utc)

    def fail(self, code: str, message: str) -> None:
        if self.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            raise OCRJobError(f"Cannot fail terminal job in state {self.status}")
        self.error_code, self.error_message = code, message
        self.transition_to(JobStatus.FAILED)
