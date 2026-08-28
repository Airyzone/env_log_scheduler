#!/usr/bin/env python3
"""Repair bounded app-upload replay excess without rebuilding aggregates.

The normal raw-log pruner intentionally stops at a coverage mismatch.  This
tool handles the narrower, proven case where the raw side has extra app-upload
rows that are exact replay duplicates and the existing ``log_10min`` count is
the intended target.

Safety rules:
* an explicit thing-id list and an aligned time range are required;
* the default is read-only dry-run;
* every candidate must be explainable by app-upload duplicate rows;
* the planned post-delete count and metric averages must still match the
  existing aggregate document;
* execute mode requires an exact range confirmation and archives rows before
  deleting their original ``_id`` values;
* detector rows and non-duplicate shortfalls are never deleted.
"""

import argparse
import json
import os
import sys
import uuid as uuid_module
from datetime import datetime, timedelta
from math import isclose
from numbers import Number
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, cast

import pymongo
from dotenv import load_dotenv
from pymongo.errors import PyMongoError

from log_dedupe import APP_UPLOAD_DEDUPE_FIELD, build_app_upload_dedupe_key
from legacy_datetime import legacy_taiwan_now, parse_legacy_taiwan_datetime


DEFAULT_MONGODB_URL = "mongodb://localhost:27017"
BUCKET_MINUTES = 10
MAX_RANGE_DAYS = 7
METRIC_FIELDS = ("temperature", "humidity", "battery", "rssi")
APP_SOURCE_FIELD = "uuid"


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def emit(event: str, **fields: Any) -> None:
    print(
        json.dumps(
            {"event": event, **fields},
            ensure_ascii=False,
            default=_json_default,
        ),
        flush=True,
    )


def parse_datetime(value: str) -> datetime:
    try:
        return parse_legacy_taiwan_datetime(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "時間格式必須是 ISO 8601，例如 2026-06-30T00:00:00"
        ) from exc


