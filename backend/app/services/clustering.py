"""
HDBSCAN-based face clustering service.
All clustering is event-scoped — embeddings from different events never mix.
"""
import uuid
import numpy as np
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from ..models import FaceDetection, FaceCluster
from .ml_pipeline import bytes_to_embedding, embedding_to_bytes, cosine_distance
from ..config import get_settings

settings = get_settings()


# ─────────────────────────────────────────────────────────────────────────────
# Incremental matching — assign new face to existing cluster or flag for recluster
# ─────────────────────────────────────────────────────────────────────────────
async def assign_to_cluster(
    detection_id: uuid.UUID,
    embedding: np.ndarray,
    event_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[uuid.UUID]:
    """
    Try to assign a new face embedding to an existing cluster.
    Returns the matched cluster_id, or None if no confident match found.
    """
    result = await db.execute(
        select(FaceCluster).where(FaceCluster.event_id == event_id)
    )
    clusters = result.scalars().all()

    if not clusters:
        return None

    best_cluster_id = None
    best_distance = float("inf")

    for cluster in clusters:
        centroid = bytes_to_embedding(cluster.centroid_embedding)
        dist = cosine_distance(embedding, centroid)
        if dist < best_distance:
            best_distance = dist
            best_cluster_id = cluster.id

    if best_distance <= settings.COSINE_MATCH_THRESHOLD:
        # Update cluster centroid (running mean)
        cluster_result = await db.execute(
            select(FaceCluster).where(FaceCluster.id == best_cluster_id)
        )
        cluster = cluster_result.scalar_one()
        old_centroid = bytes_to_embedding(cluster.centroid_embedding)
        n = cluster.member_count
        new_centroid = ((old_centroid * n) + embedding) / (n + 1)
        # Re-normalise
        norm = np.linalg.norm(new_centroid)
        if norm > 0:
            new_centroid = new_centroid / norm

        cluster.centroid_embedding = embedding_to_bytes(new_centroid)
        cluster.member_count = n + 1

        # Link detection to cluster
        det_result = await db.execute(
            select(FaceDetection).where(FaceDetection.id == detection_id)
        )
        detection = det_result.scalar_one()
        detection.cluster_id = best_cluster_id
        return best_cluster_id

    return None


async def create_new_cluster(
    detection_id: uuid.UUID,
    embedding: np.ndarray,
    event_id: uuid.UUID,
    db: AsyncSession,
) -> uuid.UUID:
    """Create a new cluster seeded by a single face detection."""
    cluster = FaceCluster(
        event_id=event_id,
        centroid_embedding=embedding_to_bytes(embedding),
        member_count=1,
    )
    db.add(cluster)
    await db.flush()  # Get the ID without full commit

    det_result = await db.execute(
        select(FaceDetection).where(FaceDetection.id == detection_id)
    )
    detection = det_result.scalar_one()
    detection.cluster_id = cluster.id
    return cluster.id


# ─────────────────────────────────────────────────────────────────────────────
# Full HDBSCAN re-cluster for an event (run periodically or on-demand)
# ─────────────────────────────────────────────────────────────────────────────
async def recluster_event(event_id: uuid.UUID, db: AsyncSession) -> int:
    """
    Run HDBSCAN over all non-low-quality embeddings for an event.
    Rebuilds cluster assignments from scratch.
    Returns the number of clusters found.
    """
    import hdbscan

    # Fetch all usable detections
    result = await db.execute(
        select(FaceDetection)
        .join(FaceDetection.photo)
        .where(
            FaceDetection.photo.has(event_id=event_id),
            FaceDetection.is_low_quality == False,
        )
    )
    detections = result.scalars().all()

    if len(detections) < 2:
        return 0

    embeddings = np.array([bytes_to_embedding(d.embedding) for d in detections])
    detection_ids = [d.id for d in detections]

    # Run HDBSCAN
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=settings.HDBSCAN_MIN_CLUSTER_SIZE,
        min_samples=1,
        metric="euclidean",       # Works on L2-normalised embeddings
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(embeddings)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)

    # Delete old clusters for this event
    old_clusters = await db.execute(
        select(FaceCluster).where(FaceCluster.event_id == event_id)
    )
    for c in old_clusters.scalars().all():
        await db.delete(c)
    await db.flush()

    # Build new clusters from HDBSCAN output
    label_to_cluster: dict[int, uuid.UUID] = {}
    for idx, label in enumerate(labels):
        if label == -1:
            continue  # Noise — leave unclustered

        if label not in label_to_cluster:
            # Create cluster with this face as seed
            cluster = FaceCluster(
                event_id=event_id,
                centroid_embedding=embedding_to_bytes(embeddings[idx]),
                member_count=0,
            )
            db.add(cluster)
            await db.flush()
            label_to_cluster[label] = cluster.id

        cluster_id = label_to_cluster[label]
        det_result = await db.execute(
            select(FaceDetection).where(FaceDetection.id == detection_ids[idx])
        )
        detection = det_result.scalar_one()
        detection.cluster_id = cluster_id

    # Recompute centroids
    for label, cluster_id in label_to_cluster.items():
        mask = labels == label
        centroid = embeddings[mask].mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid /= norm
        c_result = await db.execute(select(FaceCluster).where(FaceCluster.id == cluster_id))
        cluster = c_result.scalar_one()
        cluster.centroid_embedding = embedding_to_bytes(centroid)
        cluster.member_count = int(mask.sum())

    return n_clusters


