#!/usr/bin/env python3
"""
GitHub Copilot - 2025-12-19 15:00:00
建立 log_10min 預聚合資料表（智能版）

此腳本將 log 表的原始資料聚合成 10 分鐘粒度，存入 log_10min 表
"""

import os
import time
import pymongo
from datetime import datetime, timedelta
import argparse
from dotenv import load_dotenv

load_dotenv()

MONGODB_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")


def get_process_status(client, thing_id=None):
    """
    取得各 thing_id 的處理狀態
    """
    log_10min_db = client.env.log_10min

    pipeline = []
    if thing_id:
        pipeline.append({"$match": {"thing_id": thing_id}})

    pipeline.append({
        "$group": {
            "_id": "$thing_id",
            "last_processed": {"$max": "$datetime"},
            "first_processed": {"$min": "$datetime"},
            "count": {"$sum": 1}
        }
    })

    results = list(log_10min_db.aggregate(pipeline))
    return {r["_id"]: {
        "last_processed": r["last_processed"],
        "first_processed": r["first_processed"],
        "count": r["count"]
    } for r in results}


def show_status(client):
    """顯示處理狀態"""
    log_db = client.env.log
    log_10min_db = client.env.log_10min

    print("=" * 60)
    print("log_10min 預聚合表狀態")
    print("=" * 60)

    # 總覽
    log_count = log_db.estimated_document_count()
    log_10min_count = log_10min_db.estimated_document_count()
    print(f"\n原始 log 表: {log_count:,} 筆")
    print(f"預聚合 log_10min 表: {log_10min_count:,} 筆")

    # 各 thing_id 狀態
    status = get_process_status(client)
    all_thing_ids = set(log_db.distinct("thing_id"))
    processed_thing_ids = set(status.keys())
    unprocessed = all_thing_ids - processed_thing_ids

    print(f"\n已處理 thing_id: {len(processed_thing_ids)} 個")
    print(f"未處理 thing_id: {len(unprocessed)} 個")

    if status:
        print("\n最近處理的 5 個 thing_id:")
        sorted_status = sorted(
            status.items(), key=lambda x: x[1]["last_processed"], reverse=True)[:5]
        for tid, info in sorted_status:
            print(
                f"  - {tid}: 最後處理 {info['last_processed'].strftime('%Y-%m-%d %H:%M') if info.get('last_processed') else None}, 共 {info['count']:,} 筆")

    if unprocessed:
        print(f"\n未處理的 thing_id (前 10 個): {list(unprocessed)[:10]}")

    print("=" * 60)


