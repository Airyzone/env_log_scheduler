import json
import sys
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from unittest.mock import patch

import prune_raw_log


def _matches(document, query):
    for key, expected in query.items():
        actual = document.get(key)
        if isinstance(expected, dict):
            if "$gte" in expected and not (
                actual is not None and actual >= expected["$gte"]
            ):
                return False
            if "$lt" in expected and not (
                actual is not None and actual < expected["$lt"]
            ):
                return False
            if actual != expected.get("$eq", actual):
                return False
            continue
        if expected is None:
            if actual is not None:
                return False
        elif actual != expected:
            return False
    return True


class _DeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class _Collection:
    def __init__(self, documents):
        self.documents = list(documents)

    def list_indexes(self):
        return [{"name": "datetime_1", "key": {"datetime": 1}}]

    def find_one(self, query, _projection=None, sort=None, **_kwargs):
        matches = [
            document for document in self.documents if _matches(document, query)
        ]
        if sort:
            field, direction = sort[0]
            matches.sort(
                key=lambda document: document.get(field),
                reverse=direction < 0,
            )
        return dict(matches[0]) if matches else None

    def count_documents(self, query, **_kwargs):
        return sum(_matches(document, query) for document in self.documents)

    def delete_many(self, query, **_kwargs):
        kept = [
            document
            for document in self.documents
            if not _matches(document, query)
        ]
        deleted_count = len(self.documents) - len(kept)
        self.documents = kept
        return _DeleteResult(deleted_count)


class _Database:
    def __init__(self, raw_documents):
        self.log = _Collection(raw_documents)
        self.log_10min = _Collection([])


class _Admin:
    @staticmethod
    def command(name):
        assert name == "hello"
        return {"isWritablePrimary": True, "setName": "rs0"}


class _Client:
    def __init__(self, raw_documents):
        self.env = _Database(raw_documents)
        self.admin = _Admin()

    def close(self):
        return None


def _run_main(client, *arguments):
    output = StringIO()
    with patch.object(prune_raw_log.pymongo, "MongoClient", return_value=client):
        with patch.object(
            prune_raw_log,
            "load_daily_aggregate_counts",
            return_value={"2026-06-29": 1, "2026-06-30": 1},
        ):
            with patch.object(
                sys,
                "argv",
                ["prune_raw_log.py", *arguments],
            ):
                with redirect_stdout(output):
                    return_code = prune_raw_log.main()
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    return return_code, events


def _raw_documents():
    return [
        {"_id": "mismatch-1", "thing_id": 1, "datetime": datetime(2026, 6, 29, 1)},
        {"_id": "mismatch-2", "thing_id": 1, "datetime": datetime(2026, 6, 29, 2)},
        {"_id": "matched", "thing_id": 1, "datetime": datetime(2026, 6, 30, 1)},
    ]


def _common_arguments():
    return (
        "--cutoff",
        "2026-07-02T00:00:00",
        "--batch-hours",
        "24",
        "--max-batches",
        "1",
        "--minimum-retention-days",
        "30",
        "--pause-seconds",
        "0",
    )


def test_mismatch_still_stops_by_default():
    client = _Client(_raw_documents())

    return_code, events = _run_main(client, *_common_arguments())

    assert return_code == 3
    assert any(event["event"] == "blocked" for event in events)
    assert len(client.env.log.documents) == 3


def test_continue_on_mismatch_retains_bad_bucket_and_deletes_next_safe_bucket():
    client = _Client(_raw_documents())

    return_code, events = _run_main(
        client,
        *_common_arguments(),
        "--max-scanned-batches",
        "2",
        "--continue-on-mismatch",
        "--execute",
    )

    assert return_code == 0
    skipped = [event for event in events if event["event"] == "batch_skipped"]
    deleted = [event for event in events if event["event"] == "batch_deleted"]
    assert len(skipped) == 1
    assert skipped[0]["retained_count"] == 2
    assert len(deleted) == 1
    assert deleted[0]["deleted"] == 1
    assert {document["_id"] for document in client.env.log.documents} == {
        "mismatch-1",
        "mismatch-2",
    }
