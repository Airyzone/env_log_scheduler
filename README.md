# Env Log Scheduler

GitHub Copilot - 2025-12-19 15:15:00

此專案是從 `env` 專案中獨立出來的排程器，專門負責每日的 `log_10min` 預聚合任務。

## 功能
- 每日定時將 `log` 表的原始資料聚合成 10 分鐘粒度，存入 `log_10min` 表。
- 每日回看至少 90 天，涵蓋 API 允許的延遲補傳；不以殘缺 raw 覆蓋較完整彙整。
- 預聚合成功後，逐批核對 `log_10min.count` 再清理超過 90 天的 raw log。
- 支援 Docker 部署。

## 安裝與執行

### 本地執行
1. 安裝依賴：
   ```bash
   pip install -r requirements.txt
   ```
2. 設定環境變數：
   複製 `.env.example` 為 `.env` 並修改內容。
3. 執行：
   ```bash
   python main.py
   ```

### 型別檢查
啟用專案虛擬環境後安裝開發工具：
```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
pyright
```

### Docker 執行
1. 建立映像檔：
   ```bash
   docker build -t env-log-scheduler .
   ```
2. 執行容器：
   ```bash
   docker run -d --name env-log-scheduler \
     -e MONGODB_URL="mongodb://your-mongo-url:27017" \
     -e SCHEDULER_HOUR=3 \
     env-log-scheduler
   ```

## 腳本參數
你也可以手動執行 `build_log_10min.py` 來進行特定操作：
```bash
python build_log_10min.py --status           # 查看處理狀態
python build_log_10min.py --days 30          # 重新處理最近 30 天
python build_log_10min.py --force            # 強制重新處理所有資料
```

## Raw log 保留設定

預設保留 90 天，且程式不允許低於 API 補傳上限 90 天：

```bash
RAW_LOG_RETENTION_DAYS=90
RAW_LOG_PRUNE_BATCH_HOURS=24
RAW_LOG_PRUNE_MAX_BATCHES=7
RAW_LOG_PRUNE_PAUSE_SECONDS=2
# 只在確認歷史 mismatch bucket 不應刪除、但仍要繼續清理後續安全 bucket 時啟用
RAW_LOG_PRUNE_CONTINUE_ON_MISMATCH=0
# continue mode 的最大掃描數；避免為了找安全 bucket 無限制掃描
RAW_LOG_PRUNE_MAX_SCANNED_BATCHES=70
```

清理只會在每日 `log_10min` 預聚合成功後執行。任一批次的 raw
筆數與 `log_10min.count` 代表筆數不一致時，預設停止且不刪除。若明確啟用
`RAW_LOG_PRUNE_CONTINUE_ON_MISMATCH=1`，該 mismatch 批次會保留 raw 並記錄
`batch_skipped`，只繼續處理後續覆蓋率一致的批次；這不代表 mismatch 批次已修復。

第一批會從最早剩餘 raw 所在的 10 分鐘 aggregate bucket 開始，但在原本的
日曆批次邊界結束；之後才依 `RAW_LOG_PRUNE_BATCH_HOURS` 以日曆批次向後分批。
這可處理先前清理已在非午夜時間停止的資料邊界，又不會把下一個批次提前併入。
若最早 aggregate bucket 本身的 coverage 不一致，仍會停止並保留 raw。

## phone_log 自適應壓縮

`compress_phone_log.py` 不會固定每 10 分鐘只留一點，而是保留移動、轉折、
Beacon 變化，以及每段的首末點；靜止資料才會稀疏化。輸出放在
`phone_log_10min`，每筆包含 `source_count`，用來驗證是否完整涵蓋來源 raw
資料。

排程器預設不啟用此任務。確認 dry-run 結果與地圖軌跡後，才設定：

```bash
PHONE_LOG_COMPACTION_ENABLED=1
PHONE_LOG_RAW_RETENTION_DAYS=30
PHONE_LOG_COMPACTION_MAX_BATCHES=1
PHONE_LOG_COMPACTION_EXECUTE=0
```

`PHONE_LOG_COMPACTION_EXECUTE=0` 只做 dry-run；只有明確改成 `1` 才會在
聚合覆蓋率驗證通過後刪除已表示的 raw rows。無法用於手機軌跡的 invalid
raw rows 會保留在原集合中，不會阻擋同批有效資料壓縮；invalid 清理需另行
執行並逐批驗證。

歷史回補每次從尚未處理的最早有效 raw 開始，空日期與只有 invalid raw
的日期不消耗 `--max-batches`。成功批次核對並清理後，下一次執行會從剩餘
有效 raw 續跑，保留的 invalid raw 不會把進度拉回舊日期。

`run_limit_reached` 表示尚有有效歷史資料待處理，`next_start` 是下一個有效
批次；`complete` 才表示指定 cutoff 之前已無符合條件的待處理來源。
v2 壓縮資料保留來源 IDs 與每小時筆數，可去重續跑中斷批次與晚到資料；舊版來源不明的重疊資料仍會停止並保留 raw。

感測 v2 彙整保留 `sources`（detector_id、uuid、beacon_id 與 count）以及各感測值的有效樣本數。清理除了總筆數，還逐物件與十分鐘桶比對，僅刪除已驗證的來源 IDs。

每日 04:00 的保留維護跟隨正式 env 槽位，執行 `scripts/process_data_retention.py --limit 200 --apply`。API 槽位設定 `DATA_RETENTION_ENABLED=1` 才啟用，僅回補 AI 除錯／生成統計紀錄的到期時間。City Cup 業務資料依使用者指示保留，不納入這個工作；`CITYCUP_DATA_PURGE_ENABLED` 預設為 `0`，證據與抽獎歷史清理均停用，獎勵入帳與抽獎處理仍可正常執行。
