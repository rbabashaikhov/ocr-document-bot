"""Local entry point for the optional Telegram long-polling adapter."""

from __future__ import annotations

import asyncio
import logging

from ocr_document_bot.adapters.telegram import run_polling


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
