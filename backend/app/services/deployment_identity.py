"""Non-secret deployment identity helpers for cross-service diagnostics."""
from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Optional

from sqlalchemy.engine import make_url


@lru_cache(maxsize=8)
def database_fingerprint(database_url: Optional[str] = None) -> str:
    """Hash only database host/port/name; credentials never enter the digest."""
    if database_url is None:
        from ..config import get_settings

        database_url = get_settings().DATABASE_URL
    try:
        parsed = make_url(database_url)
        identity = "|".join(
            (
                (parsed.host or "").lower(),
                str(parsed.port or ""),
                (parsed.database or "").lower(),
            )
        )
    except Exception:
        # Still safe and stable enough to make the configuration problem
        # visible without logging the unparseable value itself.
        return "db-unparseable"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"db-{digest}"
