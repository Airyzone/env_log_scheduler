"""Safely compress historical env.phone_log records.

The command is dry-run by default.  In execute mode it writes adaptive path
points to env.phone_log_10min, verifies source coverage using source_count,
and only then deletes valid source rows from the processed time batch.
Invalid source rows are reported and deliberately retained for a separate
cleanup decision.
"""

import argparse
from datetime import datetime, timedelta
import json
import os
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pymongo
from pymongo import UpdateOne
from pymongo.errors import PyMongoError

from phone_path_compression import (
    AdaptivePhonePathCompressor,
    CompressionPolicy,
    haversine_meters,
    normalize_record,
)


DEFAULT_MONGODB_URL = "mongodb://env.airyzone.com:27017/env?directConnection=true"
RAW_COLLECTION = "phone_log"
COMPACT_COLLECTION = "phone_log_10min"
RAW_DATETIME_INDEX = "datetime_1"
COMPACT_DATETIME_INDEX = "datetime_1"
COMPACT_UUID_DATETIME_INDEX = "uuid_1_datetime_1"
INTERVAL_HOURS = 24


def emit(event: str, **fields: Any) -> None:
    print(
        json.dumps(
            {"event": event, **fields},
            ensure_ascii=False,
            default=lambda value: value.isoformat()
            if isinstance(value, datetime)
            else str(value),
        ),
        flush=True,
    )


def parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "時間格式必須是 ISO 8601，例如 2026-06-29T03:00:00"
        ) from exc
    if parsed.tzinfo is not None:
        raise argparse.ArgumentTypeError(
            "本專案 Mongo 時間使用 naive datetime，請勿附加時區"
        )
    return parsed


