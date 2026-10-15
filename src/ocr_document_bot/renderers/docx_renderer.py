"""Render the provider-neutral Document Model into an editable DOCX file."""

from __future__ import annotations

from pathlib import Path

from docx import Document as WordDocument
from docx.enum.section import WD_SECTION
from docx.shared import Cm, Pt

from ocr_document_bot.document_model import Document, Heading, Paragraph, Picture, Table, TableCandidate, TableCell


class DocxRenderer:
    """Semantic renderer: it does not inspect provider payloads or geometry."""

    def render(self, document: Document) -> WordDocument:
        word = WordDocument()
        self._configure(word)
        for page_index, page in enumerate(document.pages):
            if page_index:
                word.add_page_break()
            for element in page.elements:
                if isinstance(element, Heading):
                    paragraph = word.add_heading(level=element.level)
                    self._write_text(paragraph, element.text)
                elif isinstance(element, Paragraph):
                    paragraph = word.add_paragraph()
                    self._write_text(paragraph, element.text)
                elif isinstance(element, Table):
                    self._write_table(word, element)
                elif isinstance(element, (Picture, TableCandidate)):
                    # Picture bytes are unavailable and candidates deliberately retain source paragraphs.
                    continue
        return word

    def save(self, document: Document, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        self.render(document).save(output)
        return output

    @staticmethod
    def _configure(word: WordDocument) -> None:
        section = word.sections[0]
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.top_margin = section.bottom_margin = Cm(2)
        section.left_margin = section.right_margin = Cm(2)
        normal = word.styles["Normal"]
        normal.font.name = "Arial"
        normal.font.size = Pt(11)

    def _write_table(self, word: WordDocument, table: Table) -> None:
        word_table = word.add_table(rows=table.row_count, cols=table.column_count)
        word_table.style = "Table Grid"
        occupied: set[tuple[int, int]] = set()
        for row in table.rows:
            for cell in sorted(row.cells, key=lambda value: value.column_index):
                self._validate_cell(table, cell, occupied)
                start = word_table.cell(cell.row_index, cell.column_index)
                end = word_table.cell(cell.row_index + cell.row_span - 1, cell.column_index + cell.column_span - 1)
                target = start.merge(end) if cell.row_span > 1 or cell.column_span > 1 else start
                self._write_cell(target, cell.text)
                occupied.update((row_index, column_index) for row_index in range(cell.row_index, cell.row_index + cell.row_span) for column_index in range(cell.column_index, cell.column_index + cell.column_span))

    @staticmethod
    def _validate_cell(table: Table, cell: TableCell, occupied: set[tuple[int, int]]) -> None:
        coordinates = {(row, column) for row in range(cell.row_index, cell.row_index + cell.row_span) for column in range(cell.column_index, cell.column_index + cell.column_span)}
        if cell.row_index + cell.row_span > table.row_count or cell.column_index + cell.column_span > table.column_count:
            raise ValueError(f"Cell ({cell.row_index}, {cell.column_index}) exceeds table bounds")
        if coordinates & occupied:
            raise ValueError(f"Cell ({cell.row_index}, {cell.column_index}) overlaps a previous span")

    def _write_cell(self, cell, text: str) -> None:
        paragraph = cell.paragraphs[0]
        paragraph.clear()
        self._write_text(paragraph, text)

    @staticmethod
    def _write_text(paragraph, text: str) -> None:
        lines = text.split("\n")
        for index, line in enumerate(lines):
            if index:
                paragraph.add_run().add_break()
            paragraph.add_run(line)
