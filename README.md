# Env Log Scheduler

GitHub Copilot - 2025-12-19 15:15:00

此專案是從 `env` 專案中獨立出來的排程器，專門負責每日的 `log_10min` 預聚合任務。

## 功能
- 每日定時將 `log` 表的原始資料聚合成 10 分鐘粒度，存入 `log_10min` 表。
- 支援智能增量更新，自動跳過已處理的資料。
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
