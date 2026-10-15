import base64
import json
from pathlib import Path

import httpx
import pytest

from ocr_document_bot.domain import InputFile
from ocr_document_bot.cli import main
from ocr_document_bot.providers.yandex_vision import (
    VisionConfigurationError,
    YandexVisionClient,
    YandexVisionConfig,
    document_from_response,
    summarize_response,
)


MOCK_RESPONSE = json.loads((Path(__file__).parent / "data" / "mock_yandex_vision_response.json").read_text())


def test_client_sends_documented_sync_payload_and_api_key() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=MOCK_RESPONSE)

    config = YandexVisionConfig(None, "test-api-key", None)
    with YandexVisionClient(config, httpx.Client(transport=httpx.MockTransport(handler))) as client:
        result = client.recognize(InputFile("sample.png", "image/png", b"image-bytes", "api"))

    assert result == MOCK_RESPONSE
    assert captured["url"] == "https://ai.api.cloud.yandex.net/ocr/v1/recognizeText"
    assert captured["auth"] == "Api-Key test-api-key"
    assert captured["body"] == {"content": base64.b64encode(b"image-bytes").decode(), "mimeType": "image/png", "languageCodes": ["ru", "en"], "model": "page"}


def test_client_does_not_duplicate_recognize_path_in_existing_endpoint() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=MOCK_RESPONSE)

    config = YandexVisionConfig(None, "test-api-key", None, "https://example.test/ocr/v1/recognizeText")
    client = YandexVisionClient(config, httpx.Client(transport=httpx.MockTransport(handler)))
    client.recognize(InputFile("sample.png", "image/png", b"image-bytes", "api"))
    assert seen == ["https://example.test/ocr/v1/recognizeText"]


def test_config_requires_exactly_one_authentication_method() -> None:
    with pytest.raises(VisionConfigurationError):
        YandexVisionConfig(None, None, None).authorization_header()
    with pytest.raises(VisionConfigurationError):
        YandexVisionConfig(None, "key", "token").authorization_header()


def test_config_accepts_existing_environment_variable_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YANDEX_VISION_API_KEY", raising=False)
    monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("YANDEX_API_KEY=alias-key\nYANDEX_OCR_ENDPOINT=https://example.test/ocr\n")
    config = YandexVisionConfig.from_env(env_file)
    assert config.api_key == "alias-key"
    assert config.endpoint == "https://example.test/ocr"


def test_response_mapping_preserves_layout_table_spans_and_markdown() -> None:
    document = document_from_response(MOCK_RESPONSE, model="markdown")
    page = document.pages[0]
    assert page.blocks[0].layout_type == "LAYOUT_TYPE_TITLE"
    assert page.blocks[1].text == "First paragraph.\nSecond paragraph line."
    assert page.tables[0].cells[0].column_span == 2
    assert page.markdown == "# Quarterly report\n\n| A | B |"


def test_response_mapping_accepts_legacy_result_wrapper() -> None:
    document = document_from_response({"result": MOCK_RESPONSE})
    summary = summarize_response({"result": MOCK_RESPONSE})
    assert document.pages[0].number == 1
    assert summary.block_count == 2


def test_summary_does_not_claim_text_confidence() -> None:
    summary = summarize_response(MOCK_RESPONSE)
    assert summary.block_count == 2
    assert summary.layout_types == ("LAYOUT_TYPE_TITLE", "LAYOUT_TYPE_TEXT")
    assert (summary.table_count, summary.table_cell_count) == (1, 3)
    assert summary.has_markdown is True
    assert summary.has_text_confidence is False
    assert summary.picture_scores == (0.91,)


def test_cli_refuses_to_make_a_request_without_explicit_opt_in() -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["any-file.png"])
