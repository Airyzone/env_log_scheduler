import json
import sys
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from unittest.mock import patch

import compress_phone_log


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, item) for item in expected):
                return False
            continue
        if key == "$nor":
            if any(_matches(document, item) for item in expected):
                return False
            continue

        actual = document.get(key)
        if isinstance(expected, dict):
            if "$gte" in expected and not (actual is not None and actual >= expected["$gte"]):
                return False
            if "$gt" in expected and not (actual is not None and actual > expected["$gt"]):
                return False
            if "$lt" in expected and not (actual is not None and actual < expected["$lt"]):
                return False
            if "$lte" in expected and not (actual is not None and actual <= expected["$lte"]):
                return False
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$type" in expected:
                type_name = expected["$type"]
                if type_name == "string" and not isinstance(actual, str):
                    return False
                if type_name == "number" and (
                    isinstance(actual, bool)
                    or not isinstance(actual, (int, float))
                ):
                    return False
            continue
        if actual != expected:
            return False
    return True


class _Cursor(list):
    def batch_size(self, _size):
        return self

    def close(self):
        return None


class _DeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class _Collection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])

    def list_indexes(self):
        return [{"name": "datetime_1", "key": {"datetime": 1}}]

    def create_index(self, *_args, **_kwargs):
        return None

    def find_one(self, query, _projection=None, sort=None, **_kwargs):
        matches = [doc for doc in self.documents if _matches(doc, query)]
        if not matches:
            return None
        if sort:
            field, direction = sort[0]
            matches.sort(key=lambda item: item.get(field), reverse=direction < 0)
        return dict(matches[0])

    def count_documents(self, query, **_kwargs):
        return sum(1 for doc in self.documents if _matches(doc, query))

    def aggregate(self, pipeline, **_kwargs):
        documents = self.documents
        if pipeline and "$match" in pipeline[0]:
            documents = [
                doc for doc in documents if _matches(doc, pipeline[0]["$match"])
            ]

        group = next(
            (stage["$group"] for stage in pipeline if "$group" in stage),
            None,
        )
        if group and "represented" in group:
            return _Cursor([
                {
                    "_id": None,
                    "represented": sum(
                        int(doc.get("source_count") or 0) for doc in documents
                    ),
                }
            ])

        if any("$sort" in stage for stage in pipeline):
            documents = sorted(
                documents,
                key=lambda item: (item.get("datetime"), str(item.get("_id"))),
            )
        return _Cursor([dict(document) for document in documents])

    def bulk_write(self, operations, **_kwargs):
        for operation in operations:
            document = dict(operation._doc["$set"])
            self.documents = [
                item
                for item in self.documents
                if item.get("_id") != document.get("_id")
            ]
            self.documents.append(document)

    def delete_many(self, query, **_kwargs):
        kept = [doc for doc in self.documents if not _matches(doc, query)]
        deleted = len(self.documents) - len(kept)
        self.documents = kept
        return _DeleteResult(deleted)


class _Database:
    def __init__(self, raw_documents=None, compact_documents=None):
        self.collections = {
            "phone_log": _Collection(raw_documents),
            "phone_log_10min": _Collection(compact_documents),
        }

    def __getitem__(self, name):
        return self.collections[name]


class _Admin:
    @staticmethod
    def command(name):
        assert name == "hello"
        return {"isWritablePrimary": True, "setName": "rs0"}


class _Client:
    def __init__(self, raw_documents=None, compact_documents=None):
        self.env = _Database(raw_documents, compact_documents)
        self.admin = _Admin()

    def close(self):
        return None


def _run_main(client, *arguments):
    output = StringIO()
    with patch.object(compress_phone_log.pymongo, "MongoClient", return_value=client):
        with patch.object(sys, "argv", ["compress_phone_log.py", *arguments]):
            with redirect_stdout(output):
                return_code = compress_phone_log.main()
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    return return_code, events


def _valid_record(timestamp, source_id="valid"):
    return {
        "_id": source_id,
        "uuid": "phone-1",
        "datetime": timestamp,
        "lat": 25.033,
        "lon": 121.5654,
    }


def _invalid_record(timestamp, source_id="invalid"):
    return {
        "_id": source_id,
        "uuid": "",
        "datetime": timestamp,
        "lat": 23.0126,
        "lon": 120.2675,
    }


def test_invalid_only_batch_is_retained_and_next_batch_is_processed():
    start = datetime(2021, 6, 30)
    client = _Client(
        raw_documents=[
            _invalid_record(start + compress_phone_log.timedelta(hours=1)),
            _valid_record(
                datetime(2021, 7, 1, 1),
                source_id="valid-next-day",
            ),
        ]
    )

    return_code, events = _run_main(
        client,
        "--start",
        "2021-06-30T00:00:00",
        "--cutoff",
        "2021-07-02T00:00:00",
        "--batch-hours",
        "24",
        "--max-batches",
        "2",
        "--minimum-retention-days",
        "30",
        "--pause-seconds",
        "0",
        "--execute",
    )

    assert return_code == 0
    deleted_events = [event for event in events if event["event"] == "batch_deleted"]
    assert len(deleted_events) == 2
    assert deleted_events[0]["deleted"] == 0
    assert deleted_events[0]["invalid_retained_count"] == 1
    assert deleted_events[1]["deleted"] == 1
    assert len(client.env["phone_log"].documents) == 1
    assert client.env["phone_log"].documents[0]["uuid"] == ""
    assert len(client.env["phone_log_10min"].documents) == 1


def test_existing_compact_target_does_not_block_invalid_remainder():
    start = datetime(2021, 6, 30)
    client = _Client(
        raw_documents=[_invalid_record(start + compress_phone_log.timedelta(hours=1))]
    )
    compacted = {
        "_id": "existing-target",
        "uuid": "phone-1",
        "datetime": start,
        "lat": 25.033,
        "lon": 121.5654,
        "source_count": 1,
    }
    client.env["phone_log_10min"].documents.append(compacted)

    return_code, events = _run_main(
        client,
        "--start",
        "2021-06-30T00:00:00",
        "--cutoff",
        "2021-07-01T00:00:00",
        "--batch-hours",
        "24",
        "--max-batches",
        "1",
        "--minimum-retention-days",
        "30",
        "--pause-seconds",
        "0",
        "--execute",
    )

    assert return_code == 0
    assert not any(event["event"] == "blocked" for event in events)
    deleted_event = next(event for event in events if event["event"] == "batch_deleted")
    assert deleted_event["deleted"] == 0
    assert deleted_event["invalid_retained_count"] == 1
