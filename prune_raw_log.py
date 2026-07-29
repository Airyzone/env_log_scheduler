#!/usr/bin/env python3
"""
安全分批清理 MongoDB env.log 的舊 raw log。

安全原則：
1. 預設只做 dry-run，必須明確傳入 --execute 才會刪除。
2. cutoff 必須明確指定，且不得侵入最低保留天數。
3. 每個批次先比對 raw 筆數與 log_10min.count 代表的原始筆數。
4. 只有 thing_id 為 null 的舊資料允許沒有 log_10min 對應資料。
5. 任一批次驗證不一致就停止，不會跳過後繼資料。
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pymongo
from dotenv import load_dotenv


DEFAULT_MONGODB_URL = "mongodb://localhost:27017"
RAW_DATETIME_INDEX = "datetime_1"


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def emit(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    print(json.dumps(payload, ensure_ascii=False, default=_json_default), flush=True)


def parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "時間格式必須是 ISO 8601，例如 2026-06-29T03:00:00"
        ) from exc
    if parsed.tzinfo is not None:
        raise argparse.ArgumentTypeError(
            "本專案 Mongo 時間使用台灣牆上時間的 naive datetime，請勿附加時區"
        )
    return parsed


def floor_to_batch(value: datetime, batch_hours: int) -> datetime:
    day_start = value.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_hours = int((value - day_start).total_seconds() // 3600)
    batch_start_hour = (elapsed_hours // batch_hours) * batch_hours
    return day_start + timedelta(hours=batch_start_hour)


def load_daily_aggregate_counts(
    log_10min: pymongo.collection.Collection,
    cutoff: datetime,
    max_time_ms: int,
) -> Dict[str, int]:
    pipeline = [
        {"$match": {"datetime": {"$lt": cutoff}}},
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$datetime",
                    }
                },
                "represented": {"$sum": {"$ifNull": ["$count", 0]}},
            }
        },
    ]
    result = log_10min.aggregate(
        pipeline,
        allowDiskUse=True,
        maxTimeMS=max_time_ms,
    )
    return {row["_id"]: int(row["represented"]) for row in result}


def aggregate_count_for_range(
    log_10min: pymongo.collection.Collection,
    start: datetime,
    end: datetime,
    max_time_ms: int,
) -> int:
    result = list(
        log_10min.aggregate(
            [
                {"$match": {"datetime": {"$gte": start, "$lt": end}}},
                {
                    "$group": {
                        "_id": None,
                        "represented": {
                            "$sum": {"$ifNull": ["$count", 0]}
                        },
                    }
                },
            ],
            allowDiskUse=True,
            maxTimeMS=max_time_ms,
        )
    )
    return int(result[0]["represented"]) if result else 0


def expected_aggregate_count(
    daily_counts: Dict[str, int],
    log_10min: pymongo.collection.Collection,
    start: datetime,
    end: datetime,
    max_time_ms: int,
) -> int:
    starts_at_midnight = (
        start.hour == 0
        and start.minute == 0
        and start.second == 0
        and start.microsecond == 0
    )
    ends_at_midnight = (
        end.hour == 0
        and end.minute == 0
        and end.second == 0
        and end.microsecond == 0
    )
    duration_days = (end - start).total_seconds() / 86400
    if (
        starts_at_midnight
        and ends_at_midnight
        and duration_days.is_integer()
    ):
        represented = 0
        current_day = start
        while current_day < end:
            represented += daily_counts.get(
                current_day.strftime("%Y-%m-%d"),
                0,
            )
            current_day += timedelta(days=1)
        return represented
    return aggregate_count_for_range(log_10min, start, end, max_time_ms)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="安全分批清理已由 log_10min 涵蓋的舊 raw log"
    )
    parser.add_argument(
        "--cutoff",
        required=True,
        type=parse_datetime,
        help="只刪除此時間以前的資料，例如 2026-06-29T03:00:00",
    )
    parser.add_argument(
        "--batch-hours",
        type=int,
        default=24,
        help="每批時間範圍，預設 24 小時；可用 168 表示 7 天",
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
        help="單次唯讀驗證最長時間，預設 120 秒",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="實際執行刪除；未提供時只做 dry-run",
    )
    return parser


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()

    valid_batch_hours = (
        args.batch_hours > 0
        and (
            24 % args.batch_hours == 0
            or args.batch_hours % 24 == 0
        )
    )
    if not valid_batch_hours:
        raise SystemExit(
            "--batch-hours 必須是 24 的因數或倍數，例如 6、24、168"
        )
    if args.max_batches <= 0:
        raise SystemExit("--max-batches 必須大於 0")
    if args.minimum_retention_days < 7:
        raise SystemExit("--minimum-retention-days 不得小於原設計的 7 天")

    now = datetime.now()
    latest_allowed_cutoff = now - timedelta(
        days=args.minimum_retention_days
    )
    if args.cutoff > latest_allowed_cutoff:
        raise SystemExit(
            "cutoff 太新："
            f"至少必須保留 {args.minimum_retention_days} 天，"
            f"目前最晚允許 {latest_allowed_cutoff.isoformat()}"
        )

    mongodb_url = os.environ.get("MONGODB_URL", DEFAULT_MONGODB_URL)
    client = pymongo.MongoClient(
        mongodb_url,
        serverSelectionTimeoutMS=10000,
        appname="raw-log-pruner",
    )
    hello = client.admin.command("hello")
    if not hello.get("isWritablePrimary"):
        raise SystemExit("目前連線節點不是 writable primary，停止清理")

    db = client.env
    raw_log = db.log
    log_10min = db.log_10min

    indexes = {index["name"]: index for index in raw_log.list_indexes()}
    datetime_index = indexes.get(RAW_DATETIME_INDEX)
    if not datetime_index or datetime_index.get("key") != {"datetime": 1}:
        raise SystemExit(
            f"找不到預期的 raw log 索引 {RAW_DATETIME_INDEX}，停止清理"
        )

    emit(
        "preflight",
        mode="execute" if args.execute else "dry-run",
        cutoff=args.cutoff,
        batch_hours=args.batch_hours,
        max_batches=args.max_batches,
        minimum_retention_days=args.minimum_retention_days,
        replica_set=hello.get("setName"),
    )

    aggregate_counts = load_daily_aggregate_counts(
        log_10min,
        args.cutoff,
        args.max_time_ms,
    )
    emit("aggregate_audit_loaded", days=len(aggregate_counts))

    processed_batches = 0
    deleted_total = 0

    while processed_batches < args.max_batches:
        oldest = raw_log.find_one(
            {"datetime": {"$lt": args.cutoff}},
            {"_id": 0, "datetime": 1},
            sort=[("datetime", pymongo.ASCENDING)],
            hint=RAW_DATETIME_INDEX,
        )
        if not oldest:
            emit(
                "complete",
                processed_batches=processed_batches,
                deleted_total=deleted_total,
            )
            return 0

        oldest_datetime = oldest.get("datetime")
        if not isinstance(oldest_datetime, datetime):
            emit("blocked", reason="oldest datetime is not a BSON date")
            return 2

        batch_start = floor_to_batch(oldest_datetime, args.batch_hours)
        batch_end = min(
            batch_start + timedelta(hours=args.batch_hours),
            args.cutoff,
        )
        query = {
            "datetime": {
                "$gte": batch_start,
                "$lt": batch_end,
            }
        }

        raw_count = raw_log.count_documents(
            query,
            hint=RAW_DATETIME_INDEX,
            maxTimeMS=args.max_time_ms,
        )
        null_thing_count = raw_log.count_documents(
            {
                "thing_id": None,
                "datetime": {
                    "$gte": batch_start,
                    "$lt": batch_end,
                },
            },
            hint="thing_id_1_datetime_-1",
            maxTimeMS=args.max_time_ms,
        )
        represented_count = expected_aggregate_count(
            aggregate_counts,
            log_10min,
            batch_start,
            batch_end,
            args.max_time_ms,
        )
        coverage_matches = (
            raw_count == represented_count + null_thing_count
        )

        emit(
            "batch_audit",
            batch=processed_batches + 1,
            start=batch_start,
            end=batch_end,
            raw_count=raw_count,
            represented_count=represented_count,
            null_thing_count=null_thing_count,
            coverage_matches=coverage_matches,
        )

        if not coverage_matches:
            emit(
                "blocked",
                reason="raw 與 log_10min 代表筆數不一致",
                start=batch_start,
                end=batch_end,
            )
            return 3

        if not args.execute:
            emit(
                "dry_run_complete",
                next_start=batch_start,
                next_end=batch_end,
                deletable_count=raw_count,
            )
            return 0

        delete_result = raw_log.delete_many(
            query,
            hint=RAW_DATETIME_INDEX,
            comment=(
                "raw-log-pruner "
                f"{batch_start.isoformat()}..{batch_end.isoformat()}"
            ),
        )
        remaining = raw_log.count_documents(
            query,
            hint=RAW_DATETIME_INDEX,
            maxTimeMS=args.max_time_ms,
        )
        if remaining != 0 or delete_result.deleted_count != raw_count:
            emit(
                "blocked",
                reason="刪除後驗證不一致",
                expected_deleted=raw_count,
                deleted=delete_result.deleted_count,
                remaining=remaining,
            )
            return 4

        processed_batches += 1
        deleted_total += delete_result.deleted_count
        emit(
            "batch_deleted",
            batch=processed_batches,
            start=batch_start,
            end=batch_end,
            deleted=delete_result.deleted_count,
            deleted_total=deleted_total,
        )

        if processed_batches < args.max_batches and args.pause_seconds > 0:
            time.sleep(args.pause_seconds)

    emit(
        "run_limit_reached",
        processed_batches=processed_batches,
        deleted_total=deleted_total,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        emit(
            "interrupted",
            warning=(
                "Mongo delete 可能在 client 中斷後繼續完成；"
                "重新執行前必須先查核目前最舊資料與該批剩餘筆數"
            ),
        )
        sys.exit(130)
    except pymongo.errors.PyMongoError as exc:
        emit("mongo_error", error=str(exc))
        sys.exit(10)
