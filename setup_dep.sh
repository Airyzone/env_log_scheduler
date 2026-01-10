#!/bin/bash
# setup_dep.sh
# 智慧安裝依賴腳本 - 自動偵測本地或伺服器環境的 Core Project 路徑
# 2026-01-09

set -e

# 定義可能的路徑
PATHS=(
    "../env"    # 本地開發環境
    "../pet"    # 伺服器 (Master Source)
    "../env_a"  # 伺服器 (Fallback)
)

TARGET_PATH=""

echo "🔍 正在尋找核心專案 (Core Project)..."

for path in "${PATHS[@]}"; do
    if [ -d "$path" ] && [ -f "$path/pyproject.toml" ]; then
        TARGET_PATH="$path"
        echo "✅ 找到核心專案: $TARGET_PATH"
        break
    fi
done

if [ -z "$TARGET_PATH" ]; then
    echo "❌ 錯誤: 找不到任何核心專案資料夾 (env, pet, env_a)"
    echo "請確認您與 env 專案位於同一層目錄"
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
