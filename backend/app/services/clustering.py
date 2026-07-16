"""
High-precision, event-scoped face grouping.

The pure helpers in this module deliberately prefer a split identity over a
false merge. Distinct faces in one photo are a hard cannot-link constraint,
high-quality faces establish identity groups, and attach-only faces never
bridge two groups. Database functions preserve those event boundaries and
reuse stable cluster rows when a new grouping substantially overlaps them.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Hashable, Mapping, Optional, Sequence, Tuple
import uuid

import numpy as np
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import FaceCluster, FaceDetection, Photo, SelfieScan
from .event_lock import lock_event_face_mutation
from .ml_pipeline import (
    bytes_to_embedding,
    cosine_distance,
    embedding_to_bytes,
    get_pipeline_version,
)

settings = get_settings()
# Environment files from older deployments used 0.65-0.75. Never allow those
# stale values to silently re-enable automatic false merges after this upgrade;
# operators may still calibrate a stricter value below this ceiling.
MAX_AUTOMATIC_MERGE_DISTANCE = 0.45


# ─────────────────────────────────────────────────────────────────────────────
# Pure constrained-clustering helpers
# ─────────────────────────────────────────────────────────────────────────────
def _normalise_matrix(embeddings: np.ndarray) -> np.ndarray:
    matrix = np.asarray(embeddings, dtype=np.float32)
    if matrix.ndim != 2:
        raise ValueError("embeddings must be a two-dimensional matrix")
    if matrix.shape[0] == 0:
        return matrix.copy()
    if not np.all(np.isfinite(matrix)):
        raise ValueError("embeddings contain non-finite values")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms <= 0):
        raise ValueError("embeddings contain a zero-norm vector")
    return matrix / norms


def cosine_distance_matrix(embeddings: np.ndarray) -> np.ndarray:
    """Pairwise cosine distance for arbitrary non-zero embedding vectors."""
    normalised = _normalise_matrix(embeddings)
    return np.clip(1.0 - normalised @ normalised.T, 0.0, 2.0)


def _bounded_anchor_edges(
    matrix: np.ndarray,
    anchor_indices: Sequence[int],
    *,
    merge_threshold: float,
    block_size: int,
    max_neighbors: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return a globally sorted, bounded nearest-neighbour edge set.

    The old implementation materialised an N x N distance matrix and then a
    Python tuple for every qualifying pair. This helper computes distances in
    small blocks and retains at most ``max_neighbors`` candidates per anchor.
    Missing an edge can only leave an identity split: the later complete-link
    check still prevents an unsafe merge.
    """
    if block_size < 1:
        raise ValueError("block_size must be positive")
    if max_neighbors < 1:
        raise ValueError("max_neighbors must be positive")

    anchors = np.asarray(anchor_indices, dtype=np.int32)
    anchor_count = int(anchors.size)
    if anchor_count < 2:
        empty_distances = np.empty(0, dtype=np.float32)
        empty_indices = np.empty(0, dtype=np.int32)
        return empty_distances, empty_indices, empty_indices.copy()

    neighbour_count = min(int(max_neighbors), anchor_count - 1)
    anchor_matrix = matrix[anchors]
    distance_chunks: list[np.ndarray] = []
    left_chunks: list[np.ndarray] = []
    right_chunks: list[np.ndarray] = []

    for row_start in range(0, anchor_count, block_size):
        row_stop = min(anchor_count, row_start + block_size)
        row_count = row_stop - row_start
        row_matrix = anchor_matrix[row_start:row_stop]
        best_distances = np.full(
            (row_count, neighbour_count), np.inf, dtype=np.float32
        )
        best_positions = np.full(
            (row_count, neighbour_count), -1, dtype=np.int32
        )

        for column_start in range(0, anchor_count, block_size):
            column_stop = min(anchor_count, column_start + block_size)
            similarities = row_matrix @ anchor_matrix[column_start:column_stop].T
            distances = np.clip(1.0 - similarities, 0.0, 2.0).astype(
                np.float32, copy=False
            )
            column_positions = np.arange(
                column_start, column_stop, dtype=np.int32
            )
            expanded_positions = np.broadcast_to(
                column_positions, distances.shape
            )

            # A face is never its own neighbour, and values outside the merge
            # gate do not need to occupy one of the bounded candidate slots.
            row_positions = np.arange(row_start, row_stop, dtype=np.int32)
            self_mask = row_positions[:, None] == column_positions[None, :]
            distances[self_mask] = np.inf
            distances[distances > merge_threshold] = np.inf

            combined_distances = np.concatenate(
                (best_distances, distances), axis=1
            )
            combined_positions = np.concatenate(
                (best_positions, expanded_positions), axis=1
            )
            # lexsort makes equal-distance selection deterministic by anchor
            # position; unlike argpartition it cannot randomly drop a tie.
            order = np.lexsort(
                (combined_positions, combined_distances), axis=1
            )[:, :neighbour_count]
            best_distances = np.take_along_axis(
                combined_distances, order, axis=1
            )
            best_positions = np.take_along_axis(
                combined_positions, order, axis=1
            )

        valid = np.isfinite(best_distances) & (best_positions >= 0)
        if not np.any(valid):
            continue
        source_positions = np.broadcast_to(
            np.arange(row_start, row_stop, dtype=np.int32)[:, None],
            best_positions.shape,
        )[valid]
        target_positions = best_positions[valid]
        source_indices = anchors[source_positions]
        target_indices = anchors[target_positions]
        left_chunks.append(np.minimum(source_indices, target_indices))
        right_chunks.append(np.maximum(source_indices, target_indices))
        distance_chunks.append(best_distances[valid])

    if not distance_chunks:
        empty_distances = np.empty(0, dtype=np.float32)
        empty_indices = np.empty(0, dtype=np.int32)
        return empty_distances, empty_indices, empty_indices.copy()

    edge_distances = np.concatenate(distance_chunks)
    edge_left = np.concatenate(left_chunks)
    edge_right = np.concatenate(right_chunks)

    # Each undirected edge can be proposed by both endpoints. Deduplicate by
    # pair using compact numpy arrays, then restore global distance order.
    pair_order = np.lexsort((edge_distances, edge_right, edge_left))
    edge_distances = edge_distances[pair_order]
    edge_left = edge_left[pair_order]
    edge_right = edge_right[pair_order]
    unique = np.ones(edge_left.size, dtype=bool)
    unique[1:] = (
        (edge_left[1:] != edge_left[:-1])
        | (edge_right[1:] != edge_right[:-1])
    )
    edge_distances = edge_distances[unique]
    edge_left = edge_left[unique]
    edge_right = edge_right[unique]

    distance_order = np.lexsort((edge_right, edge_left, edge_distances))
    return (
        edge_distances[distance_order],
        edge_left[distance_order],
        edge_right[distance_order],
    )


