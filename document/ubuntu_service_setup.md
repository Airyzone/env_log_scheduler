# Ubuntu Systemd Service 設定指引

這份文件說明如何在遠端 Ubuntu Server 上將 `env_log_scheduler` 設定為系統服務，使其在背景按排程自動執行。

## 1. 準備工作

### 1.1 部署程式碼
將專案放置於伺服器上的目標目錄（例如 `/home/azureuser/webroot/env_log_scheduler`）。

### 1.2 建立虛擬環境
在專案根目錄下執行：
```bash
python3 -m venv .venv
source .venv/bin/bin/activate
pip install -r requirements.txt
```

### 1.3 設定環境變數
參考 `.env.example` 建立 `.env`：
```bash
cp .env.example .env
nano .env
```
確保設定了正確的資料庫連線與排程時間：
- `SCHEDULER_HOUR`: 聚合任務執行的小時 (0-23)
- `SCHEDULER_MINUTE`: 聚合任務執行的分鐘 (0-59)

## 2. 設定 Systemd 服務

### 2.1 修改服務設定檔
開啟專案中的 `env_scheduler.service` 並根據您的伺服器環境修改：
1. **User/Group**: 修改為您的執行帳號（例如 `ubuntu`）。
2. **WorkingDirectory**: 專案的絕對路徑。
3. **Environment/ExecStart**: 指向虛擬環境中的 python 路徑。

### 2.2 安裝服務
將檔案複製到系統目錄並載入：
```bash
# 複製檔案 (請確認路徑正確)
sudo cp env_scheduler.service /etc/systemd/system/env_log_scheduler.service

# 重新載入系統服務
sudo systemctl daemon-reload

# 設定為開機自動啟動
sudo systemctl enable env_log_scheduler.service

# 立即啟動服務
sudo systemctl start env_log_scheduler.service
```

## 3. 常用管理指令

- **查看服務狀態**:
  ```bash
  sudo systemctl status env_log_scheduler.service
  ```
- **停止服務**:
  ```bash
  sudo systemctl stop env_log_scheduler.service
  ```
- **重啟服務**:
  ```bash
  sudo systemctl restart env_log_scheduler.service
  ```
- **查看即時日誌**:
  ```bash
  journalctl -u env_log_scheduler.service -f
  ```

## 4. 排程說明
程式內部使用 `apscheduler` 進行排程：
- **每日聚合任務**: 依據 `.env` 中的時間執行一次。
- **存活檢查 (check_alive)**: 每 15 分鐘執行一次（固定於程式中）。

如果需要修改排程邏輯，請調整 `main.py` 並重啟服務。
