"""Format-normalisation tests that do not contact Yandex Vision."""

from __future__ import annotations

from io import BytesIO

import fitz
import pytest
from PIL import Image

from ocr_document_bot.domain import InputFile
from ocr_document_bot.preprocessing import InputPreprocessor, UnsupportedInputError


def _image_bytes(image_format: str, *, color: str = "white") -> bytes:
    output = BytesIO()
    Image.new("RGB", (80, 40), color=color).save(output, format=image_format)
    return output.getvalue()


def _pdf_bytes(*, native_pages: set[int] = frozenset(), pages: int = 1) -> bytes:
    document = fitz.open()
    png = _image_bytes("PNG", color="lightblue")
    for number in range(pages):
        page = document.new_page()
        if number in native_pages:
            page.insert_text((72, 72), "This PDF text layer is long enough to test native extraction safely.")
        else:
            page.insert_image(page.rect, stream=png)
    content = document.tobytes()
    document.close()
    return content


@pytest.mark.parametrize(("image_format", "mime_type"), [("WEBP", "image/webp"), ("BMP", "image/bmp")])
def test_webp_and_bmp_are_normalized_to_jpeg(image_format: str, mime_type: str) -> None:
    pages = InputPreprocessor().prepare_pages(InputFile(f"input.{image_format.lower()}", mime_type, _image_bytes(image_format), "api"))

    assert len(pages) == 1
    assert pages[0].image is not None
    assert pages[0].image.mime_type == "image/jpeg"
    assert Image.open(BytesIO(pages[0].image.content)).format == "JPEG"


def test_multipage_tiff_becomes_one_ocr_page_per_frame() -> None:
    output = BytesIO()
    first = Image.new("RGB", (40, 40), "red")
    second = Image.new("RGB", (40, 40), "blue")
    first.save(output, format="TIFF", save_all=True, append_images=[second])

    pages = InputPreprocessor().prepare_pages(InputFile("pages.tiff", "image/tiff", output.getvalue(), "api"))

    assert [page.page_number for page in pages] == [0, 1]
    assert all(page.image and page.image.mime_type == "image/jpeg" for page in pages)


def test_scanned_pdf_is_rendered_for_ocr() -> None:
    pages = InputPreprocessor().prepare_pages(InputFile("scan.pdf", "application/pdf", _pdf_bytes(), "api"))

    assert len(pages) == 1
    assert pages[0].native_text is None
    assert pages[0].image is not None and pages[0].image.mime_type == "image/jpeg"


def test_text_pdf_uses_native_text_without_rendering() -> None:
    pages = InputPreprocessor().prepare_pages(InputFile("text.pdf", "application/pdf", _pdf_bytes(native_pages={0}), "api"))

    assert len(pages) == 1
    assert pages[0].image is None
    assert "text layer" in (pages[0].native_text or "")


def test_mixed_pdf_preserves_page_order() -> None:
    pages = InputPreprocessor().prepare_pages(InputFile("mixed.pdf", "application/pdf", _pdf_bytes(native_pages={0, 2}, pages=3), "api"))

    assert [page.page_number for page in pages] == [0, 1, 2]
    assert [page.native_text is not None for page in pages] == [True, False, True]


def test_damaged_pdf_has_clear_input_error() -> None:
    with pytest.raises(UnsupportedInputError, match="damaged"):
        InputPreprocessor().prepare_pages(InputFile("broken.pdf", "application/pdf", b"not a PDF", "api"))


def test_encrypted_pdf_has_clear_input_error() -> None:
    document = fitz.open()
    document.new_page().insert_text((72, 72), "Encrypted PDF")
    output = BytesIO()
    document.save(output, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    document.close()

    with pytest.raises(UnsupportedInputError, match="encrypted"):
        InputPreprocessor().prepare_pages(InputFile("protected.pdf", "application/pdf", output.getvalue(), "api"))


def test_page_and_prepared_size_limits_are_enforced() -> None:
    multi_page = InputFile("two-pages.pdf", "application/pdf", _pdf_bytes(pages=2), "api")
    with pytest.raises(UnsupportedInputError, match="page limit"):
        InputPreprocessor(max_pages=1).prepare_pages(multi_page)

    image = InputFile("large.bmp", "image/bmp", _image_bytes("BMP"), "api")
    with pytest.raises(UnsupportedInputError, match="job size"):
        InputPreprocessor(max_job_size_bytes=10).prepare_pages(image)