def _bucket_start(value: datetime) -> datetime:
    return value.replace(
        minute=(value.minute // BUCKET_MINUTES) * BUCKET_MINUTES,
        second=0,
        microsecond=0,
    )


def _is_aligned(value: datetime) -> bool:
    return (
        value == _bucket_start(value)
        and value.second == 0
        and value.microsecond == 0
    )


def _is_app_upload(document: Dict[str, Any]) -> bool:
    source = document.get(APP_SOURCE_FIELD)
    return bool(str(source).strip()) and "detector_id" not in document


def _id_sort_key(value: Any) -> Tuple[int, Any, str]:
    generation_time = getattr(value, "generation_time", None)
    if generation_time is not None:
        return (0, generation_time.timestamp(), str(value))
    return (1, type(value).__name__, str(value))


def _id_token(value: Any) -> str:
    return f"{type(value).__name__}:{value!s}"


def _document_key(document: Dict[str, Any]) -> str:
    # Historical repair deliberately uses the full telemetry signature.  A
    # client event_id is suitable for preventing future retries, but it must
    # not by itself authorize deletion if a buggy client reused that ID.
    return build_app_upload_dedupe_key(
        uuid=document.get("uuid"),
        thing_id=document.get("thing_id"),
        beacon_id=document.get("beacon_id"),
        item_datetime=document.get("datetime"),
        temperature=document.get("temperature"),
        humidity=document.get("humidity"),
        battery=document.get("battery"),
        rssi=document.get("rssi"),
        lat=document.get("lat"),
        lon=document.get("lon"),
        event_id=None,
    )


def _average(documents: Iterable[Dict[str, Any]], field: str) -> Optional[float]:
    values: List[float] = []
    for document in documents:
        value = document.get(field)
        if isinstance(value, Number) and not isinstance(value, bool):
            numeric = float(cast(Any, value))
            if numeric == numeric and numeric not in (float("inf"), float("-inf")):
                values.append(numeric)
    if not values:
        return None
    return sum(values) / len(values)


def _metrics_match(
    documents: Sequence[Dict[str, Any]],
    aggregate: Dict[str, Any],
) -> bool:
    for field in METRIC_FIELDS:
        actual = _average(documents, field)
        expected = aggregate.get(field)
        if actual is None or expected is None:
            if actual is not None or expected is not None:
                return False
            continue
        try:
            expected_value = float(cast(Any, expected))
        except (TypeError, ValueError):
            return False
        if not isclose(actual, expected_value, rel_tol=1e-9, abs_tol=1e-6):
            return False
    return True


def build_deletion_plan(
    raw_documents: Sequence[Dict[str, Any]],
    aggregate: Optional[Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    """Return ``clean``, ``planned`` or ``blocked`` plus audit details."""

    raw_count = len(raw_documents)
    if aggregate is None:
        return "blocked", {
            "reason": "missing aggregate document",
            "raw_count": raw_count,
        }

    try:
        represented_count = int(aggregate.get("count", 0))
    except (TypeError, ValueError):
        return "blocked", {"reason": "aggregate count is invalid"}
    if represented_count < 0:
        return "blocked", {"reason": "aggregate count is negative"}

    if raw_count == represented_count:
        return "clean", {
            "raw_count": raw_count,
            "represented_count": represented_count,
        }
    if raw_count < represented_count:
        return "blocked", {
            "reason": "raw shortfall; never delete",
            "raw_count": raw_count,
            "represented_count": represented_count,
        }

    excess = raw_count - represented_count
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for document in raw_documents:
        if not _is_app_upload(document):
            continue
        document_id = document.get("_id")
        if document_id is None:
            return "blocked", {"reason": "candidate row has no _id"}
        groups.setdefault(_document_key(document), []).append(document)

    duplicate_pool: List[Dict[str, Any]] = []
    for documents in groups.values():
        ordered = sorted(documents, key=lambda item: _id_sort_key(item["_id"]))
        duplicate_pool.extend(ordered[1:])

    if len(duplicate_pool) < excess:
        return "blocked", {
            "reason": "coverage excess is not fully explained by app duplicates",
            "raw_count": raw_count,
            "represented_count": represented_count,
            "excess": excess,
            "duplicate_pool": len(duplicate_pool),
        }

    delete_documents = sorted(
        duplicate_pool,
        key=lambda item: _id_sort_key(item["_id"]),
        reverse=True,
    )[:excess]
    delete_tokens = {_id_token(item["_id"]) for item in delete_documents}
    remaining = [
        document
        for document in raw_documents
        if _id_token(document.get("_id")) not in delete_tokens
    ]

    if len(remaining) != represented_count:
        return "blocked", {
            "reason": "planned remaining count is not aggregate count",
            "raw_count": raw_count,
            "represented_count": represented_count,
            "planned_remaining": len(remaining),
        }
    if not _metrics_match(remaining, aggregate):
        return "blocked", {
            "reason": "planned deletion changes aggregate metric averages",
            "raw_count": raw_count,
            "represented_count": represented_count,
            "planned_remaining": len(remaining),
        }

    return "planned", {
        "raw_count": raw_count,
        "represented_count": represented_count,
        "excess": excess,
        "duplicate_pool": len(duplicate_pool),
        "delete_ids": [item["_id"] for item in delete_documents],
        "delete_id_sample": [str(item["_id"]) for item in delete_documents[:5]],
    }


def _aggregate_counts(
    raw_log: Any,
    thing_ids: Sequence[int],
    start: datetime,
    end: datetime,
    max_time_ms: int,
) -> Dict[Tuple[int, datetime], int]:
    pipeline = [
        {
            "$match": {
                "thing_id": {"$in": list(thing_ids)},
                "datetime": {"$gte": start, "$lt": end},
            }
        },
        {
            "$addFields": {
                "timeBucket": {
                    "$subtract": [
                        {"$toLong": "$datetime"},
                        {
                            "$mod": [
                                {"$toLong": "$datetime"},
                                BUCKET_MINUTES * 60 * 1000,
                            ]
                        },
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": {"thing_id": "$thing_id", "bucket": "$timeBucket"},
                "raw_count": {"$sum": 1},
            }
        },
    ]
    result: Dict[Tuple[int, datetime], int] = {}
    for row in raw_log.aggregate(
        pipeline,
        allowDiskUse=True,
        maxTimeMS=max_time_ms,
    ):
        key = row.get("_id") or {}
        bucket_ms = key.get("bucket")
        if bucket_ms is None:
            continue
        bucket = datetime.utcfromtimestamp(float(bucket_ms) / 1000.0)
        result[(int(key["thing_id"]), bucket)] = int(row["raw_count"])
    return result


def _find_aggregate_documents(
    log_10min: Any,
    thing_ids: Sequence[int],
    start: datetime,
    end: datetime,
    max_time_ms: int,
) -> Dict[Tuple[int, datetime], List[Dict[str, Any]]]:
    projection = {
        "_id": 1,
        "thing_id": 1,
        "datetime": 1,
        "count": 1,
        **{field: 1 for field in METRIC_FIELDS},
    }
    result: Dict[Tuple[int, datetime], List[Dict[str, Any]]] = {}
    cursor = log_10min.find(
        {
            "thing_id": {"$in": list(thing_ids)},
            "datetime": {"$gte": start, "$lt": end},
        },
        projection,
    )
    if hasattr(cursor, "max_time_ms"):
        cursor = cursor.max_time_ms(max_time_ms)
    for document in cursor:
        key = (int(document["thing_id"]), document["datetime"])
        result.setdefault(key, []).append(document)
    return result


def _find_raw_documents(
    raw_log: Any,
    thing_id: int,
    start: datetime,
    end: datetime,
    max_time_ms: int,
) -> List[Dict[str, Any]]:
    projection = {"_id": 1, "thing_id": 1, "beacon_id": 1, "datetime": 1}
    for field in (
        "temperature",
        "humidity",
        "battery",
        "rssi",
        "uuid",
        "detector_id",
        "lat",
        "lon",
        "event_id",
        APP_UPLOAD_DEDUPE_FIELD,
    ):
        projection[field] = 1
    cursor = raw_log.find(
        {
            "thing_id": thing_id,
            "datetime": {"$gte": start, "$lt": end},
        },
        projection,
    )
    if hasattr(cursor, "max_time_ms"):
        cursor = cursor.max_time_ms(max_time_ms)
    return list(cursor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="限定範圍修復 app_upload raw replay excess"
    )
    parser.add_argument("--thing-id", type=int, action="append", required=True)
    parser.add_argument("--start", required=True, type=parse_datetime)
    parser.add_argument("--end", required=True, type=parse_datetime)
    parser.add_argument("--max-time-ms", type=int, default=120000)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="先封存候選 rows，再刪除精確 _id；未提供時只做 dry-run",
    )
    parser.add_argument(
        "--confirm-range",
        help="execute 必須精確等於 START..END，例如 2026-06-30T00:00:00..2026-07-01T00:00:00",
    )
    parser.add_argument(
        "--archive-collection",
        default="log_repair_archive",
        help="execute 前封存候選資料的 collection，預設 log_repair_archive",
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.max_time_ms <= 0:
        raise SystemExit("--max-time-ms 必須大於 0")
    if args.start >= args.end:
        raise SystemExit("--start 必須早於 --end")
    if not _is_aligned(args.start) or not _is_aligned(args.end):
        raise SystemExit("--start/--end 必須對齊 10 分鐘 bucket")
    if args.end - args.start > timedelta(days=MAX_RANGE_DAYS):
        raise SystemExit(f"一次最多只能處理 {MAX_RANGE_DAYS} 天")
    expected = f"{args.start.isoformat()}..{args.end.isoformat()}"
    if args.execute and args.confirm_range != expected:
        raise SystemExit(
            "execute 必須提供完全相同的 --confirm-range: " + expected
        )


def _archive_documents(
    archive: Any,
    documents_by_id: Dict[str, Dict[str, Any]],
    run_id: str,
    bucket_start: datetime,
    bucket_end: datetime,
) -> int:
    archive_documents: List[Dict[str, Any]] = []
    archived_at = legacy_taiwan_now()
    for document in documents_by_id.values():
        archived = dict(document)
        archived.pop("_id", None)
        archived.update(
            {
                "_repair_original_id": document["_id"],
                "_repair_run_id": run_id,
                "_repair_archived_at": archived_at,
                "_repair_bucket_start": bucket_start,
                "_repair_bucket_end": bucket_end,
                "_repair_reason": "app_upload_exact_replay_excess",
            }
        )
        archive_documents.append(archived)
    if not archive_documents:
        return 0
    result = archive.insert_many(archive_documents, ordered=True)
    return len(result.inserted_ids)


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()
    _validate_args(args)

    mongodb_url = os.environ.get("MONGODB_URL", DEFAULT_MONGODB_URL)
    client = pymongo.MongoClient(
        mongodb_url,
        serverSelectionTimeoutMS=10000,
        appname="app-upload-replay-repair",
    )
    hello = client.admin.command("hello")
    if args.execute and not hello.get("isWritablePrimary"):
        raise SystemExit("execute 需要 writable primary，停止修復")

    db = client.env
    raw_log = db.log
    log_10min = db.log_10min
    thing_ids = sorted(set(args.thing_id))
    emit(
        "preflight",
        mode="execute" if args.execute else "dry-run",
        thing_ids=thing_ids,
        start=args.start,
        end=args.end,
        max_time_ms=args.max_time_ms,
        archive_collection=args.archive_collection if args.execute else None,
        replica_set=hello.get("setName"),
    )

    raw_counts = _aggregate_counts(
        raw_log, thing_ids, args.start, args.end, args.max_time_ms
    )
    aggregate_documents = _find_aggregate_documents(
        log_10min, thing_ids, args.start, args.end, args.max_time_ms
    )

    keys = set(raw_counts) | set(aggregate_documents)
    plans: List[Dict[str, Any]] = []
    blocked = 0
    clean = 0
    for thing_id, bucket_start in sorted(keys):
        bucket_end = bucket_start + timedelta(minutes=BUCKET_MINUTES)
        raw_documents = _find_raw_documents(
            raw_log,
            thing_id,
            bucket_start,
            bucket_end,
            args.max_time_ms,
        )
        aggregate_list = aggregate_documents.get((thing_id, bucket_start), [])
        aggregate = aggregate_list[0] if len(aggregate_list) == 1 else None
        if len(aggregate_list) > 1:
            status, details = "blocked", {
                "reason": "duplicate aggregate key",
                "aggregate_documents": len(aggregate_list),
            }
        else:
            status, details = build_deletion_plan(raw_documents, aggregate)

        if status == "clean":
            clean += 1
            continue
        if status == "blocked":
            blocked += 1
            emit(
                "bucket_blocked",
                thing_id=thing_id,
                start=bucket_start,
                end=bucket_end,
                raw_count=len(raw_documents),
                **details,
            )
            continue

        plan = {
            "thing_id": thing_id,
            "start": bucket_start,
            "end": bucket_end,
            "raw_documents": raw_documents,
            "aggregate": aggregate,
            **details,
        }
        plans.append(plan)
        emit(
            "bucket_plan",
            thing_id=thing_id,
            start=bucket_start,
            end=bucket_end,
            raw_count=details["raw_count"],
            represented_count=details["represented_count"],
            excess=details["excess"],
            duplicate_pool=details["duplicate_pool"],
            delete_count=len(details["delete_ids"]),
            delete_id_sample=details["delete_id_sample"],
        )

    emit(
        "audit_complete",
        clean_buckets=clean,
        planned_buckets=len(plans),
        planned_delete_count=sum(len(plan["delete_ids"]) for plan in plans),
        blocked_buckets=blocked,
    )
    if blocked:
        return 3
    if not args.execute or not plans:
        return 0

    archive = db[args.archive_collection]
    run_id = uuid_module.uuid4().hex
    for plan in plans:
        delete_ids = plan["delete_ids"]
        delete_tokens = {_id_token(value) for value in delete_ids}
        documents_by_id = {
            _id_token(document["_id"]): document
            for document in plan["raw_documents"]
            if _id_token(document["_id"]) in delete_tokens
        }
        archived_count = _archive_documents(
            archive,
            documents_by_id,
            run_id,
            plan["start"],
            plan["end"],
        )
        if archived_count != len(delete_ids):
            emit(
                "blocked",
                reason="archive count mismatch; no delete issued for this bucket",
                thing_id=plan["thing_id"],
                start=plan["start"],
                expected_archive_count=len(delete_ids),
                archived_count=archived_count,
            )
            return 4

        delete_result = raw_log.delete_many({"_id": {"$in": delete_ids}})
        if delete_result.deleted_count != len(delete_ids):
            emit(
                "blocked",
                reason="delete count mismatch; prior buckets may already be repaired",
                thing_id=plan["thing_id"],
                start=plan["start"],
                expected_deleted=len(delete_ids),
                deleted=delete_result.deleted_count,
            )
            return 4

        remaining = _find_raw_documents(
            raw_log,
            plan["thing_id"],
            plan["start"],
            plan["end"],
            args.max_time_ms,
        )
        if len(remaining) != plan["represented_count"] or not _metrics_match(
            remaining, plan["aggregate"]
        ):
            emit(
                "blocked",
                reason="post-delete coverage or metric verification failed",
                thing_id=plan["thing_id"],
                start=plan["start"],
                expected_remaining=plan["represented_count"],
                remaining=len(remaining),
            )
            return 4

        emit(
            "bucket_repaired",
            thing_id=plan["thing_id"],
            start=plan["start"],
            end=plan["end"],
            archived=archived_count,
            deleted=delete_result.deleted_count,
            remaining=len(remaining),
            run_id=run_id,
        )

    emit("complete", repaired_buckets=len(plans), run_id=run_id)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        emit("interrupted")
        sys.exit(130)
    except PyMongoError as exc:
        emit("mongo_error", error=str(exc))
        sys.exit(10)
