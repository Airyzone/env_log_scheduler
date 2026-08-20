# Env Log Scheduler

GitHub Copilot - 2025-12-19 15:15:00

此專案是從 `env` 專案中獨立出來的排程器，專門負責每日的 `log_10min` 預聚合任務。

## 功能
- 每日定時將 `log` 表的原始資料聚合成 10 分鐘粒度，存入 `log_10min` 表。
- 支援智能增量更新，自動跳過已處理的資料。
- 預聚合成功後，逐批核對 `log_10min.count` 再清理超過 30 天的 raw log。
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

預設保留 30 天，且程式不允許低於 30 天：

```bash
RAW_LOG_RETENTION_DAYS=30
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
