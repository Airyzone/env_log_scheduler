#!/usr/bin/env python3
"""
GitHub Copilot - 2026-01-09
建立 trace_log 軌跡資料表 (高效能回補版)

此腳本用於將原始 log 表轉換為 trace_log 軌跡表。

時間契約：既有 Mongo datetime 是台灣牆上時間的 naive 值；手動回補也
必須使用同一個儲存時鐘，不可依賴主機的 local timezone。
優化點：
1. 針對單一裝置 (thing_id) 進行批次查詢，避免全表掃描 O(N*M)。
2. 快取 Thing 和 Detector 的 Metadata，減少資料庫讀取。
3. 支援斷點續傳與 Batch 處理。
"""

import os
import time
import pymongo
from datetime import datetime, timedelta
import argparse
from dotenv import load_dotenv
from legacy_datetime import legacy_taiwan_now

load_dotenv()

MONGODB_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")

# 快取字典
CACHE_THING_NAME = {}
CACHE_DETECTOR_NAME = {}


def load_metadata_cache(client):
    """
    預先載入所有 Thing 和 Detector 的名稱到記憶體
    """
    print("正在載入 Metadata 快取...")
    
    # 載入 Thing Name
    db = client.env
    things = list(db.thing.find({}, {"thing_id": 1, "beacon_id": 1, "profile.name": 1}))
    for t in things:
        tid = t.get("thing_id")
        bid = t.get("beacon_id")
        name = t.get("profile", {}).get("name", "Unknown")
        
        if tid:
            CACHE_THING_NAME[tid] = name
            # 也可以用 beacon_id 查 thing_id (如果需要)
            
    # 載入 Detector Name
    detectors = list(db.detector.find({}, {"detector_id": 1, "profile.name": 1}))
    for d in detectors:
        did = d.get("detector_id")
        name = d.get("profile", {}).get("name", "Unknown")
        if did:
            CACHE_DETECTOR_NAME[did] = name
            
    print(f"快取載入完成: {len(CACHE_THING_NAME)} 個裝置, {len(CACHE_DETECTOR_NAME)} 個感測器")


def get_thing_name(thing_id):
    return CACHE_THING_NAME.get(thing_id, "Unknown")


def get_detector_name(detector_id):
    return CACHE_DETECTOR_NAME.get(detector_id, "Unknown")


def get_process_status(client, collection_name, thing_id=None):
    """
    取得各 thing_id 在 trace_log 的最新進度
    """
    trace_db = client.env[collection_name]
    pipeline = []
    if thing_id:
        pipeline.append({"$match": {"thing_id": thing_id}})

    pipeline.append({
        "$group": {
            "_id": "$thing_id",
            "last_processed": {"$max": "$leave"},  # 使用離開時間作為進度
            "count": {"$sum": 1}
        }
    })

    results = list(trace_db.aggregate(pipeline))
    return {r["_id"]: {
        "last_processed": r["last_processed"],
        "count": r["count"]
    } for r in results}


