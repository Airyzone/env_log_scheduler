# AGENTS.md — AIRYZONE env_log_scheduler

此專案從 `Python/env` 拆出，負責每日 `log_10min` 預彙總、增量更新和定期維護。先讀 [工作區共用規範](../../AGENTS.md)，本檔補充 scheduler 執行與部署慣例。

## 排程與執行環境

- 保留 `log` 到 `log_10min` 的彙總、增量更新和維護語意。只有任務需要重建時才使用 `build_log_10min.py --force`，先確認目標資料庫與重建範圍。
- 使用本專案 `.venv/bin/python`。Python 版本以 `.python-version` 為準，套件以 `requirements.lock` 安裝並啟用 `--require-hashes`。Scheduler 有 APScheduler 等額外依賴，維護獨立的 venv。
- [env_core_resolver.py](env_core_resolver.py) 的 `resolve_core_env_dir()` 由 Nginx 的 `/etc/nginx/conf.d/current_env.conf` 解析正式 env_a／env_b。僅在手動隔離測試中用 `ENV_CORE_DIR` 明確指定來源。

## 驗證與交付

- 依改動執行 Pylance／Pyright（`pyrightconfig.json`）、import、語法或 `PYTHONPATH=. .venv/bin/python -m pytest -q <test-or-selector>` 等相關檢查。整合測試使用隔離資料庫與測試設定，排除正式 `.env` 與憑證。
- MongoDB 與環境設定屬外部狀態。只有目標與設定已確認時才執行 `build_log_10min.py --status`。環境受限時回報哪項驗證未完成。
- 除錯回報已查證的原因。回報程式碼變更時，給完整修改段落。更新專案文件時，依共用規範的「Documentation And Obsidian」處理。

## az02 部署

- 在永久路徑建立候選 Python 與 venv。驗證候選環境並停止相關服務後切換 `.venv`，保留舊環境供回復。勿搬移 venv 或在服務執行中更新套件。
- env 的 `manage_env.sh switch` 會重啟 `env_log_scheduler.service` 與 `chat_outbox_worker.service`。本專案或依賴有改動時，另行部署並核對本專案鎖檔。
- 部署後核對兩個 unit 的實際 Python、PID、日誌與核心來源槽位。以排程或推播本身的證據確認結果。勿為驗證手動觸發正式維護工作。
