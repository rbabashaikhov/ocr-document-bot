from __future__ import annotations

import json
from pathlib import Path

from ocr_document_bot.domain import InputFile
from ocr_document_bot.providers.diagnostics import DiagnosticVisionClient, redact_response


RESPONSE = {
    "textAnnotation": {
        "width": "100",
        "height": "50",
        "fullText": "Confidential participant 7 worked 4 hours",
        "markdown": "| Person | Hours |\n| Anna | 4 |",
        "blocks": [{"boundingBox": {"vertices": [{"x": "1", "y": "2"}]}, "lines": [{"text": "Morning group 7"}]}],
        "tables": [{"rowCount": "1", "columnCount": "2", "cells": [{"rowIndex": "0", "columnIndex": "1", "text": "4 hours"}]}],
    }
}


class MockVision:
    def __init__(self) -> None:
        self.closed = False

    def recognize(self, input_file: InputFile, *, language_codes: tuple[str, ...], model: str):
        return RESPONSE

    def close(self) -> None:
        self.closed = True


def test_redaction_preserves_numeric_evidence_not_raw_text() -> None:
    record = redact_response(RESPONSE)
    annotation = record["textAnnotation"]

    assert annotation["fullText"] == {"character_count": 41, "numeric_tokens": ["7", "4"]}
    assert annotation["blocks"][0]["lines"][0]["numeric_tokens"] == ["7"]
    assert annotation["tables"][0]["cells"][0]["text"]["numeric_tokens"] == ["4"]
    assert "Confidential" not in json.dumps(record)
    assert "Morning" not in json.dumps(record)


def test_diagnostic_client_writes_redacted_record_only(tmp_path: Path) -> None:
    delegate = MockVision()
    client = DiagnosticVisionClient(delegate, tmp_path)

    assert client.recognize(InputFile("source.png", "image/png", b"image", "api"), language_codes=("ru",), model="page") == RESPONSE
    records = list(tmp_path.glob("vision-diagnostic-*.json"))
    assert len(records) == 1
    content = records[0].read_text()
    assert "source.png" not in content
    assert "Confidential" not in content
    client.close()
    assert delegate.closed


def test_diagnostic_write_failure_does_not_discard_successful_ocr_response(tmp_path: Path, caplog) -> None:
    blocked_directory = tmp_path / "not-a-directory"
    blocked_directory.write_text("occupied", encoding="utf-8")
    client = DiagnosticVisionClient(MockVision(), blocked_directory)

    assert client.recognize(InputFile("source.png", "image/png", b"image", "api"), language_codes=("ru",), model="page") == RESPONSE
    assert "Vision diagnostic persistence failed" in caplog.text
