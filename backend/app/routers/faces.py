"""
Faces router — selfie scan, cluster management, consent, and selfie deletion.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import desc, func, select
from pydantic import BaseModel, Field

from ..database import get_db
from ..models import (
    User, Event, Photo, PhotoStatus, FaceDetection, FaceCluster, SelfieScan,
    ConsentRecord, AuditLog, UserRole
)
from ..auth import require_attendee, require_organizer, get_current_user
from ..services.ml_pipeline import detect_and_embed, embedding_to_bytes, get_pipeline_version
from ..services.clustering import match_selfie_to_cluster, merge_clusters
from ..services.storage import generate_presigned_url
from ..services.selfie_quality import SelfieQualityError, select_selfie_face
from ..services.zip_stream import stream_zip
from ..schemas import (
    SelfieScanResponse, PhotoResponse, ClusterResponse, ClusterMergeRequest,
    DeleteSelfieResponse, ConsentRequest, ConsentResponse, MessageResponse
)
from ..config import get_settings

settings = get_settings()
router = APIRouter(prefix="/faces", tags=["Faces"])


class PersonLabelUpdate(BaseModel):
    """Organizer correction for the human-friendly People view."""

    label: str | None = Field(default=None, max_length=200)


async def _get_managed_event(
    event_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
    *,
    active_only: bool = False,
) -> Event:
    query = select(Event).where(Event.id == event_id)
    if active_only:
        query = query.where(Event.is_active == True)
    if current_user.role != UserRole.super_admin:
        query = query.where(Event.tenant_id == current_user.tenant_id)

    result = await db.execute(query)
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


# ─────────────────────────────────────────────────────────────────────────────
# Consent
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/consent", response_model=ConsentResponse, status_code=201)
async def record_consent(
    body: ConsentRequest,
    request: Request,
    current_user: User = Depends(require_attendee),
    db: AsyncSession = Depends(get_db),
):
    """Record biometric consent before selfie scan (SEC-7)."""
    await _get_managed_event(body.event_id, current_user, db, active_only=True)
    consent = ConsentRecord(
        user_id=current_user.id,
        event_id=body.event_id,
        purpose=body.purpose,
        ip_address=request.client.host if request.client else None,
    )
    db.add(consent)
    await db.flush()
    return ConsentResponse(id=consent.id, purpose=consent.purpose, given_at=consent.given_at)


# ─────────────────────────────────────────────────────────────────────────────
# Selfie Scan — core attendee flow
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/events/{event_id}/scan", response_model=SelfieScanResponse)
async def selfie_scan(
    event_id: uuid.UUID,
    selfie: UploadFile = File(...),
    current_user: User = Depends(require_attendee),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a selfie → detect face → match against event clusters → return matched photos.
    Requires prior consent record for this event.
    """
    # Verify consent (SEC-7)
    consent_result = await db.execute(
        select(ConsentRecord).where(
            ConsentRecord.user_id == current_user.id,
            ConsentRecord.event_id == event_id,
            ConsentRecord.revoked_at == None,
        )
    )
    if not consent_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Consent required before face scan.")

    # Verify event exists and is accessible to this tenant
    event = await _get_managed_event(event_id, current_user, db, active_only=True)

    # Read selfie image
    if selfie.content_type not in settings.ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=422, detail="Please upload a JPEG photo for your selfie.")

    image_bytes = await selfie.read()
    if len(image_bytes) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large")

    # Detect face in selfie
    faces = await run_in_threadpool(
        detect_and_embed,
        image_bytes,
        selfie.filename or "selfie.jpg",
    )
    try:
        best_face = select_selfie_face(faces)
    except SelfieQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Match against event clusters
    matched_cluster_id, distance = await match_selfie_to_cluster(
        best_face.embedding, event_id, db
    )

    # Persist selfie scan record
    scan = SelfieScan(
        user_id=current_user.id,
        event_id=event_id,
        matched_cluster_id=matched_cluster_id,
        embedding=embedding_to_bytes(best_face.embedding),
        pipeline_version=get_pipeline_version(),
        match_confidence=round(1.0 - distance, 4),
    )
    db.add(scan)

    # Audit
    db.add(AuditLog(
        user_id=current_user.id,
        tenant_id=event.tenant_id,
        action="selfie.scan",
        resource_type="event",
        resource_id=str(event_id),
        payload={"matched": matched_cluster_id is not None, "confidence": round(1.0 - distance, 4)},
    ))

    await db.flush()

    if not matched_cluster_id:
        await db.commit()
        return SelfieScanResponse(
            scan_id=scan.id,
            matched=False,
            match_confidence=None,
            matched_cluster_id=None,
            photo_count=0,
            photos=[],
        )

    # Retrieve all photos in the matched cluster
    det_result = await db.execute(
        select(FaceDetection).where(FaceDetection.cluster_id == matched_cluster_id)
    )
    detections = det_result.scalars().all()
    photo_ids = list({d.photo_id for d in detections})

    photo_result = await db.execute(select(Photo).where(Photo.id.in_(photo_ids)))
    photos = photo_result.scalars().all()

    photo_responses = [
        PhotoResponse(
            id=p.id,
            filename=p.filename,
            status=p.status,
            error_message=p.error_message,
            uploaded_at=p.uploaded_at,
            thumbnail_url=generate_presigned_url(p.thumbnail_key, expires_in=3600),
        )
        for p in photos
    ]

    await db.commit()

    return SelfieScanResponse(
        scan_id=scan.id,
        matched=True,
        match_confidence=round(1.0 - distance, 4),
        matched_cluster_id=matched_cluster_id,
        photo_count=len(photo_responses),
        photos=photo_responses,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Delete selfie (GDPR / SEC-8)
# ─────────────────────────────────────────────────────────────────────────────
@router.delete("/scans/{scan_id}", response_model=DeleteSelfieResponse)
async def delete_selfie(
    scan_id: uuid.UUID,
    current_user: User = Depends(require_attendee),
    db: AsyncSession = Depends(get_db),
):
    """Erase selfie embedding and unlink from matched cluster (right to erasure)."""
    result = await db.execute(
        select(SelfieScan).where(SelfieScan.id == scan_id, SelfieScan.user_id == current_user.id)
    )
    scan = result.scalar_one_or_none()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    scan.embedding = None
    scan.matched_cluster_id = None
    scan.deleted_at = datetime.now(timezone.utc)

    db.add(AuditLog(
        user_id=current_user.id,
        action="selfie.delete",
        resource_type="selfie_scan",
        resource_id=str(scan_id),
    ))
    return DeleteSelfieResponse(deleted=True, message="Selfie embedding erased")


# ─────────────────────────────────────────────────────────────────────────────
# Cluster management (organizer/admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/events/{event_id}/clusters", response_model=list[ClusterResponse])
async def list_clusters(
    event_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    await _get_managed_event(event_id, current_user, db)
    pipeline_version = get_pipeline_version()
    result = await db.execute(
        select(FaceCluster)
        .where(
            FaceCluster.event_id == event_id,
            FaceCluster.pipeline_version == pipeline_version,
        )
        .order_by(FaceCluster.member_count.desc())
    )
    clusters = result.scalars().all()
    if not clusters:
        return []

    cluster_ids = [cluster.id for cluster in clusters]
    photo_counts = {
        cluster_id: int(count or 0)
        for cluster_id, count in (await db.execute(
            select(
                FaceDetection.cluster_id,
                func.count(func.distinct(FaceDetection.photo_id)),
            )
            .where(FaceDetection.cluster_id.in_(cluster_ids))
            .group_by(FaceDetection.cluster_id)
        )).all()
    }
    ranked_faces = (
        select(
            FaceDetection.cluster_id.label("cluster_id"),
            FaceDetection.face_key.label("face_key"),
            Photo.thumbnail_key.label("photo_thumbnail_key"),
            func.row_number().over(
                partition_by=FaceDetection.cluster_id,
                order_by=(
                    desc(func.coalesce(FaceDetection.quality_score, 0.0)),
                    FaceDetection.detection_confidence.desc(),
                    FaceDetection.id,
                ),
            ).label("sample_rank"),
        )
        .join(Photo, Photo.id == FaceDetection.photo_id)
        .where(FaceDetection.cluster_id.in_(cluster_ids))
        .subquery()
    )
    thumbnail_rows = (await db.execute(
        select(
            ranked_faces.c.cluster_id,
            ranked_faces.c.face_key,
            ranked_faces.c.photo_thumbnail_key,
        )
        .where(ranked_faces.c.sample_rank <= 3)
        .order_by(ranked_faces.c.cluster_id, ranked_faces.c.sample_rank)
    )).all()
    thumbnails_by_cluster: dict[uuid.UUID, list[str]] = {}
    for cluster_id, face_key, photo_thumbnail_key in thumbnail_rows:
        key = face_key or photo_thumbnail_key
        if key:
            thumbnails_by_cluster.setdefault(cluster_id, []).append(
                generate_presigned_url(key, expires_in=3600)
            )

    out = []
    for cluster in clusters:
        out.append(ClusterResponse(
            id=cluster.id,
            member_count=cluster.member_count,
            photo_count=photo_counts.get(cluster.id, 0),
            label=cluster.label,
            updated_at=cluster.updated_at,
            sample_thumbnails=thumbnails_by_cluster.get(cluster.id, []),
        ))
    return out


@router.patch("/events/{event_id}/clusters/{cluster_id}")
async def update_person_label(
    event_id: uuid.UUID,
    cluster_id: uuid.UUID,
    body: PersonLabelUpdate,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """Name or clear a person without changing their face assignments."""
    event = await _get_managed_event(event_id, current_user, db)
    result = await db.execute(
        select(FaceCluster).where(
            FaceCluster.id == cluster_id,
            FaceCluster.event_id == event.id,
        )
    )
    cluster = result.scalar_one_or_none()
    if not cluster:
        raise HTTPException(status_code=404, detail="Person not found")

    label = body.label.strip() if body.label else None
    cluster.label = label or None
    db.add(AuditLog(
        user_id=current_user.id,
        tenant_id=event.tenant_id,
        action="person.rename",
        resource_type="face_cluster",
        resource_id=str(cluster.id),
        payload={"label": cluster.label},
    ))
    await db.flush()
    return {"id": str(cluster.id), "label": cluster.label}


@router.get("/events/{event_id}/clusters/{cluster_id}/photos", response_model=list[PhotoResponse])
async def get_cluster_photos(
    event_id: uuid.UUID,
    cluster_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all full-sized photos mapped to a specific face cluster."""
    await _get_managed_event(event_id, current_user, db)
    cluster_result = await db.execute(
        select(FaceCluster).where(
            FaceCluster.id == cluster_id,
            FaceCluster.event_id == event_id,
        )
    )
    if not cluster_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Cluster not found")

    photo_ids = list((await db.execute(
        select(FaceDetection.photo_id)
        .where(FaceDetection.cluster_id == cluster_id)
        .distinct()
    )).scalars().all())
    
    if not photo_ids:
        return []

    # SQLAlchemy SQLite workaround for UUIDs in IN clause
    photo_result = await db.execute(select(Photo).where(Photo.id.in_(photo_ids)))
    photos = photo_result.scalars().all()
    
    # Fallback if the IN clause didn't work (SQLite UUID issue)
    if not photos:
        photos = []
        for pid in photo_ids:
            pr = await db.execute(select(Photo).where(Photo.id == pid))
            p = pr.scalar_one_or_none()
            if p:
                photos.append(p)

    photo_responses = [
        PhotoResponse(
            id=p.id,
            filename=p.filename,
            status=p.status,
            error_message=p.error_message,
            uploaded_at=p.uploaded_at,
            thumbnail_url=generate_presigned_url(p.thumbnail_key, expires_in=3600) if p.thumbnail_key else None,
        )
        for p in photos
    ]
    return photo_responses


@router.get("/events/{event_id}/clusters/{cluster_id}/download")
async def download_cluster_photos_zip(
    event_id: uuid.UUID,
    cluster_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """Generate and stream a ZIP file containing all photos for this cluster."""
    await _get_managed_event(event_id, current_user, db)
    cluster_res = await db.execute(
        select(FaceCluster).where(
            FaceCluster.id == cluster_id,
            FaceCluster.event_id == event_id,
        )
    )
    cluster = cluster_res.scalar_one_or_none()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    photo_ids = list((await db.execute(
        select(FaceDetection.photo_id)
        .where(FaceDetection.cluster_id == cluster_id)
        .distinct()
    )).scalars().all())
    
    if not photo_ids:
        raise HTTPException(status_code=404, detail="No photos found for this cluster.")

    photos = (await db.execute(
        select(Photo)
        .where(Photo.id.in_(photo_ids), Photo.original_key != "")
        .order_by(Photo.uploaded_at, Photo.id)
    )).scalars().all()

    if not photos:
        raise HTTPException(status_code=404, detail="No original photos found.")

    cluster_name = cluster.label or f"Person_{str(cluster_id)[:8]}"
    safe_cluster_name = "".join(
        char if char.isascii() and (char.isalnum() or char in "-_ ") else "_"
        for char in cluster_name
    ).strip()[:80] or "Person"
    pairs = [
        (photo.original_key, photo.filename or f"photo-{index}.jpg")
        for index, photo in enumerate(photos, start=1)
    ]
    return StreamingResponse(
        stream_zip(pairs),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_cluster_name}.zip"'
        },
    )



@router.post("/clusters/merge", response_model=MessageResponse)
async def merge_two_clusters(
    body: ClusterMergeRequest,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """Admin: merge source cluster into target (corrects misclassification)."""
    if body.source_cluster_id == body.target_cluster_id:
        raise HTTPException(status_code=422, detail="Choose two different clusters")

    cluster_result = await db.execute(
        select(FaceCluster).where(
            FaceCluster.id.in_([body.source_cluster_id, body.target_cluster_id])
        )
    )
    clusters = cluster_result.scalars().all()
    if len(clusters) != 2 or clusters[0].event_id != clusters[1].event_id:
        raise HTTPException(status_code=404, detail="Clusters not found in the same event")
    await _get_managed_event(clusters[0].event_id, current_user, db)

    try:
        merged = await merge_clusters(body.source_cluster_id, body.target_cluster_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.add(AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="faces.merge_people",
        resource_type="event",
        resource_id=str(merged.event_id),
        payload={
            "source_cluster_id": str(body.source_cluster_id),
            "target_cluster_id": str(body.target_cluster_id),
        },
    ))
    return MessageResponse(message="Clusters merged successfully")


@router.post("/events/{event_id}/recluster", response_model=MessageResponse)
async def trigger_recluster(
    event_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """Admin: manually trigger re-clustering for an event."""
    from ..workers.tasks import recluster_event_task
    
    await _get_managed_event(event_id, current_user, db)
    pending = (await db.execute(
        select(func.count(Photo.id)).where(
            Photo.event_id == event_id,
            Photo.status.in_([PhotoStatus.queued, PhotoStatus.processing]),
        )
    )).scalar() or 0
    if pending:
        raise HTTPException(
            status_code=409,
            detail="Wait for photo processing to finish before rebuilding People groups.",
        )
        
    try:
        await run_in_threadpool(
            recluster_event_task.apply_async,
            args=[str(event_id)],
            queue="face-v2",
        )
    except Exception as e:
        print(f"Celery dispatch failed: {e}. Falling back to BackgroundTasks.")
        from ..services.clustering import recluster_event
        from ..database import async_session_maker
        import asyncio

        async def _recluster_bg():
            async with async_session_maker() as db2:
                await recluster_event(event_id, db2)
                from ..services.batch_tracking import finalize_event_batches
                await finalize_event_batches(db2, event_id=event_id)
                await db2.commit()

        background_tasks.add_task(_recluster_bg)
        
    return MessageResponse(message="Reclustering started in background")

