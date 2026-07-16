"""Durable, user-facing photo ingestion and processing stage helpers."""
from __future__ import annotations

import re
from typing import Optional

from ..models import PhotoIngestionStage, PhotoProcessingStage


INGESTION_STAGE_VALUES = tuple(stage.value for stage in PhotoIngestionStage)
PROCESSING_FILTER_VALUES = (
    "processing_not_started",
    "processing_queued",
    "processing",
    "processed",
    "processing_failed",
    "cancelled",
)
PHOTO_STAGE_FILTER_VALUES = INGESTION_STAGE_VALUES + PROCESSING_FILTER_VALUES


def sanitize_stage_error(error: object, *, limit: int = 500) -> Optional[str]:
    """Return a short diagnostic without query-string credentials or newlines."""
    text = " ".join(str(error or "").split())
    if not text:
        return None
    text = re.sub(
        r"(?i)([?&](?:key|token|signature|credential)=)[^&\s]+",
        r"\1[redacted]",
        text,
    )
    return text[: max(1, int(limit))]


def combined_photo_stage(
    ingestion_stage: PhotoIngestionStage | str,
    processing_stage: PhotoProcessingStage | str,
) -> str:
    ingestion = PhotoIngestionStage(ingestion_stage)
    processing = PhotoProcessingStage(processing_stage)
    if processing == PhotoProcessingStage.cancelled:
        return "cancelled"
    if ingestion != PhotoIngestionStage.r2_uploaded:
        return ingestion.value
    return {
        PhotoProcessingStage.not_started: "processing_not_started",
        PhotoProcessingStage.queued: "processing_queued",
        PhotoProcessingStage.processing: "processing",
        PhotoProcessingStage.processed: "processed",
        PhotoProcessingStage.failed: "processing_failed",
        PhotoProcessingStage.cancelled: "cancelled",
    }[processing]


def drive_stage_for_photo(
    ingestion_stage: PhotoIngestionStage | str,
    *,
    is_drive_import: bool,
) -> str:
    if not is_drive_import:
        return "not_applicable"
    ingestion = PhotoIngestionStage(ingestion_stage)
    if ingestion == PhotoIngestionStage.drive_queued:
        return "queued"
    if ingestion == PhotoIngestionStage.drive_downloading:
        return "downloading"
    if ingestion == PhotoIngestionStage.drive_download_failed:
        return "failed"
    return "downloaded"


def r2_stage_for_photo(ingestion_stage: PhotoIngestionStage | str) -> str:
    ingestion = PhotoIngestionStage(ingestion_stage)
    if ingestion == PhotoIngestionStage.r2_uploading:
        return "uploading"
    if ingestion == PhotoIngestionStage.r2_uploaded:
        return "uploaded"
    if ingestion == PhotoIngestionStage.r2_upload_failed:
        return "failed"
    return "not_started"
