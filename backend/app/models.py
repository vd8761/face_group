"""
SQLAlchemy ORM models — full schema for PhotoGroup.
Every tenant-scoped table carries tenant_id for row-level isolation.
"""
import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    String, Text, Integer, Float, Boolean, DateTime, ForeignKey,
    LargeBinary, JSON, Enum as SAEnum, func, Index, CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from .database import Base

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────
import enum

class UserRole(str, enum.Enum):
    super_admin = "super_admin"
    organizer   = "organizer"
    attendee    = "attendee"

class PhotoStatus(str, enum.Enum):
    queued      = "queued"
    processing  = "processing"
    done        = "done"
    failed      = "failed"


class PhotoIngestionStage(str, enum.Enum):
    drive_queued = "drive_queued"
    drive_downloading = "drive_downloading"
    drive_downloaded = "drive_downloaded"
    drive_download_failed = "drive_download_failed"
    r2_uploading = "r2_uploading"
    r2_uploaded = "r2_uploaded"
    r2_upload_failed = "r2_upload_failed"


class PhotoProcessingStage(str, enum.Enum):
    not_started = "not_started"
    queued = "queued"
    processing = "processing"
    processed = "processed"
    failed = "failed"
    cancelled = "cancelled"

class SubscriptionPlan(str, enum.Enum):
    starter    = "starter"
    pro        = "pro"
    enterprise = "enterprise"

class SubscriptionStatus(str, enum.Enum):
    active    = "active"
    suspended = "suspended"
    cancelled = "cancelled"


class BatchSource(str, enum.Enum):
    upload       = "upload"
    drive_import = "drive_import"
    retry        = "retry"
    reprocess    = "reprocess"


class BatchStatus(str, enum.Enum):
    receiving      = "receiving"
    queued         = "queued"
    running        = "running"
    finalizing     = "finalizing"
    completed      = "completed"
    partial_failed = "partial_failed"
    failed         = "failed"
    cancelled      = "cancelled"


class BatchItemStatus(str, enum.Enum):
    queued    = "queued"
    processing = "processing"
    succeeded = "succeeded"
    failed     = "failed"
    skipped    = "skipped"
    cancelled  = "cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# Tenant (Organisation)
# ─────────────────────────────────────────────────────────────────────────────
class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str]     = mapped_column(String(200), nullable=False)
    slug: Mapped[str]     = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    subscription: Mapped[Optional["Subscription"]] = relationship(back_populates="tenant", uselist=False)
    users: Mapped[List["User"]] = relationship(back_populates="tenant")
    events: Mapped[List["Event"]] = relationship(back_populates="tenant")


# ─────────────────────────────────────────────────────────────────────────────
# Subscription
# ─────────────────────────────────────────────────────────────────────────────
class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), unique=True)
    plan: Mapped[SubscriptionPlan] = mapped_column(SAEnum(SubscriptionPlan), default=SubscriptionPlan.starter)
    status: Mapped[SubscriptionStatus] = mapped_column(SAEnum(SubscriptionStatus), default=SubscriptionStatus.active)
    max_events_per_month: Mapped[int] = mapped_column(Integer, default=1)
    max_photos_per_event: Mapped[int] = mapped_column(Integer, default=1000)
    max_storage_gb: Mapped[float]     = mapped_column(Float, default=5.0)
    current_storage_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="subscription")


# ─────────────────────────────────────────────────────────────────────────────
# User
# ─────────────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    email: Mapped[str]        = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole]    = mapped_column(SAEnum(UserRole), default=UserRole.attendee)
    full_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool]   = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Optional["Tenant"]] = relationship(back_populates="users")
    consent_records: Mapped[List["ConsentRecord"]] = relationship(back_populates="user")
    selfie_scans: Mapped[List["SelfieScan"]] = relationship(back_populates="user")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="user")


