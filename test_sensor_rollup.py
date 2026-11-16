from datetime import datetime
import pytest
from sensor_rollup import floor_bucket, write_rollups


class Collection:
    def __init__(self, rows):
        self.rows = rows
        self.operations = []

    def find(self, query):
        return iter(self.rows)

    def bulk_write(self, operations, **kwargs):
        self.operations.extend(operations)


def test_rollup_preserves_complete_history_when_raw_is_partial_or_missing():
    t = datetime(2026, 8, 1, 8)
    other = datetime(2026, 8, 1, 9)
    db = Collection([{'datetime': t, 'count': 8}, {'datetime': other, 'count': 3}])
    assert write_rollups(db, 1, t, other, [{'datetime': t, 'count': 2}]) == (0, 2)
    assert not db.operations


def test_late_upload_updates_whole_bucket_without_delete_first():
    t = datetime(2026, 8, 1, 8)
    db = Collection([{'datetime': t, 'count': 8}])
    assert write_rollups(db, 1, t, t, [{'datetime': t, 'count': 9}]) == (1, 0)
    assert db.operations[0]._doc['$set']['count'] == 9
    assert floor_bucket(datetime(2026, 8, 1, 8, 13, 27)) == datetime(2026, 8, 1, 8, 10)


def test_duplicate_bucket_blocks_update_and_pruning():
    t = datetime(2026, 8, 1, 8)
    db = Collection([{'datetime': t, 'count': 1}] * 2)
    with pytest.raises(ValueError, match='重複'):
        write_rollups(db, 1, t, t, [])
