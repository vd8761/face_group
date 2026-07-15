"""
Faces router — selfie scan, cluster management, consent, and selfie deletion.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import io
import zipfile
import httpx

from ..database import get_db
from ..models import (
    User, Event, Photo, FaceDetection, FaceCluster, SelfieScan,
    ConsentRecord, AuditLog, UserRole
)
from ..auth import require_attendee, require_organizer, get_current_user
from ..services.ml_pipeline import detect_and_embed, embedding_to_bytes
from ..services.clustering import match_selfie_to_cluster, merge_clusters
from ..services.storage import generate_presigned_url
from ..schemas import (
    SelfieScanResponse, PhotoResponse, ClusterResponse, ClusterMergeRequest,
    DeleteSelfieResponse, ConsentRequest, ConsentResponse, MessageResponse
)
from ..config import get_settings

settings = get_settings()
router = APIRouter(prefix="/faces", tags=["Faces"])


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
    event_result = await db.execute(
        select(Event).where(Event.id == event_id, Event.is_active == True)
    )
    event = event_result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found or inactive")

    # Read selfie image
    if selfie.content_type not in settings.ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=422, detail="Please upload a JPEG photo for your selfie.")

    image_bytes = await selfie.read()
    if len(image_bytes) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large")

    # Detect face in selfie
    faces = detect_and_embed(image_bytes)
    if not faces:
        raise HTTPException(status_code=422, detail="No face detected in the submitted image")

    # Use the highest-quality face
    best_face = max(faces, key=lambda f: f.quality_score)

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
    result = await db.execute(
        select(FaceCluster).where(FaceCluster.event_id == event_id).order_by(FaceCluster.member_count.desc())
    )
    clusters = result.scalars().all()

    out = []
    for cluster in clusters:
        # Get sample thumbnails (up to 3)
        det_result = await db.execute(
            select(FaceDetection).where(FaceDetection.cluster_id == cluster.id).limit(3)
        )
        detections = det_result.scalars().all()
        thumbnails = []
        for det in detections:
            if det.face_key:
                thumbnails.append(generate_presigned_url(det.face_key, expires_in=3600))
            else:
                photo_result = await db.execute(select(Photo).where(Photo.id == det.photo_id))
                photo = photo_result.scalar_one_or_none()
                if photo and photo.thumbnail_key:
                    thumbnails.append(generate_presigned_url(photo.thumbnail_key, expires_in=3600))

        out.append(ClusterResponse(
            id=cluster.id,
            member_count=cluster.member_count,
            label=cluster.label,
            updated_at=cluster.updated_at,
            sample_thumbnails=thumbnails,
        ))
    return out


@router.get("/events/{event_id}/clusters/{cluster_id}/photos", response_model=list[PhotoResponse])
async def get_cluster_photos(
    event_id: uuid.UUID,
    cluster_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all full-sized photos mapped to a specific face cluster."""
    det_result = await db.execute(
        select(FaceDetection).where(FaceDetection.cluster_id == cluster_id)
    )
    detections = det_result.scalars().all()
    photo_ids = list({d.photo_id for d in detections})
    
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
    det_result = await db.execute(
        select(FaceDetection).where(FaceDetection.cluster_id == cluster_id)
    )
    detections = det_result.scalars().all()
    photo_ids = list({d.photo_id for d in detections})
    
    if not photo_ids:
        raise HTTPException(status_code=404, detail="No photos found for this cluster.")

    photos = []
    for pid in photo_ids:
        pr = await db.execute(select(Photo).where(Photo.id == pid))
        p = pr.scalar_one_or_none()
        if p and p.original_key:
            photos.append(p)

    if not photos:
        raise HTTPException(status_code=404, detail="No original photos found.")

    cluster_res = await db.execute(select(FaceCluster).where(FaceCluster.id == cluster_id))
    cluster = cluster_res.scalar_one_or_none()
    cluster_name = cluster.label if cluster and cluster.label else f"Person_{str(cluster_id)[:8]}"

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        async with httpx.AsyncClient() as client:
            for i, p in enumerate(photos):
                url = generate_presigned_url(p.original_key, expires_in=3600)
                if not url:
                    continue
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        # try to keep original extension if possible
                        ext = p.filename.split('.')[-1] if '.' in p.filename else 'jpg'
                        filename = f"photo_{i+1}.{ext}"
                        zip_file.writestr(filename, resp.content)
                except Exception as e:
                    print(f"Failed to download photo for zip: {e}")
                    pass

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={cluster_name}.zip"}
    )



@router.post("/clusters/merge", response_model=MessageResponse)
async def merge_two_clusters(
    body: ClusterMergeRequest,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """Admin: merge source cluster into target (corrects misclassification)."""
    await merge_clusters(body.source_cluster_id, body.target_cluster_id, db)
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
    
    # Verify event exists
    event_res = await db.execute(select(Event).where(Event.id == event_id))
    if not event_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Event not found")
        
    try:
        recluster_event_task.delay(str(event_id))
    except Exception as e:
        print(f"Celery dispatch failed: {e}. Falling back to BackgroundTasks.")
        from ..services.clustering import recluster_event
        from ..database import async_session_maker
        import asyncio

        async def _recluster_bg():
            async with async_session_maker() as db2:
                await recluster_event(event_id, db2)
                await db2.commit()

        background_tasks.add_task(_recluster_bg)
        
    return MessageResponse(message="Reclustering started in background")

