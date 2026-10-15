"""Yandex Vision configuration only; network client implementation is deferred to OCR-002."""

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class YandexVisionConfig:
    folder_id: str | None
    api_key: str | None
    iam_token: str | None
    endpoint: str = "https://ai.api.cloud.yandex.net/ocr/v1"

    @classmethod
    def from_env(cls) -> "YandexVisionConfig":
        return cls(
            folder_id=os.getenv("YANDEX_CLOUD_FOLDER_ID"),
            api_key=os.getenv("YANDEX_VISION_API_KEY"),
            iam_token=os.getenv("YANDEX_VISION_IAM_TOKEN"),
        )
