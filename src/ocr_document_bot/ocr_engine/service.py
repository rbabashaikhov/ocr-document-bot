"""Application orchestration; adapters call this service, never a provider directly."""

from __future__ import annotations

from typing import Protocol

from ocr_document_bot.domain import DocumentModel, JobStatus, OCRJob
from ocr_document_bot.preprocessing import InputPreprocessor, UnsupportedInputError


class VisionClient(Protocol):
    def recognize(self, input_file: object) -> DocumentModel: ...


class DocumentRenderer(Protocol):
    def render(self, document: DocumentModel) -> bytes: ...


class OCREngine:
    def __init__(self, preprocessor: InputPreprocessor, client: VisionClient) -> None:
        self._preprocessor = preprocessor
        self._client = client

    def recognize(self, job: OCRJob) -> OCRJob:
        try:
            job.transition_to(JobStatus.PREPROCESSING)
            prepared = self._preprocessor.prepare(job.input_file)
            job.transition_to(JobStatus.RECOGNIZING)
            job.document = self._client.recognize(prepared)
            job.transition_to(JobStatus.RENDERING)
            # Rendering is deliberately a separate use case in OCR-001.
            job.transition_to(JobStatus.COMPLETED)
        except UnsupportedInputError as error:
            job.fail("unsupported_input", str(error))
        except Exception as error:  # Provider errors are translated at this boundary in OCR-002.
            job.fail("recognition_failed", str(error))
        return job