def _components_within_distance(
    matrix: np.ndarray,
    left_members: Sequence[int],
    right_members: Sequence[int],
    *,
    max_distance: float,
    block_size: int,
) -> bool:
    """Memory-bounded complete-link check for two proposed components."""
    left = tuple(sorted(left_members))
    right = tuple(sorted(right_members))
    for left_start in range(0, len(left), block_size):
        left_indices = np.asarray(
            left[left_start:left_start + block_size], dtype=np.int32
        )
        left_block = matrix[left_indices]
        for right_start in range(0, len(right), block_size):
            right_indices = np.asarray(
                right[right_start:right_start + block_size], dtype=np.int32
            )
            right_block = matrix[right_indices]
            distances = np.clip(1.0 - left_block @ right_block.T, 0.0, 2.0)
            if distances.size and float(distances.max()) > max_distance:
                return False
    return True


class _UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> int:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return left_root
        # Stable root selection makes repeated runs deterministic.
        keep, drop = sorted((left_root, right_root))
        self.parent[drop] = keep
        return keep


def constrained_cluster_labels(
    embeddings: np.ndarray,
    photo_ids: Sequence[Hashable],
    *,
    anchor_mask: Optional[Sequence[bool]] = None,
    must_link_groups: Optional[Sequence[Optional[Hashable]]] = None,
    merge_threshold: float = 0.45,
    max_cluster_distance: float = 0.52,
    attach_threshold: float = 0.38,
    attach_margin: float = 0.05,
    distance_block_size: int = 256,
    candidate_neighbors: int = 64,
) -> np.ndarray:
    """
    Cluster anchors first, then attach weaker faces without allowing bridging.

    Two components may merge only when they have no photo in common and every
    cross-component anchor pair remains inside ``max_cluster_distance``. Faces
    outside ``anchor_mask`` can attach to one established component using the
    stricter ``attach_threshold`` but never become prototypes for later faces.
    """
    matrix = _normalise_matrix(embeddings)
    count = matrix.shape[0]
    if len(photo_ids) != count:
        raise ValueError("photo_ids and embeddings must have the same length")
    if count == 0:
        return np.empty(0, dtype=np.int32)

    if anchor_mask is None:
        anchors = np.ones(count, dtype=bool)
    else:
        anchors = np.asarray(anchor_mask, dtype=bool)
        if anchors.shape != (count,):
            raise ValueError("anchor_mask must contain one value per embedding")
    if must_link_groups is not None and len(must_link_groups) != count:
        raise ValueError("must_link_groups must contain one value per embedding")

    union_find = _UnionFind(count)
    anchor_indices = [idx for idx, is_anchor in enumerate(anchors) if is_anchor]
    members: dict[int, set[int]] = {idx: {idx} for idx in anchor_indices}
    member_photos: dict[int, set[Hashable]] = {
        idx: {photo_ids[idx]} for idx in anchor_indices
    }

    edge_distances, edge_left, edge_right = _bounded_anchor_edges(
        matrix,
        anchor_indices,
        merge_threshold=merge_threshold,
        block_size=distance_block_size,
        max_neighbors=candidate_neighbors,
    )

    for edge_index in range(edge_distances.size):
        left = int(edge_left[edge_index])
        right = int(edge_right[edge_index])
        left_root, right_root = union_find.find(left), union_find.find(right)
        if left_root == right_root:
            continue
        left_members, right_members = members[left_root], members[right_root]
        if member_photos[left_root] & member_photos[right_root]:
            continue
        if not _components_within_distance(
            matrix,
            left_members,
            right_members,
            max_distance=max_cluster_distance,
            block_size=distance_block_size,
        ):
            continue

        root = union_find.union(left_root, right_root)
        other = right_root if root == left_root else left_root
        members[root] = left_members | right_members
        member_photos[root] = member_photos[left_root] | member_photos[right_root]
        members.pop(other, None)
        member_photos.pop(other, None)

    # Snapshot anchor prototypes. Attach-only faces are intentionally excluded
    # from future scoring so a weak face can never chain two identities.
    anchor_groups: dict[int, tuple[int, ...]] = {}
    for anchor in anchor_indices:
        root = union_find.find(anchor)
        anchor_groups[root] = tuple(sorted(members[root]))

    assigned_root: dict[int, int] = {
        anchor: union_find.find(anchor) for anchor in anchor_indices
    }
    # Score every weak face in a photo before assigning any of them. If two
    # boxes compete for the same identity, the stronger proposal wins rather
    # than whichever face happened to be inserted first.
    weak_by_photo: dict[Hashable, list[int]] = defaultdict(list)
    for idx in (i for i in range(count) if not anchors[i]):
        weak_by_photo[photo_ids[idx]].append(idx)

    next_singleton_root = count
    for photo_id, weak_indices in weak_by_photo.items():
        proposals: list[tuple[float, float, int, int]] = []
        for idx in weak_indices:
            candidates: list[tuple[float, int]] = []
            for root, prototypes in anchor_groups.items():
                if photo_id in member_photos[root]:
                    continue
                similarities = matrix[list(prototypes)] @ matrix[idx]
                score = float(np.clip(1.0 - similarities.max(), 0.0, 2.0))
                candidates.append((score, root))
            candidates.sort(key=lambda item: (item[0], item[1]))
            if not candidates or candidates[0][0] > attach_threshold:
                continue
            runner_up = candidates[1][0] if len(candidates) > 1 else float("inf")
            margin = runner_up - candidates[0][0]
            if margin >= attach_margin:
                proposals.append((candidates[0][0], -margin, idx, candidates[0][1]))

        claimed_roots: set[int] = set()
        accepted_indices: set[int] = set()
        for _score, _negative_margin, idx, root in sorted(proposals):
            if root in claimed_roots:
                continue
            assigned_root[idx] = root
            claimed_roots.add(root)
            accepted_indices.add(idx)
            member_photos[root].add(photo_id)

        for idx in weak_indices:
            if idx in accepted_indices:
                continue
            assigned_root[idx] = next_singleton_root
            next_singleton_root += 1

    # Explicit organizer merges persist across automatic regrouping. They are
    # applied last so only a human correction may override an automatic
    # cannot-link or distance decision.
    if must_link_groups is not None:
        roots_by_manual_group: dict[Hashable, set[int]] = defaultdict(set)
        for idx, manual_group in enumerate(must_link_groups):
            if manual_group is not None:
                roots_by_manual_group[manual_group].add(assigned_root[idx])
        manual_union = _UnionFind(max(next_singleton_root + 1, count + 1))
        for roots in roots_by_manual_group.values():
            ordered_roots = sorted(roots)
            for root in ordered_roots[1:]:
                manual_union.union(ordered_roots[0], root)
        for idx, root in tuple(assigned_root.items()):
            assigned_root[idx] = manual_union.find(root)

    root_to_label: dict[int, int] = {}
    labels: list[int] = []
    for idx in range(count):
        root = assigned_root[idx]
        if root not in root_to_label:
            root_to_label[root] = len(root_to_label)
        labels.append(root_to_label[root])
    return np.asarray(labels, dtype=np.int32)