# ─────────────────────────────────────────────────────────────────────────────
# Match a selfie embedding against event clusters
# ─────────────────────────────────────────────────────────────────────────────
async def match_selfie_to_cluster(
    embedding: np.ndarray,
    event_id: uuid.UUID,
    db: AsyncSession,
) -> Tuple[Optional[uuid.UUID], float]:
    """
    Find the best matching cluster for a selfie embedding.
    Returns (cluster_id, distance) or (None, 1.0) if no confident match.
    """
    result = await db.execute(
        select(FaceCluster).where(FaceCluster.event_id == event_id)
    )
    clusters = result.scalars().all()

    if not clusters:
        return None, 1.0

    best_cluster_id = None
    best_distance = float("inf")

    for cluster in clusters:
        centroid = bytes_to_embedding(cluster.centroid_embedding)
        dist = cosine_distance(embedding, centroid)
        if dist < best_distance:
            best_distance = dist
            best_cluster_id = cluster.id

    if best_distance <= settings.COSINE_MATCH_THRESHOLD:
        return best_cluster_id, best_distance
    return None, best_distance


# ─────────────────────────────────────────────────────────────────────────────
# Admin: merge two clusters
# ─────────────────────────────────────────────────────────────────────────────
async def merge_clusters(
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    db: AsyncSession,
) -> FaceCluster:
    """Merge source cluster into target. Source is deleted."""
    src_result = await db.execute(select(FaceCluster).where(FaceCluster.id == source_id))
    tgt_result = await db.execute(select(FaceCluster).where(FaceCluster.id == target_id))
    source = src_result.scalar_one_or_none()
    target = tgt_result.scalar_one_or_none()

    if not source or not target:
        raise ValueError("One or both clusters not found.")

    if source.event_id != target.event_id:
        raise ValueError("Cannot merge clusters from different events.")

    # Weighted centroid
    src_emb = bytes_to_embedding(source.centroid_embedding)
    tgt_emb = bytes_to_embedding(target.centroid_embedding)
    n_src, n_tgt = source.member_count, target.member_count
    new_centroid = (src_emb * n_src + tgt_emb * n_tgt) / (n_src + n_tgt)
    norm = np.linalg.norm(new_centroid)
    if norm > 0:
        new_centroid /= norm

    target.centroid_embedding = embedding_to_bytes(new_centroid)
    target.member_count = n_src + n_tgt

    # Re-assign source detections to target
    await db.execute(
        update(FaceDetection)
        .where(FaceDetection.cluster_id == source_id)
        .values(cluster_id=target_id)
    )
    await db.delete(source)
    return target
