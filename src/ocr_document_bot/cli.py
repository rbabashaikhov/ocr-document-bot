"""CLI for explicitly authorized OCR research runs."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path

from ocr_document_bot.domain import InputFile
from ocr_document_bot.providers.yandex_vision import YandexVisionClient, YandexVisionConfig, summarize_response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Save a complete Yandex Vision OCR response as a local fixture.")
    parser.add_argument("image", type=Path, help="Local JPEG, PNG, or single-page PDF")
    parser.add_argument("--mime-type", help="Override MIME type guessed from filename")
    parser.add_argument("--model", help="Vision OCR model; defaults to YANDEX_OCR_MODEL or page")
    parser.add_argument("--output", type=Path, help="Output JSON; defaults to OCR_FIXTURES_DIR/<image>.json")
    parser.add_argument("--allow-billed-request", action="store_true", help="Required acknowledgement before a network OCR request")
    args = parser.parse_args(argv)
    if not args.allow_billed_request:
        parser.error("refusing to call Vision OCR without --allow-billed-request")
    if not args.image.is_file():
        parser.error(f"input file does not exist: {args.image}")
    mime_type = args.mime_type or mimetypes.guess_type(args.image.name)[0]
    if mime_type not in {"image/jpeg", "image/png", "application/pdf"}:
        parser.error("use --mime-type with image/jpeg, image/png, or application/pdf")

    config = YandexVisionConfig.from_env()
    languages_value = os.getenv("OCR_LANGUAGE_CODES") or os.getenv("YANDEX_OCR_LANGUAGES") or "ru,en"
    languages = tuple(item.strip() for item in languages_value.split(",") if item.strip())
    model = args.model or os.getenv("YANDEX_OCR_MODEL") or "page"
    fixture_dir = Path(os.getenv("OCR_FIXTURES_DIR", "fixtures/vision"))
    output = args.output or fixture_dir / f"{args.image.stem}.json"
    input_file = InputFile(args.image.name, mime_type, args.image.read_bytes(), "api")
    with YandexVisionClient(config) as client:
        payload = client.recognize(input_file, language_codes=languages, model=model)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = summarize_response(payload)
    print(f"saved {output}; blocks={summary.block_count}, tables={summary.table_count}, cells={summary.table_cell_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
