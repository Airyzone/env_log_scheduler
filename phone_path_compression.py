"""Adaptive compression for historical phone location records.

The output is intentionally not a fixed one-point-per-ten-minutes sample.
Stationary records can be sparse, while movement, beacon changes, and turns
are retained so that a historical map remains useful.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


Record = Dict[str, Any]


@dataclass(frozen=True)
class CompressionPolicy:
    """Thresholds for adaptive historical path compression."""

    movement_distance_meters: float = 25.0
    turn_min_distance_meters: float = 10.0
    turn_angle_degrees: float = 45.0
    moving_interval: timedelta = timedelta(minutes=10)
    stationary_interval: timedelta = timedelta(minutes=30)


def normalize_beacon_ids(value: Any) -> Tuple[str, ...]:
    """Normalize legacy string/list beacon values into stable unique IDs."""

    values: List[Any]
    if value is None:
        values = []
    elif isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]

    normalized: Set[str] = set()
    for item in values:
        if item is None:
            continue
        if isinstance(item, str):
            normalized.update(
                part.strip() for part in item.split(",") if part.strip()
            )
        else:
            text = str(item).strip()
            if text:
                normalized.add(text)
    return tuple(sorted(normalized))


def _coordinate(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def normalize_record(record: Record) -> Optional[Record]:
    """Return only the fields needed by the compressor, or skip invalid data."""

    uuid = str(record.get("uuid") or "").strip()
    timestamp = record.get("datetime")
    lat = _coordinate(record.get("lat"))
    lon = _coordinate(record.get("lon"))
    if (
        not uuid
        or not isinstance(timestamp, datetime)
        or lat is None
        or lon is None
        or lat == 0.0
        or lon == 0.0
    ):
        return None

    return {
        "_id": record.get("_id"),
        "uuid": uuid,
        "datetime": timestamp,
        "lat": lat,
        "lon": lon,
        "beacons": normalize_beacon_ids(record.get("beacon_id"))
        + normalize_beacon_ids(record.get("beacon_ids")),
    }


def haversine_meters(first: Record, second: Record) -> float:
    radius = 6_371_000.0
    first_lat = math.radians(first["lat"])
    second_lat = math.radians(second["lat"])
    delta_lat = math.radians(second["lat"] - first["lat"])
    delta_lon = math.radians(second["lon"] - first["lon"])
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(first_lat)
        * math.cos(second_lat)
        * math.sin(delta_lon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def bearing_degrees(first: Record, second: Record) -> Optional[float]:
    """Return the initial bearing, or None when the points are coincident."""

    first_lat = math.radians(first["lat"])
    second_lat = math.radians(second["lat"])
    delta_lon = math.radians(second["lon"] - first["lon"])
    if abs(delta_lon) < 1e-12 and abs(second["lat"] - first["lat"]) < 1e-12:
        return None

    y = math.sin(delta_lon) * math.cos(second_lat)
    x = (
        math.cos(first_lat) * math.sin(second_lat)
        - math.sin(first_lat) * math.cos(second_lat) * math.cos(delta_lon)
    )
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_difference(first: float, second: float) -> float:
    return abs((second - first + 180.0) % 360.0 - 180.0)


class AdaptivePhonePathCompressor:
    """Compress one UUID's time-ordered records without fixed resampling."""

    def __init__(self, policy: Optional[CompressionPolicy] = None) -> None:
        self.policy = policy or CompressionPolicy()
        self._uuid: Optional[str] = None
        self._last_raw: Optional[Record] = None
        self._previous_raw: Optional[Record] = None
        self._last_kept: Optional[Record] = None
        self._pending_start: Optional[Record] = None
        self._pending_count = 0
        self._pending_beacons: Set[str] = set()

    def add(self, record: Record) -> Optional[Record]:
        current = normalize_record(record)
        if current is None:
            return None

        if self._uuid is not None and current["uuid"] != self._uuid:
            raise ValueError("AdaptivePhonePathCompressor accepts one UUID at a time")
        self._uuid = current["uuid"]

        if self._last_raw is not None and current["datetime"] < self._last_raw[
            "datetime"
        ]:
            raise ValueError("phone records must be sorted by datetime")

        self._pending_beacons.update(current["beacons"])
        if self._last_kept is None:
            self._last_raw = current
            self._last_kept = current
            self._pending_start = current
            self._pending_count = 1
            output = self._make_output(current)
            self._reset_pending(current)
            return output

        self._pending_count += 1
        should_keep = self._should_keep(current)
        self._previous_raw = self._last_raw
        self._last_raw = current
        if not should_keep:
            return None

        output = self._make_output(current)
        self._last_kept = current
        self._reset_pending(current)
        return output

    def finish(self) -> Optional[Record]:
        """Keep the final point of the stream if it was not already emitted."""

        if self._last_raw is None or self._pending_count == 0:
            return None
        output = self._make_output(self._last_raw)
        self._last_kept = self._last_raw
        self._reset_pending(self._last_raw)
        return output

    def _should_keep(self, current: Record) -> bool:
        assert self._last_kept is not None
        assert self._pending_start is not None

        elapsed = current["datetime"] - self._last_kept["datetime"]
        distance = haversine_meters(self._last_kept, current)
        beacon_changed = bool(
            set(current["beacons"]) - set(self._last_kept["beacons"])
            or set(self._last_kept["beacons"]) - set(current["beacons"])
        )
        if beacon_changed or distance >= self.policy.movement_distance_meters:
            return True

        if elapsed >= self.policy.stationary_interval:
            return True

        if elapsed >= self.policy.moving_interval and distance >= self.policy.turn_min_distance_meters:
            return True

        if self._previous_raw is not None and self._last_raw is not None:
            previous_bearing = bearing_degrees(self._previous_raw, self._last_raw)
            current_bearing = bearing_degrees(self._last_raw, current)
            if previous_bearing is not None and current_bearing is not None:
                if angle_difference(previous_bearing, current_bearing) >= self.policy.turn_angle_degrees:
                    return distance >= self.policy.turn_min_distance_meters

        return False

    def _make_output(self, current: Record) -> Record:
        assert self._pending_start is not None
        output: Record = {
            "uuid": current["uuid"],
            "datetime": current["datetime"],
            "lat": current["lat"],
            "lon": current["lon"],
            "source_count": self._pending_count,
            "source_start_datetime": self._pending_start["datetime"],
            "source_end_datetime": current["datetime"],
            "source_id": current.get("_id"),
        }
        if self._pending_beacons:
            output["beacon_ids"] = sorted(self._pending_beacons)
        return output

    def _reset_pending(self, current: Record) -> None:
        self._pending_start = current
        self._pending_count = 0
        self._pending_beacons = set(current["beacons"])


def compress_records(
    records: Iterable[Record], policy: Optional[CompressionPolicy] = None
) -> List[Record]:
    compressor = AdaptivePhonePathCompressor(policy)
    output: List[Record] = []
    for record in records:
        emitted = compressor.add(record)
        if emitted is not None:
            output.append(emitted)
    final = compressor.finish()
    if final is not None:
        output.append(final)
    return output