def reuse_clusters_by_overlap(
    new_groups: Sequence[set[Hashable]],
    old_members: Mapping[Hashable, set[Hashable]],
    *,
    min_new_overlap: float = 0.50,
    min_old_overlap: float = 0.50,
) -> dict[int, Hashable]:
    """Preserve an ID only for a mutual, strict-majority continuation.

    Requiring more than half of both groups prevents a small fragment from
    stealing the old label and also makes the mapping naturally one-to-one for
    real cluster partitions. The explicit thresholds may make the rule stricter
    but can never relax the safety floor to an ambiguous 50/50 split.
    """
    if not 0.0 <= min_new_overlap <= 1.0:
        raise ValueError("min_new_overlap must be between zero and one")
    if not 0.0 <= min_old_overlap <= 1.0:
        raise ValueError("min_old_overlap must be between zero and one")

    candidates: list[tuple[float, float, float, int, int, Hashable]] = []
    for new_index, new_members in enumerate(new_groups):
        if not new_members:
            continue
        for old_id, old_group in old_members.items():
            if not old_group:
                continue
            overlap = len(new_members & old_group)
            new_coverage = overlap / len(new_members)
            old_coverage = overlap / len(old_group)
            if (
                overlap == 0
                or new_coverage <= 0.50
                or old_coverage <= 0.50
                or new_coverage < min_new_overlap
                or old_coverage < min_old_overlap
            ):
                continue
            union_size = len(new_members | old_group)
            jaccard = overlap / union_size if union_size else 0.0
            candidates.append((
                jaccard,
                new_coverage,
                old_coverage,
                overlap,
                new_index,
                old_id,
            ))

    candidates.sort(
        key=lambda item: (
            -item[0], -item[1], -item[2], -item[3], item[4], str(item[5])
        )
    )
    mapping: dict[int, Hashable] = {}
    used_old: set[Hashable] = set()
    for (
        _jaccard,
        _new_coverage,
        _old_coverage,
        _overlap,
        new_index,
        old_id,
    ) in candidates:
        if new_index in mapping or old_id in used_old:
            continue
        mapping[new_index] = old_id
        used_old.add(old_id)
    return mapping