def build_log_10min(thing_id=None, days=None, batch_days=7, force=False, delay=0.1):
    """
    建立預聚合表（智能版）
    """
    client = pymongo.MongoClient(MONGODB_URL)
    log_db = client.env.log
    log_10min_db = client.env.log_10min

    # 建立索引
    log_10min_db.create_index(
        [("thing_id", pymongo.ASCENDING), ("datetime", pymongo.DESCENDING)],
        background=True
    )

    # 取得所有 thing_id
    if thing_id:
        thing_ids = [thing_id]
    else:
        thing_ids = [tid for tid in log_db.distinct("thing_id") if tid is not None]

    # 取得已處理狀態
    process_status = get_process_status(client, thing_id) if not force else {}

    print(f"共 {len(thing_ids)} 個 thing_id")
    if not force:
        print(f"智能模式：將跳過已處理的時間範圍")

    interval_ms = 10 * 60 * 1000  # 10 分鐘
    now = datetime.now()
    total_things_processed = 0
    total_records_inserted = 0

    for idx, tid in enumerate(thing_ids):
        # 決定處理範圍
        status = process_status.get(tid)

        if days:
            # 指定天數模式
            start_datetime = now - timedelta(days=days)
            end_datetime = now
        elif status and not force:
            # 智能模式：從上次處理的時間點開始（往前推 1 天確保完整）
            start_datetime = status["last_processed"] - timedelta(days=1)
            end_datetime = now

            # 如果已經是最新的，跳過
            if (now - status["last_processed"]).total_seconds() < 600:  # 10 分鐘內
                print(f"[{idx+1}/{len(thing_ids)}] thing_id {tid}: 已是最新，跳過")
                continue
        else:
            # 全新處理：找出該 thing_id 最早的資料
            oldest = log_db.find_one(
                {"thing_id": tid},
                sort=[("datetime", 1)]
            )
            if not oldest:
                print(f"[{idx+1}/{len(thing_ids)}] thing_id {tid}: 無資料，跳過")
                continue
            start_datetime = oldest["datetime"]
            end_datetime = now

        print(f"\n[{idx+1}/{len(thing_ids)}] 處理 thing_id: {tid}")
        print(
            f"  時間範圍: {start_datetime.strftime('%Y-%m-%d') if hasattr(start_datetime, 'strftime') else str(start_datetime)} ~ {end_datetime.strftime('%Y-%m-%d') if hasattr(end_datetime, 'strftime') else str(end_datetime)}")

        # 分批處理
        current_start = start_datetime
        thing_inserted = 0

        while current_start < end_datetime:
            current_end = min(
                current_start + timedelta(days=batch_days), end_datetime)

            # 先刪除這個範圍內的舊資料（確保更新）
            log_10min_db.delete_many({
                "thing_id": tid,
                "datetime": {"$gte": current_start, "$lt": current_end}
            })

            # 聚合
            pipeline = [
                {"$match": {
                    "thing_id": tid,
                    "datetime": {"$gte": current_start, "$lt": current_end}
                }},
                {"$addFields": {
                    "timeBucket": {
                        "$subtract": [
                            {"$toLong": "$datetime"},
                            {"$mod": [{"$toLong": "$datetime"}, interval_ms]}
                        ]
                    }
                }},
                {"$group": {
                    "_id": "$timeBucket",
                    "thing_id": {"$first": "$thing_id"},
                    "temperature": {"$avg": "$temperature"},
                    "humidity": {"$avg": "$humidity"},
                    "battery": {"$avg": "$battery"},
                    "rssi": {"$avg": "$rssi"},
                    "count": {"$sum": 1}
                }},
                {"$addFields": {
                    "datetime": {"$toDate": "$_id"}
                }},
                {"$project": {
                    "_id": 0,
                    "thing_id": 1,
                    "datetime": 1,
                    "temperature": 1,
                    "humidity": 1,
                    "battery": 1,
                    "rssi": 1,
                    "count": 1
                }}
            ]

            results = list(log_db.aggregate(pipeline, allowDiskUse=True))

            if results:
                log_10min_db.insert_many(results)
                thing_inserted += len(results)

            print(f"  {current_start.strftime('%Y-%m-%d') if hasattr(current_start, 'strftime') else str(current_start)} ~ {current_end.strftime('%Y-%m-%d') if hasattr(current_end, 'strftime') else str(current_end)}: "
                  f"+{len(results)} 筆")

            if delay > 0:
                time.sleep(delay)

            current_start = current_end

        if thing_inserted > 0:
            total_things_processed += 1
            total_records_inserted += thing_inserted
            print(f"  ✓ thing_id {tid} 完成，共 {thing_inserted} 筆")

    print("\n" + "=" * 50)
    print(f"處理完成！")
    print(f"  處理 thing_id: {total_things_processed} 個")
    print(f"  新增/更新記錄: {total_records_inserted} 筆")
    print(f"  log_10min 表總計: {log_10min_db.count_documents({}):,} 筆")
    print("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="建立 log_10min 預聚合資料表")
    parser.add_argument("--thing_id", type=int, help="只處理特定 thing_id")
    parser.add_argument("--days", type=int, help="只處理最近幾天的資料")
    parser.add_argument("--batch_days", type=int, default=7, help="每批處理幾天")
    parser.add_argument("--delay", type=float, default=0.5, help="每批處理後的間隔秒數 (防止伺服器過載)")
    parser.add_argument("--force", action="store_true", help="強制重新處理")
    parser.add_argument("--status", action="store_true", help="查看處理狀態")

    args = parser.parse_args()
    client = pymongo.MongoClient(MONGODB_URL)

    if args.status:
        show_status(client)
    else:
        build_log_10min(
            thing_id=args.thing_id,
            days=args.days,
            batch_days=args.batch_days,
            force=args.force,
            delay=args.delay
        )
