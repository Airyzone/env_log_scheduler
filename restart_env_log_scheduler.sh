#!/usr/bin/env bash

set -Eeuo pipefail

# 可用環境變數覆寫，方便在不同 VM/服務名稱使用同一支腳本。
SERVICE_NAME="${ENV_LOG_SCHEDULER_SERVICE:-env_log_scheduler.service}"
LOG_LINES="${ENV_LOG_SCHEDULER_LOG_LINES:-50}"

if ! command -v systemctl >/dev/null 2>&1; then
    echo "錯誤：找不到 systemctl；請在 systemd Linux 主機上執行。" >&2
    exit 1
fi

if [[ ! "$LOG_LINES" =~ ^[0-9]+$ ]] || (( LOG_LINES < 1 )); then
    echo "錯誤：ENV_LOG_SCHEDULER_LOG_LINES 必須是大於 0 的整數。" >&2
    exit 1
fi

if [[ "$(id -u)" -eq 0 ]]; then
    SUDO=()
else
    SUDO=(sudo)
fi

systemctl_run() {
    "${SUDO[@]}" systemctl "$@"
}

journalctl_run() {
    "${SUDO[@]}" journalctl "$@"
}

echo "==> 重新載入 systemd service 定義：$SERVICE_NAME"
systemctl_run daemon-reload

echo "==> 重啟服務：$SERVICE_NAME"
systemctl_run restart "$SERVICE_NAME"

if ! systemctl_run is-active --quiet "$SERVICE_NAME"; then
    echo "錯誤：服務重啟後不是 active 狀態。" >&2
    systemctl_run status "$SERVICE_NAME" --no-pager -l || true
    exit 1
fi

echo "==> 服務狀態"
systemctl_run status "$SERVICE_NAME" --no-pager -l

echo "==> 最近 ${LOG_LINES} 筆 journal"
journalctl_run -u "$SERVICE_NAME" -n "$LOG_LINES" --no-pager -o short-iso

echo "完成：$SERVICE_NAME 目前為 active。"
