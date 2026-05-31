# Pylance 解譯器鎖定與巡檢流程（env_log_scheduler）

更新日期：2026-05-31（UTC+8）

## 目的

在多根工作區下，避免 `env_log_scheduler` 被切到其他資料夾的虛擬環境（例如 `env/.venv`），導致靜態分析與實際執行環境不一致。

## 已落地設定

- `.vscode/settings.json`
  - `python.defaultInterpreterPath = ${workspaceFolder}/.venv/bin/python`
  - `python.pythonPath = ${workspaceFolder}/.venv/bin/python`
  - `python.analysis.diagnosticMode = workspace`
- `pyrightconfig.json`
  - `venvPath = .`
  - `venv = .venv`

## 開啟專案後 30 秒檢查

1. 開啟 `env_log_scheduler` 任一 `.py` 檔。  
2. 執行 `Python: Select Interpreter`，確認為：
   - `/Users/ford/Documents/Code/Python/env_log_scheduler/.venv/bin/python`
3. 執行 `Python: Restart Language Server`。
4. 檢查 `Problems`（Source: Pylance）是否同步更新。

## 快速排錯（看到大量 import 錯誤時）

1. 先確認 Interpreter 是否漂移到其他 root。  
2. 重新選回 `env_log_scheduler/.venv/bin/python`。  
3. 重啟 Language Server。  
4. 如仍異常，執行 `Developer: Reload Window` 後再檢查。

## 驗證標準

- Pylance 專案掃描結果可穩定反映真實狀態（無跨專案 venv 誤判）
- 相關腳本在本專案 `.venv` 下可正常執行

## 備註

- 測試通過不代表 Pylance 一定無誤，兩者需要分開確認。
- 多根工作區最常見問題是 Interpreter 被其他 root 影響而漂移。
