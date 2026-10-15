import pytest

from ocr_document_bot.domain import InputFile, JobStatus, OCRJob, OCRJobError


def test_job_has_explicit_happy_path() -> None:
    job = OCRJob(InputFile("scan.png", "image/png", b"x", "api"))
    for status in (JobStatus.PREPROCESSING, JobStatus.RECOGNIZING, JobStatus.RENDERING, JobStatus.COMPLETED):
        job.transition_to(status)
    assert job.status is JobStatus.COMPLETED


def test_job_rejects_invalid_transition() -> None:
    job = OCRJob(InputFile("scan.png", "image/png", b"x", "api"))
    with pytest.raises(OCRJobError):
        job.transition_to(JobStatus.COMPLETED)
