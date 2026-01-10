import sys
import os
import logging

# 設定 logging
logger = logging.getLogger(__name__)


def run_check_alive():
    """
    執行 check_alive 任務
    """
    try:
        # 將 env 專案路徑加入 sys.path 以便匯入模組
        current_dir = os.path.dirname(os.path.abspath(__file__))
        env_dir = os.path.join(os.path.dirname(current_dir), 'env')

        if env_dir not in sys.path:
            sys.path.append(env_dir)

        logger.info(f"Added {env_dir} to sys.path")

        # 延遲匯入，確保 sys.path 已經設定好
        from check_alive import check_and_wake_phones

        logger.info("Starting check_alive task...")
        check_and_wake_phones()
        logger.info("check_alive task completed.")

    except ImportError as e:
        logger.error(
            f"Failed to import check_alive module: {e}. Make sure 'env' project is a sibling of 'env_log_scheduler'.")
    except Exception as e:
        logger.error(f"Error running check_alive task: {e}", exc_info=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_check_alive()