def floor_to_batch(value: datetime, batch_hours: int) -> datetime:
    day_start = value.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_hours = int((value - day_start).total_seconds() // 3600)
    batch_start_hour = (elapsed_hours // batch_hours) * batch_hours
    return day_start + timedelta(hours=batch_start_hour)


def ensure_direct_connection(uri: str) -> str:
    """Prevent a replica set's internal 127.0.0.1 address from being followed."""

    parts = urlsplit(uri)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("directConnection", "true")
    path = parts.path or "/env"
    return urlunsplit(
        (parts.scheme, parts.netloc, path, urlencode(query), parts.fragment)
    )


def batch_query(start: datetime, end: datetime) -> Dict[str, Any]:
    return {"datetime": {"$gte": start, "$lt": end}}


def valid_query(start: datetime, end: datetime) -> Dict[str, Any]:
    query = batch_query(start, end)
    query.update(
        {
            "uuid": {"$type": "string", "$ne": ""},
            "lat": {"$type": "number", "$ne": 0},
            "lon": {"$type": "number", "$ne": 0},
        }
    )
    return query


def source_pipeline(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    return [
        {"$match": valid_query(start, end)},
        # Sorting only by datetime lets the existing datetime_1 index narrow
        # the scan. Each UUID keeps chronological order even when UUIDs are
        # interleaved, so the Python compressors can run independently.
        {"$sort": {"datetime": 1, "_id": 1}},
        {
            "$project": {
                "_id": 1,
                "uuid": 1,
                "datetime": 1,
                "lat": 1,
                "lon": 1,
                "beacon_id": 1,
                "beacon_ids": 1,
            }
        },
    ]


def compress_batch(
    raw_collection: Any,
    start: datetime,
    end: datetime,
    policy: CompressionPolicy,
    max_time_ms: int,
) -> Tuple[List[Dict[str, Any]], int, float, float]:
    compressors: Dict[str, AdaptivePhonePathCompressor] = {}
    compacted: List[Dict[str, Any]] = []
    source_valid_count = 0
    source_distance_meters = 0.0
    previous_source_by_uuid: Dict[str, Dict[str, Any]] = {}
    cursor = raw_collection.aggregate(
        source_pipeline(start, end),
        allowDiskUse=True,
        maxTimeMS=max_time_ms,
    ).batch_size(5000)
    try:
        for record in cursor:
            uuid = str(record.get("uuid") or "").strip()
            compressor = compressors.get(uuid)
            if compressor is None:
                compressor = AdaptivePhonePathCompressor(policy)
                compressors[uuid] = compressor
            source_valid_count += 1
            normalized = normalize_record(record)
            if normalized is not None:
                previous_source = previous_source_by_uuid.get(uuid)
                if previous_source is not None:
                    source_distance_meters += haversine_meters(
                        previous_source, normalized
                    )
                previous_source_by_uuid[uuid] = normalized
            output = compressor.add(record)
            if output is not None:
                compacted.append(output)
    finally:
        cursor.close()

    for compressor in compressors.values():
        output = compressor.finish()
        if output is not None:
            compacted.append(output)

    previous_compact_by_uuid: Dict[str, Dict[str, Any]] = {}
    compressed_distance_meters = 0.0
    for output in sorted(
        compacted,
        key=lambda item: (item["uuid"], item["datetime"]),
    ):
        previous_compact = previous_compact_by_uuid.get(output["uuid"])
        if previous_compact is not None:
            compressed_distance_meters += haversine_meters(
                previous_compact, output
            )
        previous_compact_by_uuid[output["uuid"]] = output

    return (
        compacted,
        source_valid_count,
        source_distance_meters,
        compressed_distance_meters,
    )


def target_document(output: Dict[str, Any]) -> Dict[str, Any]:
    source_id = output.get("source_id")
    identity = "|".join(
        (
            str(output["uuid"]),
            output["datetime"].isoformat(),
            str(source_id),
        )
    )
    document = dict(output)
    document["_id"] = identity
    document["compression_version"] = 1
    document["compression_mode"] = "adaptive_movement_turn_beacon"
    return document


def represented_count(collection: Any, start: datetime, end: datetime) -> int:
    rows = list(
        collection.aggregate(
            [
                {"$match": batch_query(start, end)},
                {
                    "$group": {
                        "_id": None,
                        "represented": {
                            "$sum": {"$ifNull": ["$source_count", 0]}
                        },
                    }
                },
            ],
            allowDiskUse=True,
        )
    )
    return int(rows[0]["represented"]) if rows else 0


def write_compacted(
    collection: Any,
    outputs: Iterable[Dict[str, Any]],
    batch_size: int = 500,
) -> int:
    documents = [target_document(output) for output in outputs]
    written = 0
    for offset in range(0, len(documents), batch_size):
        batch = documents[offset : offset + batch_size]
        operations = [
            UpdateOne({"_id": document["_id"]}, {"$set": document}, upsert=True)
            for document in batch
        ]
        if operations:
            collection.bulk_write(operations, ordered=False)
            written += len(operations)
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="安全分批壓縮與清理歷史 phone_log"
    )
    parser.add_argument(
        "--cutoff",
        required=True,
        type=parse_datetime,
        help="只處理此時間以前的資料，例如 2026-07-20T00:00:00",
    )
    parser.add_argument(
        "--start",
        type=parse_datetime,
        help="指定 dry-run/手動批次起點；未提供時從最舊 raw 批次開始",
    )
    parser.add_argument(
        "--batch-hours",
        type=int,
        default=INTERVAL_HOURS,
        help="每批時間範圍，預設 24 小時",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=1,
        help="本次最多處理幾批，預設只處理 1 批",
    )
    parser.add_argument(
        "--minimum-retention-days",
        type=int,
        default=30,
        help="cutoff 至少要保留幾天，預設 30 天",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=2.0,
        help="每批成功後暫停秒數",
    )
    parser.add_argument(
        "--max-time-ms",
        type=int,
        default=120000,
        help="單次 Mongo 查詢最長時間，預設 120 秒",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="實際寫入 phone_log_10min 並刪除已驗證的 raw rows",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.batch_hours <= 0 or 24 % args.batch_hours != 0:
        raise SystemExit("--batch-hours 必須是 24 的正整數因數，例如 1、6、12、24")
    if args.max_batches <= 0:
        raise SystemExit("--max-batches 必須大於 0")
    if args.minimum_retention_days < 30:
        raise SystemExit("--minimum-retention-days 不得小於 30 天")
    if args.start is not None and args.start >= args.cutoff:
        raise SystemExit("--start 必須早於 --cutoff")

    latest_allowed_cutoff = datetime.now() - timedelta(
        days=args.minimum_retention_days
    )
    if args.cutoff > latest_allowed_cutoff:
        raise SystemExit(
            "cutoff 太新："
            f"至少必須保留 {args.minimum_retention_days} 天，"
            f"目前最晚允許 {latest_allowed_cutoff.isoformat()}"
        )

    mongodb_url = ensure_direct_connection(
        os.environ.get("MONGODB_URL", DEFAULT_MONGODB_URL)
    )
    client = pymongo.MongoClient(
        mongodb_url,
        serverSelectionTimeoutMS=10000,
        appname="phone-log-compressor",
    )
    try:
        hello = client.admin.command("hello")
        if not hello.get("isWritablePrimary") and args.execute:
            raise SystemExit("目前連線節點不是 writable primary，停止清理")

        db = client.env
        raw_collection = db[RAW_COLLECTION]
        compact_collection = db[COMPACT_COLLECTION]
        indexes = {index["name"]: index for index in raw_collection.list_indexes()}
        if RAW_DATETIME_INDEX not in indexes:
            raise SystemExit(
                f"找不到預期的 raw phone_log 索引 {RAW_DATETIME_INDEX}，停止處理"
            )

        if args.execute:
            compact_collection.create_index(
                [("uuid", pymongo.ASCENDING), ("datetime", pymongo.ASCENDING)],
                name=COMPACT_UUID_DATETIME_INDEX,
            )
            compact_collection.create_index(
                [("datetime", pymongo.ASCENDING)],
                name=COMPACT_DATETIME_INDEX,
            )

        emit(
            "preflight",
            mode="execute" if args.execute else "dry-run",
            cutoff=args.cutoff,
            batch_hours=args.batch_hours,
            max_batches=args.max_batches,
            minimum_retention_days=args.minimum_retention_days,
            start=args.start,
            replica_set=hello.get("setName"),
            compact_collection=COMPACT_COLLECTION,
        )

        processed_batches = 0
        deleted_total = 0
        compacted_total = 0
        policy = CompressionPolicy()
        next_batch_start = (
            floor_to_batch(args.start, args.batch_hours)
            if args.start is not None
            else None
        )

        while processed_batches < args.max_batches:
            if next_batch_start is not None and next_batch_start >= args.cutoff:
                emit(
                    "complete",
                    processed_batches=processed_batches,
                    compacted_total=compacted_total,
                    deleted_total=deleted_total,
                )
                return 0
            if next_batch_start is None:
                oldest = raw_collection.find_one(
                    {"datetime": {"$lt": args.cutoff}},
                    {"_id": 0, "datetime": 1},
                    sort=[("datetime", pymongo.ASCENDING)],
                    hint=RAW_DATETIME_INDEX,
                    max_time_ms=args.max_time_ms,
                )
                if not oldest:
                    emit(
                        "complete",
                        processed_batches=processed_batches,
                        compacted_total=compacted_total,
                        deleted_total=deleted_total,
                    )
                    return 0

                oldest_datetime = oldest.get("datetime")
                if not isinstance(oldest_datetime, datetime):
                    emit("blocked", reason="oldest datetime is not a BSON date")
                    return 2
                batch_start = floor_to_batch(oldest_datetime, args.batch_hours)
            else:
                batch_start = next_batch_start
            batch_end = min(
                batch_start + timedelta(hours=args.batch_hours), args.cutoff
            )
            raw_query = batch_query(batch_start, batch_end)
            valid_source_query = valid_query(batch_start, batch_end)
            raw_count = raw_collection.count_documents(
                raw_query,
                hint=RAW_DATETIME_INDEX,
                maxTimeMS=args.max_time_ms,
            )
            valid_count = raw_collection.count_documents(
                valid_source_query,
                hint=RAW_DATETIME_INDEX,
                maxTimeMS=args.max_time_ms,
            )
            invalid_count = raw_count - valid_count
            (
                compacted,
                source_valid_count,
                source_distance_meters,
                compressed_distance_meters,
            ) = compress_batch(
                raw_collection,
                batch_start,
                batch_end,
                policy,
                args.max_time_ms,
            )
            represented = sum(
                int(output.get("source_count") or 0) for output in compacted
            )
            target_count_options: Dict[str, Any] = {
                "maxTimeMS": args.max_time_ms,
            }
            if args.execute:
                target_count_options["hint"] = COMPACT_DATETIME_INDEX
            existing_target_count = compact_collection.count_documents(
                raw_query,
                **target_count_options,
            )
            coverage_matches = (
                valid_count == source_valid_count == represented
                and invalid_count >= 0
            )

            emit(
                "batch_audit",
                batch=processed_batches + 1,
                start=batch_start,
                end=batch_end,
                raw_count=raw_count,
                valid_source_count=valid_count,
                compressed_point_count=len(compacted),
                represented_count=represented,
                invalid_count=invalid_count,
                existing_target_count=existing_target_count,
                coverage_matches=coverage_matches,
                source_distance_meters=round(source_distance_meters, 2),
                compressed_distance_meters=round(compressed_distance_meters, 2),
                compressed_distance_ratio=round(
                    compressed_distance_meters / source_distance_meters, 4
                )
                if source_distance_meters > 0
                else None,
            )

            if not coverage_matches:
                emit(
                    "blocked",
                    reason="raw valid count 與 compressor source_count 不一致",
                    start=batch_start,
                    end=batch_end,
                )
                return 3
            if not args.execute:
                emit(
                    "dry_run_complete",
                    next_start=batch_start,
                    next_end=batch_end,
                    deletable_count=valid_count,
                    invalid_retained_count=invalid_count,
                )
                return 0
            # A previous successful run may already have compacted the valid
            # rows in this batch, while invalid rows remain intentionally in
            # raw. If valid rows are present and the target already exists,
            # keep the original safety block; an empty compacted result can
            # safely advance past an invalid-only remainder batch.
            if existing_target_count and compacted:
                emit(
                    "blocked",
                    reason="compact target 該時間批次已有資料，避免覆蓋或重複刪除",
                    existing_target_count=existing_target_count,
                )
                return 5

            written = write_compacted(compact_collection, compacted)
            compacted_total += written
            if compacted:
                target_count = compact_collection.count_documents(
                    raw_query,
                    hint=COMPACT_DATETIME_INDEX,
                    maxTimeMS=args.max_time_ms,
                )
                target_represented = represented_count(
                    compact_collection, batch_start, batch_end
                )
                if target_count != len(compacted) or target_represented != valid_count:
                    emit(
                        "blocked",
                        reason="compact target 寫入後覆蓋率驗證失敗",
                        target_count=target_count,
                        expected_target_count=len(compacted),
                        target_represented=target_represented,
                        expected_represented=valid_count,
                    )
                    return 6

            delete_result = raw_collection.delete_many(
                valid_source_query,
                hint=RAW_DATETIME_INDEX,
                comment=(
                    "phone-log-compressor "
                    f"{batch_start.isoformat()}..{batch_end.isoformat()}"
                ),
            )
            remaining = raw_collection.count_documents(
                valid_source_query,
                hint=RAW_DATETIME_INDEX,
                maxTimeMS=args.max_time_ms,
            )
            if remaining != 0 or delete_result.deleted_count != valid_count:
                emit(
                    "blocked",
                    reason="raw delete 後驗證不一致",
                    expected_deleted=valid_count,
                    deleted=delete_result.deleted_count,
                    remaining=remaining,
                )
                return 7

            processed_batches += 1
            deleted_total += delete_result.deleted_count
            next_batch_start = batch_end
            emit(
                "batch_deleted",
                batch=processed_batches,
                start=batch_start,
                end=batch_end,
                compacted=written,
                deleted=delete_result.deleted_count,
                deleted_total=deleted_total,
                invalid_retained_count=invalid_count,
            )
            if processed_batches < args.max_batches and args.pause_seconds > 0:
                time.sleep(args.pause_seconds)

        emit(
            "run_limit_reached",
            processed_batches=processed_batches,
            compacted_total=compacted_total,
            deleted_total=deleted_total,
        )
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        emit(
            "interrupted",
            warning=(
                "Mongo write/delete 可能在 client 中斷後繼續完成；"
                "重新執行前必須先查核 compact target 與 raw 剩餘筆數"
            ),
        )
        sys.exit(130)
    except PyMongoError as exc:
        emit("mongo_error", error=str(exc))
        sys.exit(10)
