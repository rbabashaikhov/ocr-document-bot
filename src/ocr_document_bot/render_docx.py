"""Local CLI: captured OCR fixture → Document Model → editable DOCX."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocr_document_bot.providers.yandex_document_mapper import document_from_yandex_responses
from ocr_document_bot.renderers.docx_renderer import DocxRenderer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render local Yandex OCR fixtures to DOCX without calling OCR.")
    parser.add_argument("fixtures", nargs="+", type=Path, help="Local JSON OCR fixture(s), one response per page")
    parser.add_argument("--source-image", action="append", type=Path, default=[], help="Optional source image for each fixture; enables visual detection only when OCR_ENABLE_VISUAL_TABLE_DETECTION=true")
    parser.add_argument("--output", type=Path, required=True, help="Output DOCX path")
    parser.add_argument("--model", help="Optional OCR model provenance label")
    args = parser.parse_args(argv)
    missing = [str(path) for path in args.fixtures if not path.is_file()]
    if missing:
        parser.error(f"fixture does not exist: {', '.join(missing)}")
    if args.source_image and len(args.source_image) != len(args.fixtures):
        parser.error("provide exactly one --source-image for each fixture")
    missing_images = [str(path) for path in args.source_image if not path.is_file()]
    if missing_images:
        parser.error(f"source image does not exist: {', '.join(missing_images)}")
    document = document_from_yandex_responses(
        [json.loads(path.read_text(encoding="utf-8")) for path in args.fixtures], model=args.model,
        source_images=args.source_image or None,
    )
    DocxRenderer().save(document, args.output)
    print(f"saved {args.output}; pages={len(document.pages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