def process_thing_logs(client, thing_id, beacon_id, start_time, end_time):
    """
    處理單一裝置在指定時間範圍內的 Logs，轉換為 Trace Sessions
    """
    log_db = client.env.log
    
    # 1. 查詢該裝置的所有原始 Log
    # 注意：trace_log 原邏輯是 beacon_id 匹配，且 detector_id 或 uuid 存在
    query = {
        "beacon_id": beacon_id,
        "datetime": {"$gte": start_time, "$lt": end_time}
    }
    
    # 依時間排序
    cursor = log_db.find(query).sort("datetime", pymongo.ASCENDING)
    logs = list(cursor)
    
    if not logs:
        return []

    # 2. 轉換邏輯 (Session 切割)
    # 2. 轉換邏輯 (Session 切割) - 兩階段處理 (符合 Legacy trace_log.py 行為)
    
    # Phase 1: 產生 Raw Segments (只要換 Detector 或 Timeout 就切斷)
    raw_sessions = []
    current_session = None
    TIMEOUT = timedelta(minutes=10)
    
    for log in logs:
        log_time = log['datetime']
        
        # 決定 log 的有效 detector_id
        det_id = log.get('detector_id')
        is_phone = False
        
        if not det_id and log.get('uuid'):
            det_id = log.get('uuid')
            is_phone = True
            
        if not det_id:
            continue
            
        # 檢查是否能延續上一個 Segment (嚴格連續)
        if current_session:
            is_same_detector = (current_session['detector_id'] == det_id)
            time_diff = log_time - current_session['leave']
            
            # 若 Detector 不同，或是時間斷掉，或是跨日 -> 切斷
            is_same_day = (log_time.date() == current_session['enter'].date())
            
            if is_same_detector and time_diff < TIMEOUT and is_same_day:
                current_session['leave'] = log_time
            else:
                # 實施方案 B: 若是因為跨日而切斷，且時間還算連續，則對齊 midnight
                if is_same_detector and time_diff <= TIMEOUT and not is_same_day:
                    # 補齊舊日到 23:59:59
                    current_session['leave'] = current_session['enter'].replace(hour=23, minute=59, second=59, microsecond=0)
                    raw_sessions.append(current_session)
                    # 新日從 00:00:00 開始
                    print(f"  [Midnight Split] {current_session['date'].strftime('%Y-%m-%d')} 補齊至 23:59:59")
                    
                    current_session = {
                        "thing_id": thing_id,
                        "beacon_id": beacon_id,
                        "thing_name": get_thing_name(thing_id),
                        "detector_id": det_id,
                        "detector_name": get_detector_name(det_id) if not is_phone else "",
                        "date": datetime(log_time.year, log_time.month, log_time.day),
                        "enter": log_time.replace(hour=0, minute=0, second=0, microsecond=0),
                        "leave": log_time,
                    }
                else:
                    # 真正的結束或是切換 Detector
                    raw_sessions.append(current_session)
                    current_session = None
        
        # 建立新 Segment
        if current_session is None:
            current_session = {
                "thing_id": thing_id,
                "beacon_id": beacon_id,
                "thing_name": get_thing_name(thing_id),
                "detector_id": det_id,
                "detector_name": get_detector_name(det_id) if not is_phone else "",
                "date": datetime(log_time.year, log_time.month, log_time.day),
                "enter": log_time,
                "leave": log_time,
            }
            
    if current_session:
        raw_sessions.append(current_session)
        
    if not raw_sessions:
        return []

    # Phase 2: Rescan Buffer (處理共存/Coexistence) - Legacy Logic
    # 允許 A -> B -> A 的情況下，兩個 A 合併成一個長 Session
    final_sessions = []
    final_sessions.append(raw_sessions[0])
    
    for i in range(1, len(raw_sessions)):
        current_segment = raw_sessions[i]
        is_new = True
        
        # 往前搜尋是否有同 Detector 的 Session 可以合併
        # (Legacy 邏輯：反向搜尋 final_sessions)
        for j in range(len(final_sessions)-1, -1, -1):
            target_session = final_sessions[j]
            
            if current_segment['detector_id'] == target_session['detector_id']:
                # 檢查時間差 (用 current.enter - target.leave)
                time_delta = current_segment['enter'] - target_session['leave']
                is_same_day = (current_segment['enter'].date() == target_session['enter'].date())
                
                if timedelta(minutes=0) <= time_delta <= TIMEOUT:
                    if is_same_day:
                        # 同一天：直接合併
                        target_session['leave'] = current_segment['leave']
                        is_new = False
                        break 
                    else:
                        # 跨日且連續：兩邊補齊到午夜 (方案 B)
                        target_session['leave'] = target_session['enter'].replace(hour=23, minute=59, second=59, microsecond=0)
                        current_segment['enter'] = current_segment['enter'].replace(hour=0, minute=0, second=0, microsecond=0)
                        print(f"  [Midnight Stretch] 對齊 {target_session['date'].strftime('%Y-%m-%d')} 與 {current_segment['date'].strftime('%Y-%m-%d')}")
                        # 依然是新紀錄，但已對齊
                        is_new = True
                        break
                else: 
                     is_new = True
                     break
        
        if is_new:
            final_sessions.append(current_segment)
            
    return final_sessions


