"""Deterministic app-upload telemetry keys shared by maintenance tooling."""

import hashlib
import json
import math
from datetime import datetime
from numbers import Number
from typing import Any, Dict, Optional, cast


APP_UPLOAD_DEDUPE_FIELD = "_app_upload_dedupe_key"
APP_UPLOAD_DEDUPE_VERSION = 1


def _canonical_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S.%f")
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Number):
        numeric = float(cast(Any, value))
        if math.isfinite(numeric):
            return format(numeric, ".17g")
    return str(value).strip()


def build_app_upload_dedupe_key(
    *,
    uuid: Any,
    thing_id: Any,
    beacon_id: Any,
    item_datetime: Any,
    temperature: Any,
    humidity: Any,
    battery: Any,
    rssi: Any,
    lat: Any,
    lon: Any,
    event_id: Optional[Any] = None,
) -> str:
    """Match the backend key for new event IDs and legacy payload replay."""

    normalized_event_id = _canonical_value(event_id)
    payload: Dict[str, Any]
    if isinstance(normalized_event_id, str) and normalized_event_id:
        payload = {
            "version": APP_UPLOAD_DEDUPE_VERSION,
            "source": "app_upload",
            "uuid": _canonical_value(uuid),
            "event_id": normalized_event_id,
        }
    else:
        payload = {
            "version": APP_UPLOAD_DEDUPE_VERSION,
            "source": "app_upload",
            "uuid": _canonical_value(uuid),
            "thing_id": _canonical_value(thing_id),
            "beacon_id": _canonical_value(beacon_id),
            "datetime": _canonical_value(item_datetime),
            "temperature": _canonical_value(temperature),
            "humidity": _canonical_value(humidity),
            "battery": _canonical_value(battery),
            "rssi": _canonical_value(rssi),
            "lat": _canonical_value(lat),
            "lon": _canonical_value(lon),
        }

    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
