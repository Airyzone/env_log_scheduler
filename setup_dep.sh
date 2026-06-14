#!/bin/bash
# setup_dep.sh
# 智慧安裝依賴腳本 - 自動偵測本地或伺服器環境的 Core Project 路徑
# 2026-01-09

set -e

TARGET_PATH=""

echo "🔍 正在尋找核心專案 (Core Project)..."

if [ -n "${ENV_CORE_DIR:-}" ]; then
    if [ -d "$ENV_CORE_DIR" ] && [ -f "$ENV_CORE_DIR/pyproject.toml" ]; then
        TARGET_PATH="$ENV_CORE_DIR"
        echo "✅ 使用 ENV_CORE_DIR 指定核心專案: $TARGET_PATH"
    else
        echo "❌ ENV_CORE_DIR 無效或缺少 pyproject.toml: $ENV_CORE_DIR"
        exit 1
    fi
fi

if [ -z "$TARGET_PATH" ] && [ -L "/etc/nginx/conf.d/current_env.conf" ]; then
    CURRENT_LINK=$(readlink -f "/etc/nginx/conf.d/current_env.conf")
    if [[ "$CURRENT_LINK" == *"env_target_a.map" ]]; then
        TARGET_PATH="../env_a"
    elif [[ "$CURRENT_LINK" == *"env_target_b.map" ]]; then
        TARGET_PATH="../env_b"
    fi

    if [ -n "$TARGET_PATH" ]; then
        echo "✅ 依正式 nginx 指向選擇核心專案: $TARGET_PATH"
    fi
fi

if [ -z "$TARGET_PATH" ]; then
    # 本地開發環境才使用 ../env；伺服器正式環境應由 nginx symlink 決定 env_a/env_b。
    if [ -d "../env" ] && [ -f "../env/pyproject.toml" ]; then
        TARGET_PATH="../env"
        echo "✅ 使用本地開發核心專案: $TARGET_PATH"
    fi
fi

if [ -z "$TARGET_PATH" ]; then
    echo "❌ 錯誤: 找不到正式核心專案資料夾"
    echo "請確認 /etc/nginx/conf.d/current_env.conf 指向 env_a/env_b，或用 ENV_CORE_DIR 明確指定"
    exit 1
fi

# 檢查 uv 是否存在
UV_CMD="pip"
if command -v uv >/dev/null 2>&1; then
    echo "⚡ 偵測到 uv，將使用 uv pip 進行安裝"
    UV_CMD="uv pip"
fi

# 建立/啟用 venv (如果是 Linux/Mac)
if [ ! -d ".venv" ]; then
    echo "📦 建立 .venv..."
    if command -v uv >/dev/null 2>&1; then
        uv venv --python 3.8
    else
        python3 -m venv .venv
    fi
fi

# 嘗試啟用 venv
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "⚠️  警告: 無法啟用 .venv，將嘗試直接安裝"
fi

echo "🚀 開始安裝依賴..."
# 1. 安裝 requirements.txt
$UV_CMD install -r requirements.txt

# 2. 安裝 Core Project (Editable Mode)
echo "🔗 連結核心專案: $TARGET_PATH"
$UV_CMD install -e "$TARGET_PATH"

echo "✨ 安裝完成！"
echo "請使用 'source .venv/bin/activate' 啟用環境"