def choose_selfie_match(
    candidates: Sequence[tuple[Hashable, float, int]],
    *,
    match_threshold: float,
    strong_threshold: float,
    runner_up_margin: float,
) -> tuple[Optional[Hashable], float]:
    """Apply prototype support and top-two-person ambiguity rejection."""
    if not candidates:
        return None, 1.0
    ordered = sorted(candidates, key=lambda item: (item[1], str(item[0])))
    best_id, best_distance, support = ordered[0]
    qualifies = best_distance <= strong_threshold or (
        best_distance <= match_threshold and support >= 2
    )
    if not qualifies:
        return None, best_distance
    if len(ordered) > 1 and ordered[1][1] - best_distance < runner_up_margin:
        return None, best_distance
    return best_id, best_distance


def _normalised_centroid(embeddings: Sequence[np.ndarray]) -> np.ndarray:
    if not embeddings:
        raise ValueError("Cannot compute a centroid without embeddings")
    matrix = _normalise_matrix(np.asarray(embeddings, dtype=np.float32))
    centroid = matrix.mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    if norm <= 0:
        raise ValueError("Cluster centroid has zero norm")
    return centroid / norm


def _incremental_candidate_metrics(
    embedding: np.ndarray,
    anchor_prototypes: Sequence[np.ndarray],
    all_prototypes: Sequence[np.ndarray],
    *,
    incoming_is_anchor: bool,
    merge_threshold: float,
    max_cluster_distance: float,
    attach_threshold: float,
) -> Optional[tuple[float, bool]]:
    """Return nearest-prototype distance and whether a cluster is admissible."""
    incoming = _normalise_matrix(
        np.asarray(embedding, dtype=np.float32).reshape(1, -1)
    )[0]
    anchors = list(anchor_prototypes)
    prototypes = anchors if anchors else list(all_prototypes)
    if not prototypes:
        return None

    prototype_matrix = _normalise_matrix(
        np.asarray(prototypes, dtype=np.float32)
    )
    distances = np.clip(1.0 - prototype_matrix @ incoming, 0.0, 2.0)
    nearest = float(distances.min())

    if not incoming_is_anchor:
        # Attach-only faces can use established anchors, never another weak
        # face or a centroid that may have been seeded by one.
        if not anchors:
            return None
        return nearest, nearest <= attach_threshold

    if anchors:
        # This is the singleton-to-component equivalent of the batch
        # clustering rule: one real merge edge plus complete-link protection.
        admissible = (
            nearest <= merge_threshold
            and float(distances.max()) <= max_cluster_distance
        )
        return nearest, admissible

    # A strong face may rescue a weak-only singleton, but only if every weak
    # member could itself attach to that new anchor under the strict gate.
    return nearest, float(distances.max()) <= attach_threshold


def choose_incremental_cluster(
    embedding: np.ndarray,
    candidates: Mapping[
        Hashable,
        tuple[Sequence[np.ndarray], Sequence[np.ndarray]],
    ],
    *,
    incoming_is_anchor: bool,
    merge_threshold: float,
    max_cluster_distance: float,
    attach_threshold: float,
    runner_up_margin: float,
) -> tuple[Optional[Hashable], float]:
    """Choose one prototype-backed cluster with ambiguity rejection.

    Candidate values are ``(anchor_prototypes, all_prototypes)``. An
    inadmissible but nearby identity still counts as a runner-up, preventing a
    complete-link rejection from silently redirecting the face to a worse
    cluster.
    """
    if runner_up_margin < 0:
        raise ValueError("runner_up_margin cannot be negative")

    scored: list[tuple[float, str, Hashable, bool]] = []
    for cluster_id, (anchors, prototypes) in candidates.items():
        metrics = _incremental_candidate_metrics(
            embedding,
            anchors,
            prototypes,
            incoming_is_anchor=incoming_is_anchor,
            merge_threshold=merge_threshold,
            max_cluster_distance=max_cluster_distance,
            attach_threshold=attach_threshold,
        )
        if metrics is None:
            continue
        distance, admissible = metrics
        scored.append((distance, str(cluster_id), cluster_id, admissible))

    if not scored:
        return None, 1.0
    scored.sort(key=lambda item: (item[0], item[1]))
    admissible = [item for item in scored if item[3]]
    if not admissible:
        return None, scored[0][0]

    best_distance, _stable_id, best_id, _accepted = admissible[0]
    runner_up = min(
        (item[0] for item in scored if item[2] != best_id),
        default=float("inf"),
    )
    if runner_up - best_distance < runner_up_margin:
        return None, best_distance
    return best_id, best_distance


