import math
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np


# App settings are intentionally required in production. Pure tests provide
# inert values so importing the algorithm modules never contacts external
# services.
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SUPER_ADMIN_PASSWORD", "test-password")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test",
)
os.environ.setdefault("R2_ACCOUNT_ID", "test")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("R2_BUCKET_NAME", "test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["INSIGHTFACE_MODEL"] = "buffalo_l"
os.environ["FACE_ENABLE_TILING"] = "true"
os.environ["FACE_TILE_TRIGGER_DIM"] = "1600"
os.environ["FACE_PROCESS_MAX_DIM"] = "1920"

from app.services.clustering import (  # noqa: E402
    _bounded_anchor_edges,
    choose_selfie_match,
    choose_incremental_cluster,
    constrained_cluster_labels,
    reuse_clusters_by_overlap,
)
from app.services.ml_pipeline import (  # noqa: E402
    _iter_detection_views,
    bbox_iou,
    detect_and_embed,
    get_ml_runtime_info,
    non_maximum_face_indices,
)


def vector_at_cosine_distance(distance: float) -> np.ndarray:
    """Return a unit 2D vector at an exact cosine distance from [1, 0]."""
    similarity = 1.0 - distance
    return np.asarray(
        [similarity, math.sqrt(max(0.0, 1.0 - similarity * similarity))],
        dtype=np.float32,
    )


class ConstrainedClusteringTests(unittest.TestCase):
    def test_never_merges_two_faces_from_the_same_photo(self):
        first = np.asarray([1.0, 0.0], dtype=np.float32)
        duplicate_identity = vector_at_cosine_distance(0.02)
        supporting_view = vector_at_cosine_distance(0.03)
        labels = constrained_cluster_labels(
            np.vstack([first, duplicate_identity, supporting_view]),
            ["photo-a", "photo-a", "photo-b"],
            merge_threshold=0.45,
            max_cluster_distance=0.52,
        )
        self.assertNotEqual(labels[0], labels[1])
        self.assertTrue(labels[2] in (labels[0], labels[1]))

    def test_merge_threshold_is_strict(self):
        origin = np.asarray([1.0, 0.0], dtype=np.float32)
        accepted = constrained_cluster_labels(
            np.vstack([origin, vector_at_cosine_distance(0.44)]),
            ["a", "b"],
            merge_threshold=0.45,
            max_cluster_distance=0.52,
        )
        rejected = constrained_cluster_labels(
            np.vstack([origin, vector_at_cosine_distance(0.46)]),
            ["a", "b"],
            merge_threshold=0.45,
            max_cluster_distance=0.52,
        )
        self.assertEqual(accepted[0], accepted[1])
        self.assertNotEqual(rejected[0], rejected[1])

    def test_attach_only_faces_use_a_stricter_gate_and_do_not_bridge(self):
        origin = np.asarray([1.0, 0.0], dtype=np.float32)
        strict_match = vector_at_cosine_distance(0.37)
        too_weak = vector_at_cosine_distance(0.40)
        labels = constrained_cluster_labels(
            np.vstack([origin, strict_match, too_weak]),
            ["a", "b", "c"],
            anchor_mask=[True, False, False],
            merge_threshold=0.45,
            attach_threshold=0.38,
            attach_margin=0.05,
        )
        self.assertEqual(labels[0], labels[1])
        self.assertNotEqual(labels[0], labels[2])

    def test_attach_only_face_respects_same_photo_cannot_link(self):
        labels = constrained_cluster_labels(
            np.vstack([
                np.asarray([1.0, 0.0], dtype=np.float32),
                vector_at_cosine_distance(0.10),
            ]),
            ["same-photo", "same-photo"],
            anchor_mask=[True, False],
            attach_threshold=0.38,
        )
        self.assertNotEqual(labels[0], labels[1])

    def test_complete_link_prevents_centroid_chaining(self):
        # The third face is close to the second and to the first-two centroid,
        # but too far from the first face to join the complete-link component.
        vectors = np.asarray([
            [1.0, 0.0],
            [math.cos(math.radians(50)), math.sin(math.radians(50))],
            [math.cos(math.radians(80)), math.sin(math.radians(80))],
        ], dtype=np.float32)
        labels = constrained_cluster_labels(
            vectors,
            ["a", "b", "c"],
            merge_threshold=0.45,
            max_cluster_distance=0.52,
            distance_block_size=2,
            candidate_neighbors=2,
        )
        self.assertNotEqual(labels[0], labels[1])
        self.assertEqual(labels[1], labels[2])

    def test_weak_face_competition_chooses_best_box_not_input_order(self):
        anchor = np.asarray([1.0, 0.0], dtype=np.float32)
        weaker = vector_at_cosine_distance(0.30)
        stronger = vector_at_cosine_distance(0.10)

        weaker_first = constrained_cluster_labels(
            np.vstack([anchor, weaker, stronger]),
            ["anchor-photo", "shared-photo", "shared-photo"],
            anchor_mask=[True, False, False],
            attach_threshold=0.38,
        )
        stronger_first = constrained_cluster_labels(
            np.vstack([anchor, stronger, weaker]),
            ["anchor-photo", "shared-photo", "shared-photo"],
            anchor_mask=[True, False, False],
            attach_threshold=0.38,
        )

        self.assertNotEqual(weaker_first[0], weaker_first[1])
        self.assertEqual(weaker_first[0], weaker_first[2])
        self.assertEqual(stronger_first[0], stronger_first[1])
        self.assertNotEqual(stronger_first[0], stronger_first[2])

    def test_dense_candidate_graph_has_linear_edge_bound(self):
        count = 120
        embeddings = np.repeat(
            np.asarray([[1.0, 0.0]], dtype=np.float32), count, axis=0
        )
        distances, left, right = _bounded_anchor_edges(
            embeddings,
            list(range(count)),
            merge_threshold=0.45,
            block_size=17,
            max_neighbors=4,
        )
        self.assertEqual(distances.shape, left.shape)
        self.assertEqual(left.shape, right.shape)
        self.assertLessEqual(len(distances), count * 4)
        labels = constrained_cluster_labels(
            embeddings,
            [f"photo-{index}" for index in range(count)],
            distance_block_size=17,
            candidate_neighbors=4,
        )
        self.assertEqual(len(set(int(label) for label in labels)), 1)

    def test_manual_merge_survives_later_reclustering(self):
        labels = constrained_cluster_labels(
            np.asarray([[1.0, 0.0], [-1.0, 0.0]], dtype=np.float32),
            ["photo-a", "photo-b"],
            must_link_groups=["organizer-merge", "organizer-merge"],
            merge_threshold=0.10,
        )
        self.assertEqual(labels[0], labels[1])


class IncrementalSelectionTests(unittest.TestCase):
    def test_rejects_centroid_match_that_breaks_complete_link(self):
        first = np.asarray([1.0, 0.0], dtype=np.float32)
        second = np.asarray([
            math.cos(math.radians(50)),
            math.sin(math.radians(50)),
        ], dtype=np.float32)
        incoming = np.asarray([
            math.cos(math.radians(80)),
            math.sin(math.radians(80)),
        ], dtype=np.float32)

        match, _ = choose_incremental_cluster(
            incoming,
            {"person": ([first, second], [first, second])},
            incoming_is_anchor=True,
            merge_threshold=0.45,
            max_cluster_distance=0.52,
            attach_threshold=0.38,
            runner_up_margin=0.05,
        )
        self.assertIsNone(match)

    def test_rejects_ambiguous_weak_attachment(self):
        incoming = np.asarray([1.0, 0.0], dtype=np.float32)
        first = vector_at_cosine_distance(0.30)
        second = vector_at_cosine_distance(0.33)
        match, distance = choose_incremental_cluster(
            incoming,
            {
                "first": ([first], [first]),
                "second": ([second], [second]),
            },
            incoming_is_anchor=False,
            merge_threshold=0.45,
            max_cluster_distance=0.52,
            attach_threshold=0.38,
            runner_up_margin=0.05,
        )
        self.assertIsNone(match)
        self.assertAlmostEqual(distance, 0.30, places=5)

    def test_weak_face_cannot_attach_to_weak_only_seed(self):
        incoming = np.asarray([1.0, 0.0], dtype=np.float32)
        weak_seed = vector_at_cosine_distance(0.10)
        match, _ = choose_incremental_cluster(
            incoming,
            {"weak-only": ([], [weak_seed])},
            incoming_is_anchor=False,
            merge_threshold=0.45,
            max_cluster_distance=0.52,
            attach_threshold=0.38,
            runner_up_margin=0.05,
        )
        self.assertIsNone(match)

    def test_anchor_rescues_weak_seed_only_under_strict_gate(self):
        incoming = np.asarray([1.0, 0.0], dtype=np.float32)
        accepted, _ = choose_incremental_cluster(
            incoming,
            {"weak-only": ([], [vector_at_cosine_distance(0.37)])},
            incoming_is_anchor=True,
            merge_threshold=0.45,
            max_cluster_distance=0.52,
            attach_threshold=0.38,
            runner_up_margin=0.05,
        )
        rejected, _ = choose_incremental_cluster(
            incoming,
            {"weak-only": ([], [vector_at_cosine_distance(0.40)])},
            incoming_is_anchor=True,
            merge_threshold=0.45,
            max_cluster_distance=0.52,
            attach_threshold=0.38,
            runner_up_margin=0.05,
        )
        self.assertEqual(accepted, "weak-only")
        self.assertIsNone(rejected)


class StableIdentityTests(unittest.TestCase):
    def test_reuses_old_cluster_for_majority_overlap(self):
        old_a, old_b = uuid.uuid4(), uuid.uuid4()
        mapping = reuse_clusters_by_overlap(
            [{1, 2, 4}, {3}],
            {old_a: {1, 2}, old_b: {3}},
            min_new_overlap=0.50,
        )
        self.assertEqual(mapping, {0: old_a, 1: old_b})

    def test_does_not_reuse_id_for_tiny_overlap_in_large_new_group(self):
        old_id = uuid.uuid4()
        mapping = reuse_clusters_by_overlap(
            [{1, 2, 3, 4, 5}],
            {old_id: {1}},
            min_new_overlap=0.50,
        )
        self.assertEqual(mapping, {})

    def test_does_not_reuse_id_for_exact_half_overlap(self):
        old_id = uuid.uuid4()
        mapping = reuse_clusters_by_overlap(
            [{1, 2, 3, 4}],
            {old_id: {1, 2}},
            min_new_overlap=0.50,
        )
        self.assertEqual(mapping, {})

    def test_does_not_let_small_split_fragment_take_old_id(self):
        old_id = uuid.uuid4()
        mapping = reuse_clusters_by_overlap(
            [{1, 2}],
            {old_id: {1, 2, 3, 4, 5}},
            min_new_overlap=0.50,
        )
        self.assertEqual(mapping, {})

    def test_reuse_is_deterministic_across_old_mapping_order(self):
        old_a, old_b = uuid.uuid4(), uuid.uuid4()
        new_groups = [{1, 2, 3}, {4, 5, 6}]
        forward = reuse_clusters_by_overlap(
            new_groups,
            {old_a: {1, 2, 3}, old_b: {4, 5, 6}},
        )
        reverse = reuse_clusters_by_overlap(
            new_groups,
            {old_b: {4, 5, 6}, old_a: {1, 2, 3}},
        )
        self.assertEqual(forward, reverse)


class SelfieSelectionTests(unittest.TestCase):
    def test_rejects_ambiguous_top_two_people(self):
        first, second = uuid.uuid4(), uuid.uuid4()
        match, distance = choose_selfie_match(
            [(first, 0.30, 2), (second, 0.34, 2)],
            match_threshold=0.50,
            strong_threshold=0.38,
            runner_up_margin=0.08,
        )
        self.assertIsNone(match)
        self.assertEqual(distance, 0.30)

    def test_moderate_match_needs_two_prototypes(self):
        person = uuid.uuid4()
        rejected, _ = choose_selfie_match(
            [(person, 0.44, 1)],
            match_threshold=0.50,
            strong_threshold=0.38,
            runner_up_margin=0.08,
        )
        accepted, _ = choose_selfie_match(
            [(person, 0.44, 2)],
            match_threshold=0.50,
            strong_threshold=0.38,
            runner_up_margin=0.08,
        )
        self.assertIsNone(rejected)
        self.assertEqual(accepted, person)


class DetectionHelperTests(unittest.TestCase):
    def test_large_image_has_global_plus_four_tiled_views(self):
        image = np.zeros((1700, 1700, 3), dtype=np.uint8)
        views = list(_iter_detection_views(image))
        self.assertEqual(len(views), 5)

    def test_global_iou_dedup_prefers_higher_detail_score(self):
        boxes = [[0, 0, 100, 100], [4, 4, 104, 104], [200, 200, 240, 240]]
        kept = non_maximum_face_indices(boxes, [0.80, 0.95, 0.70], 0.40)
        self.assertEqual(kept, [1, 2])
        self.assertGreater(bbox_iou(boxes[0], boxes[1]), 0.40)

    def test_runtime_metadata_does_not_load_model_by_default(self):
        runtime = get_ml_runtime_info(load_model=False)
        self.assertEqual(runtime["model"], "buffalo_l")
        self.assertIn("pipeline_version", runtime)
        self.assertIn(runtime["device"], {"NOT_LOADED", "CPU", "GPU"})

    def test_30px_confident_face_is_usable_but_not_an_anchor(self):
        embedding = np.zeros(512, dtype=np.float32)
        embedding[0] = 1.0
        detected = SimpleNamespace(
            bbox=np.asarray([20, 20, 50, 50], dtype=np.float32),
            det_score=0.90,
            normed_embedding=embedding,
            pose=np.asarray([0.0, 0.0, 0.0], dtype=np.float32),
        )

        class FakeApp:
            def get(self, _image):
                return [detected]

        image = np.full((100, 100, 3), 127, dtype=np.uint8)
        encoded, buffer = cv2.imencode(".jpg", image)
        self.assertTrue(encoded)
        with patch("app.services.ml_pipeline._get_insightface_app", return_value=FakeApp()):
            faces = detect_and_embed(buffer.tobytes(), "face.jpg")

        self.assertEqual(len(faces), 1)
        self.assertFalse(faces[0].is_low_quality)
        self.assertFalse(faces[0].is_anchor_quality)


if __name__ == "__main__":
    unittest.main()
