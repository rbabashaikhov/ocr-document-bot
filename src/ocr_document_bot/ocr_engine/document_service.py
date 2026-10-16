"""Page-aware OCR orchestration shared by every transport adapter."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any, Protocol

from ocr_document_bot.document_model import BoundingBox, Document, OCRProvenance, Page, Paragraph, Point, ReadingOrderResolver, Table, TableCell, TableRow
from ocr_document_bot.domain import InputFile
from ocr_document_bot.preprocessing import InputPreprocessor, PreparedPage
from ocr_document_bot.providers.yandex_document_mapper import document_from_yandex_responses


class RawVisionClient(Protocol):
    def recognize(self, input_file: InputFile, *, language_codes: tuple[str, ...], model: str) -> dict[str, Any]: ...


class DocumentOCRService:
    """Use native PDF text where suitable and Vision only for rendered pages."""

    def __init__(
        self,
        vision: RawVisionClient,
        *,
        preprocessor: InputPreprocessor,
        language_codes: tuple[str, ...] = ("ru", "en"),
        model: str = "page",
    ) -> None:
        self._vision = vision
        self._preprocessor = preprocessor
        self._language_codes = language_codes
        self._model = model

    def process(self, input_file: InputFile) -> Document:
        pages = []
        for prepared in self._preprocessor.prepare_pages(input_file):
            pages.append(self._native_page(prepared) if prepared.native_text is not None else self._ocr_page(prepared))
        return Document(pages=pages, source_provider="yandex-vision-ocr", source_model=self._model)

    def _ocr_page(self, prepared: PreparedPage) -> Page:
        assert prepared.image is not None
        raw = self._vision.recognize(prepared.image, language_codes=self._language_codes, model=self._model)
        source_path = _temporary_image(prepared.image)
        try:
            mapped = document_from_yandex_responses([raw], model=self._model, source_images=[source_path])
        finally:
            source_path.unlink(missing_ok=True)
        return mapped.pages[0].model_copy(update={"number": prepared.page_number})

    def _native_page(self, prepared: PreparedPage) -> Page:
        assert prepared.native_text is not None
        elements = [
            Paragraph(
                id=f"page-{prepared.page_number}-pdf-text-{block.source_order}",
                text=block.text,
                geometry=_bbox(block.bbox),
                provenance=OCRProvenance(
                    provider="pdf-native-text",
                    source_page_number=prepared.page_number,
                    source_order=block.source_order,
                    source_type="pdf_text",
                ),
            )
            for block in prepared.native_blocks
        ]
        if not prepared.native_blocks and not prepared.native_tables:
            paragraphs = [item for item in prepared.native_text.split("\n\n") if item.strip()] or [prepared.native_text]
            elements = [
                Paragraph(
                    id=f"page-{prepared.page_number}-pdf-text-{index}",
                    text=text,
                    provenance=OCRProvenance(
                        provider="pdf-native-text",
                        source_page_number=prepared.page_number,
                        source_order=index,
                        source_type="pdf_text",
                    ),
                )
                for index, text in enumerate(paragraphs)
            ]
        for index, native_table in enumerate(prepared.native_tables):
            order = len(prepared.native_blocks) + index
            rows = [
                TableRow(
                    index=row_index,
                    cells=[
                        TableCell(
                            text=value,
                            row_index=row_index,
                            column_index=column_index,
                            provenance=OCRProvenance(
                                provider="pdf-native-text",
                                source_page_number=prepared.page_number,
                                source_order=order,
                                source_type="pdf_table_cell",
                            ),
                        )
                        for column_index, value in enumerate(row)
                    ],
                )
                for row_index, row in enumerate(native_table.rows)
            ]
            elements.append(Table(
                id=f"page-{prepared.page_number}-pdf-table-{index}",
                geometry=_bbox(native_table.bbox),
                provenance=OCRProvenance(
                    provider="pdf-native-text",
                    source_page_number=prepared.page_number,
                    source_order=order,
                    source_type="pdf_table",
                ),
                row_count=len(rows),
                column_count=max((len(row.cells) for row in rows), default=0),
                rows=rows,
            ))
        return Page(number=prepared.page_number, elements=ReadingOrderResolver().resolve(elements))


def _temporary_image(input_file: InputFile) -> Path:
    suffix = ".jpg" if input_file.mime_type == "image/jpeg" else ".png"
    with tempfile.NamedTemporaryFile(prefix="ocr-page-", suffix=suffix, delete=False) as handle:
        handle.write(input_file.content)
        return Path(handle.name)


def _bbox(value: tuple[float, float, float, float]) -> BoundingBox:
    return BoundingBox(vertices=(Point(x=value[0], y=value[1]), Point(x=value[2], y=value[3])))
