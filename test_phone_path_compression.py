from datetime import datetime, timedelta

from phone_path_compression import (
    AdaptivePhonePathCompressor,
    CompressionPolicy,
    compress_records,
)


def _record(timestamp: datetime, lat: float = 25.0330, **extra):
    return {
        "_id": f"source-{timestamp.isoformat()}",
        "uuid": "phone-1",
        "datetime": timestamp,
        "lat": lat,
        "lon": 121.5654,
        **extra,
    }


def test_stationary_records_are_sparse_but_source_coverage_is_exact():
    start = datetime(2026, 8, 19, 0, 0, 0)
    records = [_record(start + timedelta(minutes=10 * i)) for i in range(7)]

    compressed = compress_records(records)

    assert [item["datetime"] for item in compressed] == [
        start,
        start + timedelta(minutes=30),
        start + timedelta(minutes=60),
    ]
    assert sum(item["source_count"] for item in compressed) == len(records)


def test_movement_is_kept_even_before_stationary_interval():
    start = datetime(2026, 8, 19, 1, 0, 0)
    records = [
        _record(start, lat=25.0330),
        _record(start + timedelta(minutes=5), lat=25.0334),
        _record(start + timedelta(minutes=10), lat=25.0338),
    ]

    compressed = compress_records(records)

    assert len(compressed) == 3
    assert sum(item["source_count"] for item in compressed) == len(records)


def test_beacon_change_is_kept_at_the_same_location():
    start = datetime(2026, 8, 19, 2, 0, 0)
    records = [
        _record(start, beacon_id="beacon-a"),
        _record(start + timedelta(minutes=5), beacon_id="beacon-b"),
    ]

    compressed = compress_records(records)

    assert len(compressed) == 2
    assert set(compressed[1]["beacon_ids"]) == {"beacon-a", "beacon-b"}
    assert sum(item["source_count"] for item in compressed) == len(records)


def test_turn_is_kept_when_distance_is_below_full_movement_threshold():
    policy = CompressionPolicy(
        movement_distance_meters=100.0,
        turn_min_distance_meters=5.0,
        turn_angle_degrees=30.0,
    )
    start = datetime(2026, 8, 19, 3, 0, 0)
    records = [
        _record(start, lat=25.0330, lon=121.5654),
        _record(start + timedelta(minutes=2), lat=25.0332, lon=121.5654),
        _record(start + timedelta(minutes=4), lat=25.0332, lon=121.5657),
    ]

    compressed = compress_records(records, policy)

    assert len(compressed) == 2
    assert compressed[-1]["datetime"] == start + timedelta(minutes=4)
    assert sum(item["source_count"] for item in compressed) == len(records)


def test_invalid_records_are_not_represented():
    start = datetime(2026, 8, 19, 4, 0, 0)
    records = [
        _record(start),
        _record(start + timedelta(minutes=1), lat=0.0),
        {"uuid": "phone-1", "datetime": start + timedelta(minutes=2)},
    ]

    compressed = compress_records(records)

    assert len(compressed) == 1
    assert sum(item["source_count"] for item in compressed) == 1


def test_compressor_rejects_out_of_order_records():
    compressor = AdaptivePhonePathCompressor()
    start = datetime(2026, 8, 19, 5, 0, 0)
    compressor.add(_record(start))

    try:
        compressor.add(_record(start - timedelta(minutes=1)))
    except ValueError as error:
        assert "sorted" in str(error)
    else:
        raise AssertionError("out-of-order records must be rejected")