def build_trace_log(thing_id=None, days=None, batch_days=30, force=False, delay=0.1, end_date=None, collection_name="trace_log"):
    client = pymongo.MongoClient(MONGODB_URL)
    log_db = client.env.log
    trace_db = client.env[collection_name]
    thing_db = client.env.thing
    
    # 0. 載入快取
    load_metadata_cache(client)
    
    # 1. 建立索引 (如果沒有的話)
    trace_db.create_index([("thing_id", 1), ("date", 1)])
    trace_db.create_index([("detector_id", 1), ("date", 1)])
    
    # 2. 決定要處理的裝置列表
    target_things = []
    
    if thing_id:
        t = thing_db.find_one({"thing_id": thing_id})
        if t:
            target_things.append(t)
    else:
        # 找出所有有 beacon_id 的裝置
        target_things = list(thing_db.find({"beacon_id": {"$exists": True, "$ne": ""}}))

    # 3. 取得目前進度
    status_map = get_process_status(client, collection_name) if not force else {}
    
    print(f"共有 {len(target_things)} 個裝置需處理")
    now = legacy_taiwan_now()
    
    total_sessions = 0
    
    for idx, t in enumerate(target_things):
        tid = t['thing_id']
        bid = t['beacon_id']
        tname = t.get('profile', {}).get('name', 'Unknown')
        
        # 決定時間範圍
        if days:
            start_dt = now - timedelta(days=days)
            end_dt = now
        elif tid in status_map and not force:
            last_processed = status_map[tid]['last_processed']
            # 從上次結束前 1 天開始重跑 (處理跨日或邊界 session)
            start_dt = last_processed - timedelta(days=1)
            end_dt = now
            
            if (now - last_processed).total_seconds() < 600:
                print(f"[{idx+1}/{len(target_things)}] {tname} ({tid}): 已更新，跳過")
                continue
        else:
            # 全新或強制：找 Log 裡該 Beacon 最早出現的時間
            first_log = log_db.find_one({"beacon_id": bid}, sort=[("datetime", 1)])
            if not first_log:
                print(f"[{idx+1}/{len(target_things)}] {tname} ({tid}): 無 Log 資料，跳過")
                continue
            start_dt = first_log['datetime']
            end_dt = now

        # 如果有指定結束日期，覆蓋 end_dt
        if end_date:
            try:
                target_end = datetime.strptime(end_date, "%Y-%m-%d")
                if target_end < end_dt:
                    end_dt = target_end
            except ValueError:
                print(f"日期格式錯誤: {end_date}，請使用 YYYY-MM-DD")
                return

        # 若起始時間已超過結束時間，跳過
        if start_dt >= end_dt:
             print(f"[{idx+1}/{len(target_things)}] {tname} ({tid}): 範圍不需要處理 ({start_dt.date()} >= {end_dt.date()})，跳過")
             continue

            
        print(f"\n[{idx+1}/{len(target_things)}] 處理 {tname} (ID: {tid}, Beacon: {bid})")
        print(f"  範圍: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}")
        
        # 分批處理
        curr = start_dt
        dev_sessions = 0
        
        while curr < end_dt:
            next_hop = min(curr + timedelta(days=batch_days), end_dt)
            
            # 1. 清除該時段舊資料 (重跑機制)
            # 注意：這裡 delete 條件要謹慎，避免刪錯
            # trace_log 有 'enter' 和 'leave'，我們用 'enter' 作為區間判斷
            trace_db.delete_many({
                "thing_id": tid,
                "enter": {"$gte": curr, "$lt": next_hop}
            })
            
            # 2. 計算 Sessions
            sessions = process_thing_logs(client, tid, bid, curr, next_hop)
            
            # 3. 寫入 DB
            if sessions:
                trace_db.insert_many(sessions)
                dev_sessions += len(sessions)
                print(f"  {curr.strftime('%Y-%m-%d')} ~ {next_hop.strftime('%Y-%m-%d')}: +{len(sessions)} 筆軌跡")
            
            if delay > 0:
                time.sleep(delay)
                
            curr = next_hop
            
        total_sessions += dev_sessions
        print(f"  ✓ 完成，共新增 {dev_sessions} 筆軌跡")

    print("\n" + "="*50)
    print(f"全部完成！共產生 {total_sessions} 筆軌跡紀錄")
    print("="*50)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="建立 trace_log 軌跡資料表")
    parser.add_argument("--thing_id", type=int, help="只處理特定 thing_id")
    parser.add_argument("--days", type=int, help="只處理最近幾天的資料")
    parser.add_argument("--batch_days", type=int, default=30, help="每批處理天數")
    parser.add_argument("--delay", type=float, default=0.1, help="批次延遲 (秒)")
    parser.add_argument("--end_date", type=str, help="結束日期 (YYYY-MM-DD)，預設為現在。建議設為昨天以避免影響即時資料。")
    parser.add_argument("--collection", type=str, default="trace_log_v2", help="目標資料表名稱 (預設: trace_log_v2)")
    parser.add_argument("--force", action="store_true", help="強制重新處理")
    
    args = parser.parse_args()
    
    build_trace_log(
        thing_id=args.thing_id,
        days=args.days,
        batch_days=args.batch_days,
        force=args.force,
        delay=args.delay,
        end_date=args.end_date,
        collection_name=args.collection
    )
