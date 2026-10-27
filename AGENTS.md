# AGENTS.md - Python Scheduler (env_log_scheduler)

Read `/Users/fordwang/Documents/Code/AGENTS.md` first. This file adds project-specific
rules for `/Users/fordwang/Documents/Code/Python/env_log_scheduler`.

## Project Overview

Python background scheduler split out from `Python/env`. It builds daily `log_10min` pre-aggregations from raw `log` records, supports incremental updates, and performs scheduled maintenance tasks.

## Tech Stack

- **Language**: Python 3.12.16（使用本專案 `.venv/bin/python`；精確版本見 `.python-version`）
- **Deployment**: az02 systemd（`env_log_scheduler.service`、`chat_outbox_worker.service`）；本機腳本或 Docker 用於測試
- **Type Checker**: Pylance / Pyright (`pyrightconfig.json`)

## Scheduler Rules

- Preserve `log` to `log_10min` aggregation semantics unless the task explicitly changes them
- Be careful with force rebuild paths such as `build_log_10min.py --force`
- Treat MongoDB/environment access as external state; do not assume it is available locally

## Runtime and Blue-Green Deployment

- 使用本專案 `.venv/bin/python`，Python 精確版本以 `.python-version` 為準；
  套件以本專案 `requirements.lock` 安裝並啟用 `--require-hashes`。
  Scheduler 含 APScheduler 等額外套件，不直接拿 API 的 venv 取代本專案環境。
- 候選 Python 與 venv 建於永久路徑，停止相關背景服務後才切換 `.venv`；
  保留舊環境供回復，不在服務執行中更新套件，也不搬移已建好的 venv。
- `env_core_resolver.resolve_core_env_dir()` 依 Nginx 的
  `/etc/nginx/conf.d/current_env.conf` 解析正式 env_a/env_b。
  不寫死槽位或默認使用 pet；手動隔離測試才以 `ENV_CORE_DIR` 明確指定來源。
- env 的 `manage_env.sh switch` 會重啟兩個背景服務，但不會上傳本專案程式。
  本專案程式或依賴變更時，必須另外部署並核對 scheduler 鎖檔。
- 部署後檢查兩個 unit 的實際 Python、PID、日誌與核心來源槽位；
  程序 active 不等於排程工作或推播已成功。不要為驗證而手動觸發正式維護工作。

## Code Style

- Provide **full code snippets** when modifying code
- Modify **only necessary sections**
- Prefer clear architecture and efficient algorithms
- No assumptions without evidence
- If debugging: explain root cause
- Ensure code runs correctly after modification

## Verification

- 從本專案根目錄以 `PYTHONPATH=. .venv/bin/python -m pytest -q <test-or-selector>`
  執行相關測試；整合測試使用隔離資料庫與測試設定，不繼承正式 `.env` 或憑證。
- Prefer narrow checks such as import/script syntax checks or `build_log_10min.py --status` when environment variables are configured
- If database or environment access is unavailable, report that clearly instead of pretending verification passed

## Documentation

- New and updated project documentation goes first to the Obsidian knowledge
  base at:
  `/Users/fordwang/Library/Mobile Documents/iCloud~md~obsidian/Documents/Ford Obsidian/工作/AIRYZONE`.
- Follow the shared `Documentation And Obsidian` rules: update existing topic
  notes when appropriate, preserve source/evidence context, and avoid duplicate
  full documents in this repository's `document/` or `docs/` directories.
- Keep agent instructions, essential README/index files, and documents directly
  required by builds/tests/tooling in the repository. Direct user instructions
  may specify another destination.
- If vault writing is restricted, use the available narrowly scoped approval
  mechanism or explain how to allow this AIRYZONE directory. Do not silently
  generate the document in the project instead; these instructions do not
  override filesystem permissions.