# ─────────────────────────────────────────────────────────────────────────────
# Incremental assignment
# ─────────────────────────────────────────────────────────────────────────────
async def _cluster_has_photo(
    cluster_id: uuid.UUID,
    photo_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    result = await db.execute(
        select(FaceDetection.id)
        .where(
            FaceDetection.cluster_id == cluster_id,
            FaceDetection.photo_id == photo_id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def assign_to_cluster(
    detection_id: uuid.UUID,
    embedding: np.ndarray,
    event_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[uuid.UUID]:
    """Assign a face using the same conservative invariants as batch grouping."""
    await lock_event_face_mutation(event_id, db)
    detection_result = await db.execute(
        select(FaceDetection, Photo.event_id)
        .join(Photo, Photo.id == FaceDetection.photo_id)
        .where(FaceDetection.id == detection_id)
    )
    row = detection_result.one_or_none()
    if row is None:
        raise ValueError(f"Face detection {detection_id} was not found")
    detection, detection_event_id = row
    if detection_event_id != event_id:
        raise ValueError("Detection and requested cluster event do not match")
    if detection.cluster_id is not None:
        return detection.cluster_id
    pipeline_version = detection.pipeline_version

    quality = float(detection.quality_score or 0.0)
    incoming_is_anchor = quality >= settings.FACE_ANCHOR_QUALITY_THRESHOLD
    merge_threshold = min(
        float(settings.COSINE_MATCH_THRESHOLD),
        MAX_AUTOMATIC_MERGE_DISTANCE,
    )
    max_cluster_distance = float(settings.CLUSTER_MAX_DISTANCE_THRESHOLD)
    attach_threshold = float(settings.FACE_ATTACH_DISTANCE_THRESHOLD)
    runner_up_margin = float(settings.FACE_ATTACH_MARGIN)

    # Build a consistent prototype snapshot for every event cluster. Centroids
    # are not sufficient for complete-link safety or top-two ambiguity checks.
    prototype_rows = (
        await db.execute(
            select(
                FaceDetection.cluster_id,
                FaceDetection.embedding,
                FaceDetection.quality_score,
                FaceDetection.photo_id,
            )
            .join(Photo, Photo.id == FaceDetection.photo_id)
            .join(FaceCluster, FaceCluster.id == FaceDetection.cluster_id)
            .where(
                Photo.event_id == event_id,
                FaceDetection.cluster_id.is_not(None),
                FaceDetection.is_low_quality.is_(False),
                FaceDetection.pipeline_version == pipeline_version,
                FaceCluster.pipeline_version == pipeline_version,
            )
            .order_by(
                FaceDetection.cluster_id,
                FaceDetection.created_at,
                FaceDetection.id,
            )
        )
    ).all()
    all_prototypes: dict[uuid.UUID, list[np.ndarray]] = defaultdict(list)
    anchor_prototypes: dict[uuid.UUID, list[np.ndarray]] = defaultdict(list)
    cluster_photos: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    invalid_clusters: set[uuid.UUID] = set()
    for cluster_id, blob, row_quality, row_photo_id in prototype_rows:
        if cluster_id in invalid_clusters:
            continue
        try:
            vector = bytes_to_embedding(blob)
        except ValueError:
            invalid_clusters.add(cluster_id)
            all_prototypes.pop(cluster_id, None)
            anchor_prototypes.pop(cluster_id, None)
            cluster_photos.pop(cluster_id, None)
            continue
        all_prototypes[cluster_id].append(vector)
        cluster_photos[cluster_id].add(row_photo_id)
        if float(row_quality or 0.0) >= settings.FACE_ANCHOR_QUALITY_THRESHOLD:
            anchor_prototypes[cluster_id].append(vector)

    evidence = {
        cluster_id: (
            tuple(anchor_prototypes.get(cluster_id, ())),
            tuple(vectors),
        )
        for cluster_id, vectors in all_prototypes.items()
        if (
            cluster_id not in invalid_clusters
            and detection.photo_id not in cluster_photos[cluster_id]
        )
    }
    chosen_id, _snapshot_distance = choose_incremental_cluster(
        embedding,
        evidence,
        incoming_is_anchor=incoming_is_anchor,
        merge_threshold=merge_threshold,
        max_cluster_distance=max_cluster_distance,
        attach_threshold=attach_threshold,
        runner_up_margin=runner_up_margin,
    )
    if chosen_id is None:
        return None
    cluster_id = uuid.UUID(str(chosen_id))

    # Lock only the proven winner. Redirecting to a runner-up because the best
    # row is busy would defeat the ambiguity check; a temporary singleton is
    # safer and will be reconsidered by final grouping.
    if await _cluster_has_photo(cluster_id, detection.photo_id, db):
        return None
    lock_result = await db.execute(
        select(FaceCluster)
        .where(
            FaceCluster.id == cluster_id,
            FaceCluster.event_id == event_id,
            FaceCluster.pipeline_version == pipeline_version,
        )
        .with_for_update(skip_locked=True)
    )
    cluster = lock_result.scalar_one_or_none()
    if cluster is None:
        return None
    if await _cluster_has_photo(cluster.id, detection.photo_id, db):
        return None

    existing_rows = (
        await db.execute(
            select(
                FaceDetection.embedding,
                FaceDetection.quality_score,
                FaceDetection.is_low_quality,
            )
            .where(
                FaceDetection.cluster_id == cluster.id,
                FaceDetection.pipeline_version == pipeline_version,
            )
            .order_by(FaceDetection.created_at, FaceDetection.id)
        )
    ).all()
    current_all: list[np.ndarray] = []
    current_anchors: list[np.ndarray] = []
    try:
        for blob, row_quality, is_low_quality in existing_rows:
            if is_low_quality:
                continue
            vector = bytes_to_embedding(blob)
            current_all.append(vector)
            if float(row_quality or 0.0) >= settings.FACE_ANCHOR_QUALITY_THRESHOLD:
                current_anchors.append(vector)
    except ValueError:
        return None
    if not current_all:
        return None

    # Replace the winner's snapshot with its locked state and repeat the full
    # choice. This catches centroid/prototype changes committed while waiting.
    refreshed_evidence = dict(evidence)
    refreshed_evidence[cluster.id] = (tuple(current_anchors), tuple(current_all))
    refreshed_id, _current_distance = choose_incremental_cluster(
        embedding,
        refreshed_evidence,
        incoming_is_anchor=incoming_is_anchor,
        merge_threshold=merge_threshold,
        max_cluster_distance=max_cluster_distance,
        attach_threshold=attach_threshold,
        runner_up_margin=runner_up_margin,
    )
    if refreshed_id != cluster.id:
        return None

    if incoming_is_anchor:
        current_anchors.append(embedding)
    # Every accepted path now has at least one high-quality anchor: weak faces
    # require one, and a strong face becomes one when rescuing a weak singleton.
    cluster.centroid_embedding = embedding_to_bytes(
        _normalised_centroid(current_anchors)
    )
    cluster.member_count = len(existing_rows) + 1
    detection.cluster_id = cluster.id
    return cluster.id


async def create_new_cluster(
    detection_id: uuid.UUID,
    embedding: np.ndarray,
    event_id: uuid.UUID,
    db: AsyncSession,
) -> uuid.UUID:
    """Create an event-scoped singleton, or return its existing assignment."""
    await lock_event_face_mutation(event_id, db)
    detection_result = await db.execute(
        select(FaceDetection, Photo.event_id)
        .join(Photo, Photo.id == FaceDetection.photo_id)
        .where(FaceDetection.id == detection_id)
    )
    row = detection_result.one_or_none()
    if row is None:
        raise ValueError(f"Face detection {detection_id} was not found")
    detection, detection_event_id = row
    if detection_event_id != event_id:
        raise ValueError("Detection and requested cluster event do not match")
    if detection.cluster_id is not None:
        return detection.cluster_id

    cluster = FaceCluster(
        event_id=event_id,
        centroid_embedding=embedding_to_bytes(embedding),
        pipeline_version=detection.pipeline_version,
        member_count=1,
    )
    db.add(cluster)
    await db.flush()
    detection.cluster_id = cluster.id
    return cluster.id


# ─────────────────────────────────────────────────────────────────────────────
# Full constrained reclustering with stable ID reuse
# ─────────────────────────────────────────────────────────────────────────────
async def recluster_event(event_id: uuid.UUID, db: AsyncSession) -> int:
    """Build constrained event groups and preserve old cluster identity by overlap."""
    await lock_event_face_mutation(event_id, db)
    pipeline_version = get_pipeline_version()

    detections = (
        await db.execute(
            select(FaceDetection)
            .join(Photo, Photo.id == FaceDetection.photo_id)
            .where(
                Photo.event_id == event_id,
                FaceDetection.pipeline_version == pipeline_version,
            )
            .order_by(FaceDetection.created_at, FaceDetection.id)
        )
    ).scalars().all()
    old_clusters = (
        await db.execute(
            select(FaceCluster).where(
                FaceCluster.event_id == event_id,
                FaceCluster.pipeline_version == pipeline_version,
            )
        )
    ).scalars().all()
    old_by_id = {cluster.id: cluster for cluster in old_clusters}
    usable = [detection for detection in detections if not detection.is_low_quality]
    old_members: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for detection in usable:
        if detection.cluster_id is not None:
            old_members[detection.cluster_id].add(detection.id)

    for detection in detections:
        if detection.is_low_quality:
            detection.cluster_id = None

    if not usable:
        await db.flush()
        for cluster in old_clusters:
            await db.delete(cluster)
        return 0

    embeddings = np.asarray(
        [bytes_to_embedding(detection.embedding) for detection in usable],
        dtype=np.float32,
    )
    photo_ids = [detection.photo_id for detection in usable]
    anchor_mask = [
        float(detection.quality_score or 0.0) >= settings.FACE_ANCHOR_QUALITY_THRESHOLD
        for detection in usable
    ]
    labels = constrained_cluster_labels(
        embeddings,
        photo_ids,
        anchor_mask=anchor_mask,
        must_link_groups=[detection.manual_group_id for detection in usable],
        merge_threshold=min(
            float(settings.AGGLOMERATIVE_DISTANCE_THRESHOLD),
            MAX_AUTOMATIC_MERGE_DISTANCE,
        ),
        max_cluster_distance=float(settings.CLUSTER_MAX_DISTANCE_THRESHOLD),
        attach_threshold=float(settings.FACE_ATTACH_DISTANCE_THRESHOLD),
        attach_margin=float(settings.FACE_ATTACH_MARGIN),
    )

    indices_by_label: dict[int, list[int]] = defaultdict(list)
    for idx, label in enumerate(labels):
        indices_by_label[int(label)].append(idx)
    grouped_indices = [
        indices_by_label[label] for label in sorted(indices_by_label)
    ]
    new_member_sets = [
        {usable[idx].id for idx in indices} for indices in grouped_indices
    ]
    reused = reuse_clusters_by_overlap(
        new_member_sets,
        old_members,
        min_new_overlap=float(settings.CLUSTER_ID_REUSE_MIN_OVERLAP),
    )

    reused_ids: set[uuid.UUID] = set()
    for group_index, indices in enumerate(grouped_indices):
        old_id = reused.get(group_index)
        cluster = old_by_id.get(old_id) if old_id is not None else None
        if cluster is None:
            cluster = FaceCluster(
                event_id=event_id,
                centroid_embedding=embedding_to_bytes(embeddings[indices[0]]),
                pipeline_version=pipeline_version,
                member_count=0,
            )
            db.add(cluster)
            await db.flush()
        else:
            reused_ids.add(cluster.id)

        group_embeddings = [embeddings[idx] for idx in indices]
        group_anchors = [embeddings[idx] for idx in indices if anchor_mask[idx]]
        cluster.centroid_embedding = embedding_to_bytes(
            _normalised_centroid(group_anchors or group_embeddings)
        )
        cluster.member_count = len(indices)
        for idx in indices:
            usable[idx].cluster_id = cluster.id

    # Flush reassignment first, then remove only obsolete cluster rows. Reused
    # rows retain IDs, labels, creation timestamps, and linked selfie scans.
    await db.flush()
    for cluster in old_clusters:
        if cluster.id not in reused_ids:
            await db.delete(cluster)
    await db.flush()

    # ON DELETE SET NULL protects referential integrity, then stored selfies
    # from this exact pipeline are rematched to the newly formed identities.
    orphaned_scans = (await db.execute(
        select(SelfieScan).where(
            SelfieScan.event_id == event_id,
            SelfieScan.pipeline_version == pipeline_version,
            SelfieScan.embedding.is_not(None),
            SelfieScan.deleted_at.is_(None),
            SelfieScan.matched_cluster_id.is_(None),
        )
    )).scalars().all()
    for scan in orphaned_scans:
        try:
            match_id, distance = await match_selfie_to_cluster(
                bytes_to_embedding(scan.embedding), event_id, db
            )
        except ValueError:
            continue
        scan.matched_cluster_id = match_id
        scan.match_confidence = round(1.0 - distance, 4) if match_id else None
    return len(grouped_indices)


# ─────────────────────────────────────────────────────────────────────────────
# Multi-prototype selfie search
# ─────────────────────────────────────────────────────────────────────────────
async def match_selfie_to_cluster(
    embedding: np.ndarray,
    event_id: uuid.UUID,
    db: AsyncSession,
) -> Tuple[Optional[uuid.UUID], float]:
    """Match against high-quality person prototypes with ambiguity rejection."""
    pipeline_version = get_pipeline_version()
    clusters = (
        await db.execute(
            select(FaceCluster).where(
                FaceCluster.event_id == event_id,
                FaceCluster.pipeline_version == pipeline_version,
            )
        )
    ).scalars().all()
    if not clusters:
        return None, 1.0

    cluster_ids = [cluster.id for cluster in clusters]
    limit = max(1, int(settings.SELFIE_PROTOTYPES_PER_CLUSTER))
    ranked_prototypes = (
        select(
            FaceDetection.cluster_id.label("cluster_id"),
            FaceDetection.embedding.label("embedding"),
            FaceDetection.quality_score.label("quality_score"),
            func.row_number().over(
                partition_by=FaceDetection.cluster_id,
                order_by=(
                    FaceDetection.quality_score.desc().nullslast(),
                    FaceDetection.created_at,
                    FaceDetection.id,
                ),
            ).label("prototype_rank"),
        )
        .join(Photo, Photo.id == FaceDetection.photo_id)
        .where(
            Photo.event_id == event_id,
            FaceDetection.cluster_id.in_(cluster_ids),
            FaceDetection.pipeline_version == pipeline_version,
            FaceDetection.is_low_quality.is_(False),
            FaceDetection.quality_score >= settings.FACE_ANCHOR_QUALITY_THRESHOLD,
        )
        .subquery()
    )
    # Keep the cap in SQL; large celebrity/event clusters must not load every
    # stored anchor merely to discard all but a handful in Python.
    prototype_rows = (await db.execute(
        select(
            ranked_prototypes.c.cluster_id,
            ranked_prototypes.c.embedding,
            ranked_prototypes.c.quality_score,
        ).where(ranked_prototypes.c.prototype_rank <= limit)
    )).all()
    prototypes: dict[uuid.UUID, list[np.ndarray]] = defaultdict(list)
    for cluster_id, blob, _quality in prototype_rows:
        prototypes[cluster_id].append(bytes_to_embedding(blob))

    candidate_scores: list[tuple[uuid.UUID, float, int]] = []
    for cluster in clusters:
        vectors = prototypes.get(cluster.id, [])
        if not vectors:
            vectors = [bytes_to_embedding(cluster.centroid_embedding)]
        distances = sorted(cosine_distance(embedding, vector) for vector in vectors)
        best_distance = float(distances[0])
        support = sum(
            distance <= settings.SELFIE_MATCH_THRESHOLD for distance in distances
        )
        candidate_scores.append((cluster.id, best_distance, support))

    match_id, best_distance = choose_selfie_match(
        candidate_scores,
        match_threshold=float(settings.SELFIE_MATCH_THRESHOLD),
        strong_threshold=float(settings.SELFIE_STRONG_MATCH_THRESHOLD),
        runner_up_margin=float(settings.SELFIE_MATCH_MARGIN),
    )
    return match_id, best_distance


# ─────────────────────────────────────────────────────────────────────────────
# Organizer correction
# ─────────────────────────────────────────────────────────────────────────────
async def merge_clusters(
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    db: AsyncSession,
) -> FaceCluster:
    """Merge two clusters and persist the organizer's must-link correction."""
    initial = (await db.execute(
        select(FaceCluster).where(FaceCluster.id.in_([source_id, target_id]))
    )).scalars().all()
    if len(initial) != 2 or initial[0].event_id != initial[1].event_id:
        raise ValueError("Clusters were not found in the same event.")
    event_id = initial[0].event_id
    await lock_event_face_mutation(event_id, db)

    locked = (await db.execute(
        select(FaceCluster)
        .where(FaceCluster.id.in_([source_id, target_id]))
        .with_for_update()
    )).scalars().all()
    by_id = {cluster.id: cluster for cluster in locked}
    source, target = by_id.get(source_id), by_id.get(target_id)
    if source is None or target is None:
        raise ValueError("One or both clusters no longer exist.")
    if source.pipeline_version != target.pipeline_version:
        raise ValueError("Reprocess legacy face groups before merging model versions.")

    detection_rows = (await db.execute(
        select(
            FaceDetection.embedding,
            FaceDetection.quality_score,
            FaceDetection.is_low_quality,
            FaceDetection.manual_group_id,
        ).where(
            FaceDetection.cluster_id.in_([source_id, target_id]),
            FaceDetection.pipeline_version == target.pipeline_version,
        )
    )).all()
    embeddings = [bytes_to_embedding(row.embedding) for row in detection_rows]
    anchor_embeddings = [
        bytes_to_embedding(row.embedding)
        for row in detection_rows
        if not row.is_low_quality
        and float(row.quality_score or 0.0) >= settings.FACE_ANCHOR_QUALITY_THRESHOLD
    ]
    if not embeddings:
        raise ValueError("The selected clusters contain no compatible faces.")

    manual_groups = sorted(
        {row.manual_group_id for row in detection_rows if row.manual_group_id},
        key=str,
    )
    manual_group_id = manual_groups[0] if manual_groups else uuid.uuid4()
    if len(manual_groups) > 1:
        await db.execute(
            update(FaceDetection)
            .where(FaceDetection.manual_group_id.in_(manual_groups[1:]))
            .values(manual_group_id=manual_group_id)
        )

    target.centroid_embedding = embedding_to_bytes(
        _normalised_centroid(anchor_embeddings or embeddings)
    )
    target.member_count = len(embeddings)
    if target.label is None and source.label is not None:
        target.label = source.label
    await db.execute(
        update(FaceDetection)
        .where(FaceDetection.cluster_id.in_([source_id, target_id]))
        .values(cluster_id=target_id, manual_group_id=manual_group_id)
    )
    await db.execute(
        update(SelfieScan)
        .where(SelfieScan.matched_cluster_id == source_id)
        .values(matched_cluster_id=target_id)
    )
    await db.delete(source)
    return target
