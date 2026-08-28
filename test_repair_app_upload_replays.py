from datetime import datetime

from repair_app_upload_replays import build_deletion_plan


def _row(row_id, temperature=25.0, detector=False):
    row = {
        "_id": row_id,
        "thing_id": 123,
        "beacon_id": "beacon-1",
        "datetime": datetime(2026, 6, 30, 2, 0),
        "temperature": temperature,
        "humidity": 60.0,
        "battery": 90.0,
        "rssi": -50.0,
        "uuid": "phone-1",
    }
    if detector:
        row.pop("uuid")
        row["detector_id"] = "detector-1"
    return row


def _aggregate(count, temperature=25.0):
    return {
        "count": count,
        "temperature": temperature,
        "humidity": 60.0,
        "battery": 90.0,
        "rssi": -50.0,
    }


def test_plan_removes_only_excess_app_replay_rows() -> None:
    status, details = build_deletion_plan(
        [_row("a"), _row("b"), _row("c")],
        _aggregate(2),
    )

    assert status == "planned"
    assert details["excess"] == 1
    assert details["delete_ids"] == ["c"]


def test_plan_blocks_when_excess_is_not_duplicate_app_data() -> None:
    status, details = build_deletion_plan(
        [_row("a"), _row("b", temperature=26.0)],
        _aggregate(1, temperature=25.0),
    )

    assert status == "blocked"
    assert "not fully explained" in details["reason"]


def test_plan_never_uses_detector_rows_as_delete_candidates() -> None:
    status, details = build_deletion_plan(
        [_row("a", detector=True), _row("b", detector=True), _row("c")],
        _aggregate(2, temperature=25.0),
    )

    assert status == "blocked"
    assert details["duplicate_pool"] == 0
