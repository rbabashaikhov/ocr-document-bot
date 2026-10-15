import pytest

from ocr_document_bot.domain import InputFile
from ocr_document_bot.preprocessing import InputPreprocessor, UnsupportedInputError


def test_accepts_supported_nonempty_image() -> None:
    file = InputFile("scan.png", "image/png", b"image", "api")
    assert InputPreprocessor().prepare(file) is file


def test_rejects_unsupported_type() -> None:
    file = InputFile("scan.tiff", "image/tiff", b"image", "api")
    with pytest.raises(UnsupportedInputError, match="Unsupported MIME type"):
        InputPreprocessor().prepare(file)
