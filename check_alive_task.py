import sys
import os
import logging
import importlib

# 設定 logging
logger = logging.getLogger(__name__)


def run_check_alive():
    """
    執行 check_alive 任務，支援藍綠部署 (env_a/env_b)
    """
    try:
        # 將 env 專案路徑加入 sys.path 以便匯入模組
        current_dir = os.path.dirname(os.path.abspath(__file__))
        webroot_dir = os.path.dirname(current_dir)

        # 優先搜尋 env_a, env_b, env (新增 env 以支援本地開發環境)
        active_env_dir = None
        # 搜尋順序: env_a -> env_b -> env -> pet
        candidates = ['env_a', 'env_b', 'env', 'pet']

        for cand in candidates:
            env_path = os.path.join(webroot_dir, cand)
            if os.path.exists(os.path.join(env_path, 'check_alive.py')):
                active_env_dir = env_path
                break

        # 如果都沒找到 (理論上不應發生，因為上面已包含 fallback)
        if not active_env_dir:
            active_env_dir = os.path.join(webroot_dir, 'pet')

        if active_env_dir not in sys.path:
            sys.path.append(active_env_dir)

        logger.info(f"Using environment directory: {active_env_dir}")

        # 延遲匯入，確保 sys.path 已經設定好
        check_alive = importlib.import_module("check_alive")

        logger.info("Starting check_alive task...")
        check_alive.check_and_wake_phones()
        logger.info("check_alive task completed.")

    except ImportError as e:
        logger.error(
            f"Failed to import check_alive module: {e}. Current sys.path: {sys.path}")
    except Exception as e:
        logger.error(f"Error running check_alive task: {e}", exc_info=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_check_alive()
