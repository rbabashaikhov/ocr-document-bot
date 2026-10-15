"""Local validation boundary before a document reaches an OCR provider."""

from ocr_document_bot.domain import InputFile


class UnsupportedInputError(ValueError):
    pass


class InputPreprocessor:
    SUPPORTED_MIME_TYPES = frozenset({"image/jpeg", "image/png", "application/pdf"})

    def __init__(self, max_file_size_bytes: int = 10 * 1024 * 1024) -> None:
        self.max_file_size_bytes = max_file_size_bytes

    def prepare(self, input_file: InputFile) -> InputFile:
        if input_file.mime_type not in self.SUPPORTED_MIME_TYPES:
            raise UnsupportedInputError(f"Unsupported MIME type: {input_file.mime_type}")
        if not input_file.content:
            raise UnsupportedInputError("Input file is empty")
        if len(input_file.content) > self.max_file_size_bytes:
            raise UnsupportedInputError("Input file exceeds configured size limit")
        return input_file
