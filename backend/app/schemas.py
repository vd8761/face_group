"""
Pydantic request/response schemas for all API endpoints.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, Literal, Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator

from .models import (
    UserRole, PhotoStatus, SubscriptionPlan, SubscriptionStatus,
    BatchSource, BatchStatus,
)


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    tenant_id: Optional[uuid.UUID]
    user_id: uuid.UUID


class AttendeeJoinRequest(BaseModel):
    access_code: str = Field(..., min_length=4, max_length=12)
    email: EmailStr
    full_name: Optional[str] = None
    password: str = Field(..., min_length=8)


# ─────────────────────────────────────────────────────────────────────────────
# Tenant / Organisation
# ─────────────────────────────────────────────────────────────────────────────
class TenantCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    organizer_email: EmailStr
    organizer_password: str = Field(..., min_length=8)
    organizer_name: Optional[str] = None
    plan: SubscriptionPlan = SubscriptionPlan.starter


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TenantDetailResponse(TenantResponse):
    subscription: Optional["SubscriptionResponse"] = None
    event_count: int = 0
    photo_count: int = 0
    storage_used_gb: float = 0.0


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None


# ─────────────────────────────────────────────────────────────────────────────
# Subscription
# ─────────────────────────────────────────────────────────────────────────────
class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    plan: SubscriptionPlan
    status: SubscriptionStatus
    max_events_per_month: int
    max_photos_per_event: int
    max_storage_gb: float
    current_storage_bytes: int
    updated_at: datetime

    class Config:
        from_attributes = True


class SubscriptionUpdate(BaseModel):
    plan: Optional[SubscriptionPlan] = None
    status: Optional[SubscriptionStatus] = None


# ─────────────────────────────────────────────────────────────────────────────
# Event
# ─────────────────────────────────────────────────────────────────────────────
class EventCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = None


class EventResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    access_code: str
    is_active: bool
    created_at: datetime
    photo_count: int = 0
    processed_count: int = 0
    failed_count: int = 0
    queued_count: int = 0
    processing_count: int = 0
    cluster_count: int = 0
    face_pipeline_version: Optional[str] = None
    legacy_face_count: int = 0
    needs_face_rebuild: bool = False

    class Config:
        from_attributes = True


class EventUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


# ─────────────────────────────────────────────────────────────────────────────
# Photo
# ─────────────────────────────────────────────────────────────────────────────
class PhotoResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: PhotoStatus
    error_message: Optional[str]
    uploaded_at: datetime
    thumbnail_url: Optional[str] = None
    preview_url: Optional[str] = None
    original_size_bytes: int = 0
    face_count: int = 0

    class Config:
        from_attributes = True


class PhotoListResponse(BaseModel):
    photos: List[PhotoResponse]
    total: int


# ─────────────────────────────────────────────────────────────────────────────
# Processing batches + realtime telemetry
# ─────────────────────────────────────────────────────────────────────────────
class ProcessingBatchCreateRequest(BaseModel):
    source: BatchSource = BatchSource.upload
    expected_images: Optional[int] = Field(default=None, ge=0, le=100_000)


class ProcessingBatchResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    source: BatchSource
    status: BatchStatus
    expected_images: Optional[int] = None
    total_images: int
    completed_images: int
    succeeded_images: int
    failed_images: int
    skipped_images: int
    faces_detected: int
    processor: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    last_activity_at: datetime
    completed_at: Optional[datetime] = None
    updated_at: datetime
    finalization_error: Optional[str] = None

    class Config:
        from_attributes = True


class ProcessingSummary(BaseModel):
    running_batches: int = 0
    total_images: int = 0
    completed_images: int = 0
    succeeded_images: int = 0
    failed_images: int = 0
    skipped_images: int = 0
    active_images: int = 0
    remaining_images: int = 0
    faces_detected: int = 0
    images_per_second: float = 0.0
    faces_per_second: float = 0.0
    eta_seconds: Optional[int] = None


class ProcessingResources(BaseModel):
    processor: Literal["cpu", "gpu", "mixed", "unknown"] = "unknown"
    cpu_percent: Optional[float] = None
    gpu_percent: Optional[float] = None
    gpu_memory_used_bytes: Optional[int] = None
    gpu_memory_total_bytes: Optional[int] = None
    worker_count: int = 0
    stale: bool = True


class ProcessingBatchMetrics(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    event_name: str
    source: BatchSource
    status: BatchStatus
    phase: str
    processor: Literal["cpu", "gpu", "mixed", "unknown"] = "unknown"
    total_images: int = 0
    completed_images: int = 0
    succeeded_images: int = 0
    failed_images: int = 0
    skipped_images: int = 0
    active_images: int = 0
    remaining_images: int = 0
    faces_detected: int = 0
    images_per_second: float = 0.0
    faces_per_second: float = 0.0
    eta_seconds: Optional[int] = None
    progress_percent: float = 0.0
    finalization_error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    last_activity_at: datetime
    completed_at: Optional[datetime] = None
    updated_at: datetime


class ProcessingSnapshot(BaseModel):
    v: Literal[1] = 1
    type: Literal["processing.snapshot"] = "processing.snapshot"
    seq: int = 0
    emitted_at: datetime
    scope: Dict[str, Any]
    summary: ProcessingSummary
    resources: ProcessingResources
    batches: List[ProcessingBatchMetrics] = []


# ─────────────────────────────────────────────────────────────────────────────
# Face / Cluster
# ─────────────────────────────────────────────────────────────────────────────
class ClusterResponse(BaseModel):
    id: uuid.UUID
    member_count: int
    photo_count: int = 0
    label: Optional[str]
    updated_at: datetime
    # Representative thumbnail URLs from photos in this cluster
    sample_thumbnails: List[str] = []

    class Config:
        from_attributes = True


class ClusterMergeRequest(BaseModel):
    source_cluster_id: uuid.UUID
    target_cluster_id: uuid.UUID


class SelfieScanResponse(BaseModel):
    scan_id: uuid.UUID
    matched: bool
    match_confidence: Optional[float]
    matched_cluster_id: Optional[uuid.UUID]
    photo_count: int
    photos: List[PhotoResponse] = []


class DeleteSelfieResponse(BaseModel):
    deleted: bool
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# Download
# ─────────────────────────────────────────────────────────────────────────────
class ZipDownloadRequest(BaseModel):
    photo_ids: List[uuid.UUID] = Field(..., min_length=1, max_length=500)


# ─────────────────────────────────────────────────────────────────────────────
# Consent
# ─────────────────────────────────────────────────────────────────────────────
class ConsentRequest(BaseModel):
    event_id: uuid.UUID
    purpose: str = "Face recognition for photo retrieval at this event"
    accepted: bool

    @field_validator("accepted")
    @classmethod
    def must_accept(cls, v):
        if not v:
            raise ValueError("Consent must be explicitly accepted")
        return v


class ConsentResponse(BaseModel):
    id: uuid.UUID
    purpose: str
    given_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# Admin / Stats
# ─────────────────────────────────────────────────────────────────────────────
class SystemStatsResponse(BaseModel):
    total_tenants: int
    active_tenants: int
    total_events: int
    total_photos: int
    total_storage_bytes: int
    processing_queue_depth: int


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID]
    tenant_id: Optional[uuid.UUID]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    ip_address: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class PaginatedAuditLogs(BaseModel):
    logs: List[AuditLogResponse]
    total: int
    page: int
    page_size: int


# ─────────────────────────────────────────────────────────────────────────────
# Shared
# ─────────────────────────────────────────────────────────────────────────────
class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str


TenantDetailResponse.model_rebuild()
