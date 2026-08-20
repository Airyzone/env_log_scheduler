"""Compatibility helpers for the legacy Mongo datetime contract.

The historical ``env`` collections store Taiwan wall-clock values as naive
``datetime`` values.  MongoDB BSON dates do not retain the original timezone,
so existing values must not be shifted or bulk-converted.

Contract for new code:
* a naive value is already a Taiwan wall-clock value and is kept unchanged;
* an aware value is converted to UTC+8 and then made naive before storage or
  querying legacy collections;
* Mongo aggregation/query boundaries use the stored wall-clock value directly;
  do not add another ``+08:00`` conversion to legacy BSON dates.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional


TAIWAN_TZ = timezone(timedelta(hours=8))


def legacy_taiwan_now() -> datetime:
    """Return current Taiwan wall-clock time for legacy Mongo fields."""

    return datetime.now(TAIWAN_TZ).replace(tzinfo=None)


def to_legacy_taiwan_datetime(value: datetime) -> datetime:
    """Normalize an aware/naive datetime without changing legacy semantics."""

    if value.tzinfo is None:
        return value
    return value.astimezone(TAIWAN_TZ).replace(tzinfo=None)


def parse_legacy_taiwan_datetime(value: str) -> datetime:
    """Parse an ISO datetime and return the legacy Taiwan wall-clock value.

    Naive input is interpreted as Taiwan wall-clock time.  ``Z`` and explicit
    offsets are converted to Taiwan before the timezone marker is removed.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError("datetime must be a non-empty ISO string")

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return to_legacy_taiwan_datetime(datetime.fromisoformat(normalized))


def normalize_legacy_taiwan_datetime(value: Any) -> Optional[datetime]:
    """Best-effort version for data-boundary normalization."""

    if isinstance(value, datetime):
        return to_legacy_taiwan_datetime(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return parse_legacy_taiwan_datetime(value)
    except (TypeError, ValueError):
        return None