# ─────────────────────────────────────────────────────────────────────────────
# Event
# ─────────────────────────────────────────────────────────────────────────────
class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str]        = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    access_code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    is_active: Mapped[bool]  = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped["Tenant"]  = relationship(back_populates="events")
    photos: Mapped[List["Photo"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    clusters: Mapped[List["FaceCluster"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    selfie_scans: Mapped[List["SelfieScan"]] = relationship(back_populates="event")


# ─────────────────────────────────────────────────────────────────────────────
# Photo
# ─────────────────────────────────────────────────────────────────────────────
class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    original_key: Mapped[str]  = mapped_column(String(500))   # R2 object key
    thumbnail_key: Mapped[str] = mapped_column(String(500))   # R2 object key
    original_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    filename: Mapped[str]     = mapped_column(String(255))
    mime_type: Mapped[str]    = mapped_column(String(50))
    # SHA-256 hex digest of the raw file bytes — used for duplicate detection within an event
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[PhotoStatus] = mapped_column(SAEnum(PhotoStatus), default=PhotoStatus.queued)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # These are deliberately separate from the legacy status. Ingestion can
    # fail before face processing begins, and each axis must remain visible.
    ingestion_stage: Mapped[PhotoIngestionStage] = mapped_column(
        SAEnum(PhotoIngestionStage, native_enum=False, length=32),
        nullable=False,
        default=PhotoIngestionStage.r2_uploaded,
        server_default=PhotoIngestionStage.r2_uploaded.value,
    )
    processing_stage: Mapped[PhotoProcessingStage] = mapped_column(
        SAEnum(PhotoProcessingStage, native_enum=False, length=20),
        nullable=False,
        default=PhotoProcessingStage.queued,
        server_default=PhotoProcessingStage.queued.value,
    )
    stage_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    event: Mapped["Event"] = relationship(back_populates="photos")
    face_detections: Mapped[List["FaceDetection"]] = relationship(back_populates="photo", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_photos_event_status", "event_id", "status"),
        Index("ix_photos_event_ingestion_stage", "event_id", "ingestion_stage"),
        Index("ix_photos_event_processing_stage", "event_id", "processing_stage"),
        Index("ix_photos_event_hash",   "event_id", "content_hash"),
    )


# Durable upload/import/retry processing batches. Redis is intentionally not
# the source of truth for these counters: it is used only for rolling rates and
# short-lived worker heartbeats.
class ProcessingBatch(Base):
    __tablename__ = "processing_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[BatchSource] = mapped_column(
        SAEnum(BatchSource, name="processing_batch_source"),
        nullable=False,
        default=BatchSource.upload,
    )
    status: Mapped[BatchStatus] = mapped_column(
        SAEnum(BatchStatus, name="processing_batch_status"),
        nullable=False,
        default=BatchStatus.receiving,
        index=True,
    )
    # Lets the server seal a batch once every selected file (including
    # duplicates/skips) is accounted for, even if the browser disappears.
    expected_images: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_images: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completed_images: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    succeeded_images: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_images: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_images: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    faces_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # cpu, gpu, mixed, or NULL until the first worker reports its provider.
    processor: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finalize_dispatched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finalization_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    event: Mapped["Event"] = relationship()
    created_by: Mapped[Optional["User"]] = relationship()
    items: Mapped[List["ProcessingBatchItem"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_processing_batches_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_processing_batches_event_status", "event_id", "status"),
        CheckConstraint("total_images >= 0", name="ck_processing_batches_total_nonnegative"),
        CheckConstraint("expected_images IS NULL OR expected_images >= 0", name="ck_processing_batches_expected_nonnegative"),
        CheckConstraint("completed_images >= 0 AND completed_images <= total_images", name="ck_processing_batches_completed_range"),
        CheckConstraint("succeeded_images >= 0 AND failed_images >= 0 AND skipped_images >= 0", name="ck_processing_batches_terminal_nonnegative"),
    )


class ProcessingBatchItem(Base):
    __tablename__ = "processing_batch_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable so a Drive duplicate can retain a durable skipped item after its
    # placeholder Photo row is removed.
    photo_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("photos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[BatchItemStatus] = mapped_column(
        SAEnum(BatchItemStatus, name="processing_batch_item_status"),
        nullable=False,
        default=BatchItemStatus.queued,
        index=True,
    )
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dispatch_attempted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    faces_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    processing_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    processor: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    batch: Mapped["ProcessingBatch"] = relationship(back_populates="items")
    photo: Mapped[Optional["Photo"]] = relationship()

    __table_args__ = (
        UniqueConstraint("batch_id", "photo_id", name="uq_processing_batch_item_photo"),
        Index("ix_processing_batch_items_batch_status", "batch_id", "status"),
        CheckConstraint("attempt_count >= 0", name="ck_processing_batch_items_attempt_nonnegative"),
        CheckConstraint("faces_detected >= 0", name="ck_processing_batch_items_faces_nonnegative"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# FaceCluster  (one row per detected person-group, per event)
# ─────────────────────────────────────────────────────────────────────────────
class FaceCluster(Base):
    __tablename__ = "face_clusters"

    id: Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    # Centroid embedding stored as raw bytes (numpy float32 array serialised)
    centroid_embedding: Mapped[bytes] = mapped_column(LargeBinary)
    # Embeddings from different model packs/configurations are incomparable.
    pipeline_version: Mapped[str] = mapped_column(String(100), nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # Admin-assigned label
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    event: Mapped["Event"] = relationship(back_populates="clusters")
    detections: Mapped[List["FaceDetection"]] = relationship(back_populates="cluster")
    selfie_scans: Mapped[List["SelfieScan"]] = relationship(back_populates="matched_cluster")


# ─────────────────────────────────────────────────────────────────────────────
# FaceDetection  (one row per face found in a photo)
# ─────────────────────────────────────────────────────────────────────────────
class FaceDetection(Base):
    __tablename__ = "face_detections"

    id: Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    photo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("photos.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("face_clusters.id", ondelete="SET NULL"), nullable=True, index=True)
    # Bounding box: [x1, y1, x2, y2]
    bbox: Mapped[dict] = mapped_column(JSON)
    # Optional cropped face thumbnail R2 key
    face_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    detection_confidence: Mapped[float] = mapped_column(Float)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 512-dim float32 embedding serialised as bytes
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    # Versioned identity makes task redelivery idempotent while allowing a
    # future explicit rebuild to coexist with legacy, unversioned detections.
    pipeline_version: Mapped[str] = mapped_column(String(100), nullable=False)
    face_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Organizer merges outlive transient cluster rows and are honored by
    # future full reclustering passes.
    manual_group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    is_low_quality: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    photo: Mapped["Photo"] = relationship(back_populates="face_detections")
    cluster: Mapped[Optional["FaceCluster"]] = relationship(back_populates="detections")

    __table_args__ = (
        Index(
            "uq_face_detections_photo_pipeline_face",
            "photo_id", "pipeline_version", "face_index",
            unique=True,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# SelfieScan  (attendee self-match — deletable for GDPR)
# ─────────────────────────────────────────────────────────────────────────────
class SelfieScan(Base):
    __tablename__ = "selfie_scans"

    id: Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    matched_cluster_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("face_clusters.id", ondelete="SET NULL"), nullable=True)
    # Selfie embedding — deleted on erasure request
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    pipeline_version: Mapped[str] = mapped_column(String(100), nullable=False)
    match_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="selfie_scans")
    event: Mapped["Event"] = relationship(back_populates="selfie_scans")
    matched_cluster: Mapped[Optional["FaceCluster"]] = relationship(back_populates="selfie_scans")


# ─────────────────────────────────────────────────────────────────────────────
# ConsentRecord  (biometric consent audit trail — SEC-7/SEC-8)
# ─────────────────────────────────────────────────────────────────────────────
class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=True)
    purpose: Mapped[str]     = mapped_column(String(500))
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    user: Mapped["User"] = relationship(back_populates="consent_records")


# ─────────────────────────────────────────────────────────────────────────────
# AuditLog  (SEC-6 — who accessed what, when)
# ─────────────────────────────────────────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str]      = mapped_column(String(100))       # e.g. "photo.download", "selfie.scan"
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[str]]   = mapped_column(String(100), nullable=True)
    ip_address: Mapped[Optional[str]]    = mapped_column(String(45), nullable=True)
    payload: Mapped[Optional[dict]]     = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_logs_action_created", "action", "created_at"),
    )
