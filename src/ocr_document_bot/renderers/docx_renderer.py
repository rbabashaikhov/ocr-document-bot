"""Render the provider-neutral Document Model into an editable DOCX file."""

from __future__ import annotations

from pathlib import Path
from statistics import median

from docx import Document as WordDocument
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt

from ocr_document_bot.document_model import Document, Heading, Paragraph, Picture, Table, TableCandidate, TableCell


class DocxRenderer:
    """Semantic renderer: it does not inspect provider payloads or geometry."""

    def render(self, document: Document) -> WordDocument:
        word = WordDocument()
        self._configure(word, landscape=any(self._needs_landscape(element) for page in document.pages for element in page.elements if isinstance(element, Table)))
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
    def _configure(word: WordDocument, *, landscape: bool) -> None:
        section = word.sections[0]
        if landscape:
            section.orientation = WD_ORIENT.LANDSCAPE
            section.page_width, section.page_height = Cm(29.7), Cm(21)
            section.top_margin = section.bottom_margin = Cm(1.2)
            section.left_margin = section.right_margin = Cm(1.0)
        else:
            section.page_width, section.page_height = Cm(21), Cm(29.7)
            section.top_margin = section.bottom_margin = Cm(2)
            section.left_margin = section.right_margin = Cm(2)
        normal = word.styles["Normal"]
        normal.font.name = "Arial"
        normal.font.size = Pt(11)

    def _write_table(self, word: WordDocument, table: Table) -> None:
        word_table = word.add_table(rows=table.row_count, cols=table.column_count)
        word_table.style = "Table Grid"
        word_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        word_table.autofit = False
        widths = self._column_widths(table, word.sections[-1])
        self._set_grid_widths(word_table, widths)
        occupied: set[tuple[int, int]] = set()
        for row in table.rows:
            for cell in sorted(row.cells, key=lambda value: value.column_index):
                self._validate_cell(table, cell, occupied)
                start = word_table.cell(cell.row_index, cell.column_index)
                end = word_table.cell(cell.row_index + cell.row_span - 1, cell.column_index + cell.column_span - 1)
                target = start.merge(end) if cell.row_span > 1 or cell.column_span > 1 else start
                target.width = sum(widths[cell.column_index : cell.column_index + cell.column_span])
                target.vertical_alignment = WD_ALIGN_VERTICAL.TOP
                self._set_cell_margins(target)
                self._write_cell(target, cell.text, centered=cell.row_index == 0 or cell.text.strip().replace(".", "").replace("/", "").replace("–", "").isdigit())
                occupied.update((row_index, column_index) for row_index in range(cell.row_index, cell.row_index + cell.row_span) for column_index in range(cell.column_index, cell.column_index + cell.column_span))

    @staticmethod
    def _needs_landscape(table: Table) -> bool:
        if table.geometry is None or table.column_count < 4:
            return False
        height = table.geometry.bottom - table.geometry.top
        return height > 0 and table.geometry.width / height >= 1.4

    @staticmethod
    def _column_widths(table: Table, section) -> list[Emu]:
        samples: list[list[float]] = [[] for _ in range(table.column_count)]
        for row in table.rows:
            for cell in row.cells:
                if cell.geometry is not None:
                    width = cell.geometry.width / cell.column_span
                    for column in range(cell.column_index, cell.column_index + cell.column_span):
                        if column < table.column_count:
                            samples[column].append(width)
        raw = [median(values) if values else 1.0 for values in samples]
        total = sum(raw)
        available = section.page_width - section.left_margin - section.right_margin
        return [Emu(round(available * value / total)) for value in raw]

    @staticmethod
    def _set_grid_widths(word_table, widths: list[Emu]) -> None:
        for column, width in zip(word_table.columns, widths):
            column.width = width
        grid = word_table._tbl.tblGrid
        for grid_column, width in zip(grid.gridCol_lst, widths):
            grid_column.set(qn("w:w"), str(width.twips))
            grid_column.set(qn("w:type"), "dxa")

    @staticmethod
    def _set_cell_margins(cell) -> None:
        properties = cell._tc.get_or_add_tcPr()
        margins = properties.first_child_found_in("w:tcMar")
        if margins is None:
            margins = OxmlElement("w:tcMar")
            properties.append(margins)
        for side, value in {"top": "70", "start": "90", "bottom": "70", "end": "90"}.items():
            node = margins.find(qn(f"w:{side}"))
            if node is None:
                node = OxmlElement(f"w:{side}")
                margins.append(node)
            node.set(qn("w:w"), value)
            node.set(qn("w:type"), "dxa")

    @staticmethod
    def _validate_cell(table: Table, cell: TableCell, occupied: set[tuple[int, int]]) -> None:
        coordinates = {(row, column) for row in range(cell.row_index, cell.row_index + cell.row_span) for column in range(cell.column_index, cell.column_index + cell.column_span)}
        if cell.row_index + cell.row_span > table.row_count or cell.column_index + cell.column_span > table.column_count:
            raise ValueError(f"Cell ({cell.row_index}, {cell.column_index}) exceeds table bounds")
        if coordinates & occupied:
            raise ValueError(f"Cell ({cell.row_index}, {cell.column_index}) overlaps a previous span")

    def _write_cell(self, cell, text: str, *, centered: bool) -> None:
        paragraph = cell.paragraphs[0]
        paragraph.clear()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if centered else WD_ALIGN_PARAGRAPH.LEFT
        self._write_text(paragraph, text, font_size=Pt(8.5))

    @staticmethod
    def _write_text(paragraph, text: str, *, font_size: Pt | None = None) -> None:
        lines = text.split("\n")
        for index, line in enumerate(lines):
            if index:
                paragraph.add_run().add_break()
            run = paragraph.add_run(line)
            if font_size is not None:
                run.font.size = font_size
