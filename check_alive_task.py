import sys
import logging
import importlib

from env_core_resolver import (
    EnvCoreResolverError,
    prepare_core_env_import,
    resolve_core_env_dir,
)

# 設定 logging
logger = logging.getLogger(__name__)


def run_check_alive():
    """
    執行 check_alive 任務，跟隨正式藍綠部署槽位 (env_a/env_b)。
    """
    try:
        active_env_dir = resolve_core_env_dir(required_file="check_alive.py")
        prepare_core_env_import(active_env_dir)

        logger.info(f"Using environment directory: {active_env_dir}")

        # 延遲匯入，確保 sys.path 已經設定好
        check_alive = importlib.import_module("check_alive")

        logger.info("Starting check_alive task...")
        check_alive.check_and_wake_phones()
        logger.info("check_alive task completed.")

    except ImportError as e:
        logger.error(
            f"Failed to import check_alive module: {e}. Current sys.path: {sys.path}")
    except EnvCoreResolverError as e:
        logger.error(f"Failed to resolve core env directory: {e}")
    except Exception as e:
        logger.error(f"Error running check_alive task: {e}", exc_info=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_check_alive()
