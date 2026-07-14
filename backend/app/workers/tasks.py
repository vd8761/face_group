"""
Celery tasks for asynchronous photo processing.
Each task is idempotent and retries up to 3 times on failure.
"""
import uuid
import asyncio
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


def run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=15,      # Match celery_app.py setting
    time_limit=300,              # Hard kill after 5 min (stuck tasks)
    soft_time_limit=240,         # Soft warning at 4 min
    name="app.workers.tasks.process_photo",
)
def process_photo(self, photo_id: str, tenant_id: str, event_id: str):
    """
    Main photo processing task:
    1. Download photo bytes from R2
    2. Run face detection + embedding (InsightFace)
    3. Store FaceDetection rows in DB
    4. Attempt incremental cluster assignment; create new clusters as needed
    5. Mark photo status = 'done'
    On any unhandled error: mark photo status = 'failed' with error message.
    """
    from ..database import AsyncSessionLocal
    from ..models import Photo, PhotoStatus, FaceDetection
    from ..services.storage import stream_object
    from ..services.ml_pipeline import detect_and_embed, embedding_to_bytes
    from ..services.clustering import assign_to_cluster, create_new_cluster
    from sqlalchemy import select

    async def _run():
        async with AsyncSessionLocal() as db:
            try:
                # Load photo record
                result = await db.execute(
                    select(Photo).where(Photo.id == uuid.UUID(photo_id))
                )
                photo = result.scalar_one_or_none()
                if not photo:
                    logger.error(f"Photo {photo_id} not found")
                    return

                photo.status = PhotoStatus.processing
                await db.commit()

                # Download original from R2
                body = stream_object(photo.original_key)
                image_bytes = body.read()

                # Detect faces
                detected_faces = detect_and_embed(image_bytes)
                logger.info(f"Photo {photo_id}: {len(detected_faces)} faces detected")

                for face in detected_faces:
                    # Persist detection + embedding
                    detection = FaceDetection(
                        photo_id=photo.id,
                        bbox={"x1": face.bbox[0], "y1": face.bbox[1], "x2": face.bbox[2], "y2": face.bbox[3]},
                        detection_confidence=face.confidence,
                        quality_score=face.quality_score,
                        embedding=embedding_to_bytes(face.embedding),
                        is_low_quality=face.is_low_quality,
                    )
                    db.add(detection)
                    await db.flush()

                    # Skip low-quality faces for clustering
                    if not face.is_low_quality:
                        cluster_id = await assign_to_cluster(
                            detection.id, face.embedding,
                            uuid.UUID(event_id), db
                        )
                        if cluster_id is None:
                            await create_new_cluster(
                                detection.id, face.embedding,
                                uuid.UUID(event_id), db
                            )

                photo.status = PhotoStatus.done
                await db.commit()
                logger.info(f"Photo {photo_id} processed successfully")

                # ── Auto-recluster when ALL photos in this event are done ──────
                # Check if any photos are still queued or processing.
                # If this was the last one, kick off a full HDBSCAN recluster
                # to merge any duplicate clusters created by concurrent workers.
                from sqlalchemy import func as sa_func
                pending_count_result = await db.execute(
                    select(sa_func.count(Photo.id)).where(
                        Photo.event_id == uuid.UUID(event_id),
                        Photo.status.in_([PhotoStatus.queued, PhotoStatus.processing]),
                    )
                )
                pending = pending_count_result.scalar() or 0
                if pending == 0:
                    logger.info(f"Event {event_id}: all photos done — triggering auto-recluster")
                    recluster_event_task.apply_async(
                        args=[event_id],
                        countdown=5,   # 5s delay so any in-flight commits settle
                    )


            except Exception as exc:
                await db.rollback()
                # Re-raise so the outer handler can decide retry vs fail
                raise exc

    try:
        run_async(_run())
    except Exception as exc:
        exc_str = str(exc)
        is_deadlock = "DeadlockDetected" in exc_str or "deadlock" in exc_str.lower()
        is_retriable = is_deadlock or "connection" in exc_str.lower()

        if is_retriable and self.request.retries < self.max_retries:
            # Deadlocks: retry immediately (0-2s jitter) — no need to wait 15s
            countdown = 1 if is_deadlock else 15
            logger.warning(f"Photo {photo_id} retriable error (attempt {self.request.retries+1}): {exc_str[:120]}")
            raise self.retry(exc=exc, countdown=countdown)

        # All retries exhausted — mark as permanently failed
        logger.error(f"Photo {photo_id} permanently failed: {exc_str[:200]}")
        try:
            async def _mark_failed():
                from ..database import AsyncSessionLocal
                from ..models import Photo, PhotoStatus
                from sqlalchemy import select
                async with AsyncSessionLocal() as db2:
                    result = await db2.execute(select(Photo).where(Photo.id == uuid.UUID(photo_id)))
                    photo = result.scalar_one_or_none()
                    if photo:
                        photo.status = PhotoStatus.failed
                        photo.error_message = exc_str[:500]
                        await db2.commit()
            run_async(_mark_failed())
        except Exception:
            pass
        raise exc


@shared_task(
    bind=True,
    max_retries=2,
    name="app.workers.tasks.recluster_event",
)
def recluster_event_task(self, event_id: str):
    """
    Full HDBSCAN re-cluster for an event.
    Run after bulk uploads complete or triggered manually by organizer.
    """
    from ..database import AsyncSessionLocal
    from ..services.clustering import recluster_event

    async def _run():
        async with AsyncSessionLocal() as db:
            n_clusters = await recluster_event(uuid.UUID(event_id), db)
            await db.commit()
            logger.info(f"Event {event_id} reclustered: {n_clusters} clusters")
            return n_clusters

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error(f"Recluster failed for event {event_id}: {exc}")
        raise self.retry(exc=exc)
