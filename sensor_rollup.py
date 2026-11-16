"""十分鐘彙整：保留來源分類與有效樣本數，避免殘缺 raw 覆蓋完整歷史。"""
from datetime import datetime
from pymongo import UpdateOne

METRICS = ("temperature", "humidity", "battery", "rssi")


def floor_bucket(value: datetime) -> datetime:
    return value.replace(minute=value.minute // 10 * 10, second=0, microsecond=0)


def rollup_pipeline(thing_id, start, end):
    first = {
        "_id": {
            "bucket": {"$subtract": [{"$toLong": "$datetime"}, {"$mod": [{"$toLong": "$datetime"}, 600000]}]},
            **{field: {"$ifNull": ["$" + field, None]} for field in ("detector_id", "uuid", "beacon_id")},
        },
        "count": {"$sum": 1},
    }
    second = {
        "_id": "$_id.bucket", "count": {"$sum": "$count"},
        "sources": {"$push": {**{field: "$_id." + field for field in ("detector_id", "uuid", "beacon_id")}, "count": "$count"}},
    }
    output = {"_id": 0, "thing_id": {"$literal": thing_id}, "datetime": {"$toDate": "$_id"},
              "count": 1, "sources": 1, "aggregation_version": {"$literal": 2}}
    for field in METRICS:
        first[field + "_sum"] = {"$sum": {"$cond": [{"$isNumber": "$" + field}, "$" + field, 0]}}
        first[field + "_samples"] = {"$sum": {"$cond": [{"$isNumber": "$" + field}, 1, 0]}}
        for suffix in ("_sum", "_samples"):
            second[field + suffix] = {"$sum": "$" + field + suffix}
            output[field + suffix] = 1
        output[field] = {"$cond": [{"$gt": ["$" + field + "_samples", 0]}, {"$divide": ["$" + field + "_sum", "$" + field + "_samples"]}, None]}
    return [{"$match": {"thing_id": thing_id, "datetime": {"$gte": start, "$lt": end}}},
            {"$group": first}, {"$group": second}, {"$project": output}]


def write_rollups(collection, thing_id, start, end, rows):
    existing = {}
    for row in collection.find({"thing_id": thing_id, "datetime": {"$gte": start, "$lt": end}}):
        if row["datetime"] in existing:
            raise ValueError("log_10min 同一物件與時間桶重複，停止更新及 raw 清理")
        existing[row["datetime"]] = row
    timestamps = {row["datetime"] for row in rows}
    protected = sum(1 for timestamp in existing if timestamp not in timestamps)
    operations = []
    for row in rows:
        old = existing.get(row["datetime"])
        if old and old.get("count", 0) > row["count"]:
            protected += 1
            continue
        operations.append(UpdateOne({"thing_id": thing_id, "datetime": row["datetime"]}, {"$set": row}, upsert=True))
    if operations:
        collection.bulk_write(operations, ordered=True)
    return len(operations), protected
