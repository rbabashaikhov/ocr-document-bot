"""Normalize transport files into page inputs safe for the synchronous OCR API."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import fitz
from PIL import Image, ImageSequence, UnidentifiedImageError

from ocr_document_bot.domain import InputFile


class UnsupportedInputError(ValueError):
    """Input is corrupted, unsupported, encrypted, or exceeds local limits."""


@dataclass(frozen=True)
class NativeTextBlock:
    """A text-layer block outside a native PDF table."""

    text: str
    bbox: tuple[float, float, float, float]
    source_order: int


@dataclass(frozen=True)
class NativeTable:
    """A table extracted by PyMuPDF from a text-layer PDF page."""

    rows: tuple[tuple[str, ...], ...]
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class PreparedPage:
    page_number: int
    image: InputFile | None = None
    native_text: str | None = None
    native_blocks: tuple[NativeTextBlock, ...] = ()
    native_tables: tuple[NativeTable, ...] = ()

    def __post_init__(self) -> None:
        if (self.image is None) == (self.native_text is None):
            raise ValueError("PreparedPage requires exactly one of image or native_text")


class InputPreprocessor:
    """Convert every non-native provider format to one JPEG/PNG page at a time."""

    IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/bmp", "image/tiff"})
    PDF_MIME_TYPE = "application/pdf"
    SUPPORTED_MIME_TYPES = IMAGE_MIME_TYPES | {PDF_MIME_TYPE}

    def __init__(self, max_file_size_bytes: int = 10 * 1024 * 1024, *, max_pages: int = 20, max_job_size_bytes: int = 25 * 1024 * 1024, pdf_render_dpi: int = 150, max_rendered_pixels: int = 16_000_000, pdf_text_min_chars: int = 20) -> None:
        self.max_file_size_bytes = max_file_size_bytes
        self.max_pages = max_pages
        self.max_job_size_bytes = max_job_size_bytes
        self.pdf_render_dpi = pdf_render_dpi
        self.max_rendered_pixels = max_rendered_pixels
        self.pdf_text_min_chars = pdf_text_min_chars

    def prepare(self, input_file: InputFile) -> InputFile:
        """Backward-compatible single-image API used by the original engine."""
        pages = self.prepare_pages(input_file)
        if len(pages) != 1 or pages[0].image is None:
            raise UnsupportedInputError("This input requires page-aware processing")
        return pages[0].image

    def prepare_pages(self, input_file: InputFile) -> list[PreparedPage]:
        self._validate_input(input_file)
        return self._prepare_pdf(input_file) if input_file.mime_type == self.PDF_MIME_TYPE else self._prepare_image(input_file)

    def _validate_input(self, input_file: InputFile) -> None:
        if input_file.mime_type not in self.SUPPORTED_MIME_TYPES:
            raise UnsupportedInputError("Unsupported file type")
        if not input_file.content:
            raise UnsupportedInputError("Input file is empty")
        if len(input_file.content) > self.max_file_size_bytes:
            raise UnsupportedInputError("Input file exceeds configured size limit")

    def _prepare_image(self, input_file: InputFile) -> list[PreparedPage]:
        try:
            with Image.open(BytesIO(input_file.content)) as opened:
                self._check_page_count(getattr(opened, "n_frames", 1))
                pages = [self._image_page(frame.copy(), input_file, index) for index, frame in enumerate(ImageSequence.Iterator(opened))]
        except (UnidentifiedImageError, OSError) as error:
            raise UnsupportedInputError("Image is damaged or cannot be decoded") from error
        self._check_total_size(pages)
        return pages

    def _image_page(self, image: Image.Image, source: InputFile, page_number: int) -> PreparedPage:
        if source.mime_type in {"image/jpeg", "image/png"} and page_number == 0:
            return PreparedPage(page_number, image=source)
        return PreparedPage(page_number, image=InputFile(f"{Path(source.filename).stem}-page-{page_number + 1}.jpg", "image/jpeg", _encode_jpeg(image), source.source))

    def _prepare_pdf(self, input_file: InputFile) -> list[PreparedPage]:
        try:
            document = fitz.open(stream=input_file.content, filetype="pdf")
        except (fitz.FileDataError, RuntimeError) as error:
            raise UnsupportedInputError("PDF is damaged or cannot be opened") from error
        try:
            if document.needs_pass:
                raise UnsupportedInputError("PDF is encrypted and cannot be processed")
            self._check_page_count(document.page_count)
            pages: list[PreparedPage] = []
            for page_number, page in enumerate(document):
                text = page.get_text("text").strip()
                native_tables = _native_tables(page)
                if _usable_text(text, self.pdf_text_min_chars) or native_tables:
                    pages.append(PreparedPage(
                        page_number,
                        native_text=text,
                        native_blocks=_native_blocks(page, native_tables),
                        native_tables=native_tables,
                    ))
                else:
                    pages.append(PreparedPage(page_number, image=self._pdf_page_image(page, input_file, page_number)))
            self._check_total_size(pages)
            return pages
        finally:
            document.close()

    def _pdf_page_image(self, page: fitz.Page, source: InputFile, page_number: int) -> InputFile:
        scale = self.pdf_render_dpi / 72
        pixels = page.rect.width * scale * page.rect.height * scale
        if pixels > self.max_rendered_pixels:
            scale *= (self.max_rendered_pixels / pixels) ** 0.5
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return InputFile(f"{Path(source.filename).stem}-page-{page_number + 1}.jpg", "image/jpeg", pixmap.tobytes("jpeg"), source.source)

    def _check_page_count(self, count: int) -> None:
        if count < 1:
            raise UnsupportedInputError("Document has no pages")
        if count > self.max_pages:
            raise UnsupportedInputError("Document exceeds configured page limit")

    def _check_total_size(self, pages: list[PreparedPage]) -> None:
        if sum(len(page.image.content) for page in pages if page.image is not None) > self.max_job_size_bytes:
            raise UnsupportedInputError("Prepared document exceeds configured job size limit")


def _encode_jpeg(image: Image.Image) -> bytes:
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        background = Image.new("RGB", image.size, "white")
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    output = BytesIO()
    image.save(output, format="JPEG", quality=90, optimize=True)
    return output.getvalue()


def _usable_text(text: str, minimum_chars: int) -> bool:
    compact = "".join(text.split())
    return len(compact) >= minimum_chars and sum(character.isalnum() for character in compact) >= minimum_chars


def _native_tables(page: fitz.Page) -> tuple[NativeTable, ...]:
    """Extract only PyMuPDF-confirmed tables; never infer one from plain text."""
    result = page.find_tables()
    tables = []
    for table in result.tables:
        extracted = table.extract()
        column_count = max((len(row) for row in extracted), default=0)
        rows = tuple(
            tuple("" if column >= len(row) or row[column] is None else str(row[column]) for column in range(column_count))
            for row in extracted
        )
        if rows and column_count:
            tables.append(NativeTable(rows=rows, bbox=tuple(float(value) for value in table.bbox)))
    return tuple(tables)


def _native_blocks(page: fitz.Page, tables: Iterable[NativeTable]) -> tuple[NativeTextBlock, ...]:
    table_boxes = tuple(table.bbox for table in tables)
    blocks = []
    for order, block in enumerate(page.get_text("blocks")):
        x0, y0, x1, y1, text, _, block_type = block
        if block_type != 0 or not text.strip():
            continue
        bbox = (float(x0), float(y0), float(x1), float(y1))
        if any(_center_inside(bbox, table_box) for table_box in table_boxes):
            continue
        blocks.append(NativeTextBlock(text=text.strip(), bbox=bbox, source_order=order))
    return tuple(blocks)


def _center_inside(inner: tuple[float, float, float, float], outer: tuple[float, float, float, float]) -> bool:
    center_x, center_y = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= center_x <= outer[2] and outer[1] <= center_y <= outer[3]
