"""
Public router — no authentication required.
Allows attendees to scan their selfie using just an event access code + name + phone.
"""
import uuid
from fastapi import APIRouter, UploadFile, File, Form, Request, HTTPException
from fastapi.concurrency import run_in_threadpool
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import Depends

from ..database import get_db
from ..models import Event, Photo, FaceDetection, FaceCluster, AuditLog
from ..services.ml_pipeline import detect_and_embed, embedding_to_bytes
from ..services.clustering import match_selfie_to_cluster
from ..services.storage import generate_presigned_url
from ..services.selfie_quality import SelfieQualityError, select_selfie_face
from ..config import get_settings

settings = get_settings()
router = APIRouter(prefix="/public", tags=["Public"])
_rate_limit_redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)


async def _enforce_scan_rate_limit(request: Request, event_id: uuid.UUID) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"scan-rate:{event_id}:{client_ip}"
    try:
        count = await _rate_limit_redis.incr(key)
        if count == 1:
            await _rate_limit_redis.expire(key, 3600)
        if count > settings.SCAN_RATE_LIMIT:
            ttl = max(1, await _rate_limit_redis.ttl(key))
            raise HTTPException(
                status_code=429,
                detail="Too many selfie scans. Please try again later.",
                headers={"Retry-After": str(ttl)},
            )
    except HTTPException:
        raise
    except RedisError as exc:
        print(f"Scan rate-limit check unavailable: {exc}")


@router.post("/validate-code")
async def validate_event_code(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Check whether an event access code is valid (no auth required)."""
    code = body.get("access_code", "").upper().strip()
    if not code:
        raise HTTPException(status_code=422, detail="access_code is required")
    result = await db.execute(
        select(Event).where(Event.access_code == code, Event.is_active == True)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Invalid event code. Please check and try again.")
    return {"valid": True, "event_name": event.name}


@router.post("/scan")
async def public_selfie_scan(
    request: Request,
    access_code: str = Form(...),
    full_name: str = Form(...),
    mobile: str = Form(...),
    selfie: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Guest selfie scan — no login required.
    Takes: access_code, full_name, mobile, selfie image.
    Returns matched photos from the event.
    """
    # Resolve event by access code
    event_result = await db.execute(
        select(Event).where(Event.access_code == access_code.upper(), Event.is_active == True)
    )
    event = event_result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found. Please check the access code.")

    await _enforce_scan_rate_limit(request, event.id)

    # Validate image type
    if selfie.content_type not in settings.ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=422, detail="Please upload a JPEG photo for your selfie.")

    image_bytes = await selfie.read()
    if len(image_bytes) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large. Max size is 25 MB.")

    # Detect face
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
        best_face.embedding, event.id, db
    )

    # Collect IP for audit
    ip_address = request.client.host if request.client else None

    # Audit log (anonymous guest scan)
    db.add(AuditLog(
        user_id=None,
        tenant_id=event.tenant_id,
        action="selfie.guest_scan",
        resource_type="event",
        resource_id=str(event.id),
        ip_address=ip_address,
        payload={
            "name": full_name,
            "mobile": mobile[-4:],  # Store only last 4 digits for privacy
            "matched": matched_cluster_id is not None,
            "confidence": round(1.0 - distance, 4) if distance is not None else None,
        },
    ))

    if not matched_cluster_id:
        await db.commit()
        return {
            "matched": False,
            "match_confidence": None,
            "photo_count": 0,
            "photos": [],
            "event_name": event.name,
        }

    # Get all photos in matched cluster
    det_result = await db.execute(
        select(FaceDetection).where(FaceDetection.cluster_id == matched_cluster_id)
    )
    detections = det_result.scalars().all()
    photo_ids = list({d.photo_id for d in detections})

    photo_result = await db.execute(select(Photo).where(Photo.id.in_(photo_ids)))
    photos = photo_result.scalars().all()

    photo_list = [
        {
            "id": str(p.id),
            "filename": p.filename,
            "thumbnail_url": generate_presigned_url(p.thumbnail_key, expires_in=3600),
            "download_url": generate_presigned_url(p.original_key, expires_in=3600),
        }
        for p in photos if p.thumbnail_key
    ]

    await db.commit()

    return {
        "matched": True,
        "match_confidence": round(1.0 - distance, 4),
        "photo_count": len(photo_list),
        "photos": photo_list,
        "event_name": event.name,
    }
