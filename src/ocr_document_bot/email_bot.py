"""Local entry point for the optional IMAP/SMTP adapter."""

from __future__ import annotations

import logging
from pathlib import Path
import time

from ocr_document_bot.adapters.email import EmailAdapter, EmailConfig, EmailOCRService, EmailStateStore, IMAPMailbox, SMTPMailer
from ocr_document_bot.ocr_engine import DocumentOCRService
from ocr_document_bot.preprocessing import InputPreprocessor
from ocr_document_bot.providers import DiagnosticVisionClient, YandexVisionClient, YandexVisionConfig
from ocr_document_bot.providers.yandex_vision import load_env_file


def build_adapter() -> EmailAdapter:
    """Construct the local runtime; no connection is made until polling."""
    load_env_file(Path(".env"))
    config = EmailConfig.from_env()
    vision = YandexVisionClient(YandexVisionConfig.from_env())
    # Diagnostics are intentionally configured only locally and stay ignored.
    import os
    if diagnostics_dir := os.getenv("OCR_DIAGNOSTICS_DIR"):
        vision = DiagnosticVisionClient(vision, Path(diagnostics_dir))
    languages = tuple(value.strip() for value in os.getenv("OCR_LANGUAGE_CODES", "ru,en").split(",") if value.strip())
    processor = EmailOCRService(DocumentOCRService(vision, preprocessor=InputPreprocessor.from_environment(), language_codes=languages))
    return EmailAdapter(config, IMAPMailbox(config), SMTPMailer(config), processor, EmailStateStore(config.state_path))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    adapter = build_adapter()
    baseline = adapter.establish_baseline()
    logging.info("Email adapter baseline established at IMAP UID %s; only newer unseen mail will be processed", baseline)
    interval = EmailConfig.from_env().poll_interval_seconds
    while True:
        try:
            adapter.poll_once()
        except Exception:
            logging.exception("Email polling cycle failed")
        time.sleep(interval)


if __name__ == "__main__":
    main()
