"""Guardrails for selecting the identity-bearing face in a selfie."""
from __future__ import annotations

from collections.abc import Sequence


class SelfieQualityError(ValueError):
    """Raised when a selfie cannot be matched safely."""


def _face_area(face) -> int:
    x1, y1, x2, y2 = face.bbox
    return max(0, x2 - x1) * max(0, y2 - y1)


def select_selfie_face(faces: Sequence):
    """
    Return the dominant usable face and reject genuinely ambiguous selfies.

    Tiny background faces are ignored, but a second similarly-sized face is
    rejected so a group selfie cannot silently search for the wrong person.
    """
    if not faces:
        raise SelfieQualityError(
            "No face detected. Use a clear, front-facing selfie in good light."
        )

    usable = [face for face in faces if not face.is_low_quality]
    if not usable:
        raise SelfieQualityError(
            "The detected face is too small or unclear. Move closer and try again."
        )

    ranked = sorted(
        usable,
        key=lambda face: (face.quality_score, _face_area(face)),
        reverse=True,
    )
    best = ranked[0]
    best_area = max(1, _face_area(best))
    ambiguous = [
        face
        for face in ranked[1:]
        if _face_area(face) >= best_area * 0.40
        and face.quality_score >= best.quality_score * 0.70
    ]
    if ambiguous:
        raise SelfieQualityError(
            "More than one prominent face was detected. Take a selfie with only you in frame."
        )
    return best
