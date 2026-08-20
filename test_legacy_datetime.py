from datetime import datetime, timezone

from legacy_datetime import (
    legacy_taiwan_now,
    normalize_legacy_taiwan_datetime,
    parse_legacy_taiwan_datetime,
    to_legacy_taiwan_datetime,
)


def test_naive_values_are_preserved_as_legacy_wall_clock() -> None:
    value = datetime(2026, 8, 20, 3, 4, 5)

    assert to_legacy_taiwan_datetime(value) == value
    assert parse_legacy_taiwan_datetime("2026-08-20T03:04:05") == value


def test_aware_values_are_converted_to_taiwan_before_storage() -> None:
    value = datetime(2026, 8, 19, 19, 4, 5, tzinfo=timezone.utc)

    assert to_legacy_taiwan_datetime(value) == datetime(2026, 8, 20, 3, 4, 5)
    assert parse_legacy_taiwan_datetime("2026-08-19T19:04:05Z") == datetime(
        2026, 8, 20, 3, 4, 5
    )


def test_normalizer_keeps_invalid_boundary_values_out() -> None:
    assert normalize_legacy_taiwan_datetime("not-a-datetime") is None
    assert normalize_legacy_taiwan_datetime(None) is None


def test_now_returns_naive_taiwan_wall_clock() -> None:
    assert legacy_taiwan_now().tzinfo is None
