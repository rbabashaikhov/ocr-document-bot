from io import BytesIO

import pytest
from PIL import Image

from ocr_document_bot.domain import InputFile
from ocr_document_bot.preprocessing import InputPreprocessor, UnsupportedInputError


def test_accepts_supported_nonempty_image() -> None:
    content = BytesIO()
    Image.new("RGB", (10, 10), "white").save(content, format="PNG")
    file = InputFile("scan.png", "image/png", content.getvalue(), "api")
    assert InputPreprocessor().prepare(file) is file


def test_rejects_unsupported_type() -> None:
    file = InputFile("scan.gif", "image/gif", b"image", "api")
    with pytest.raises(UnsupportedInputError, match="Unsupported file type"):
        InputPreprocessor().prepare(file)
