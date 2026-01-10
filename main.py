"""
GitHub Copilot - 2025-12-19 15:05:00
獨立排程器專案 - 每日 log_10min 預聚合任務
"""

import os
import logging
import time
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from build_log_10min import build_log_10min
from check_alive_task import run_check_alive

# 載入環境變數
load_dotenv()

# 設定 logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def job_build_log_10min():
    """執行預聚合任務"""
    try:
        logger.info("開始執行 log_10min 預聚合任務...")
        # 執行核心邏輯
        build_log_10min(thing_id=None, days=None, batch_days=7, force=False)
        logger.info("log_10min 預聚合任務完成")
    except Exception as e:
        logger.error(f"log_10min 預聚合任務失敗: {e}", exc_info=True)


if __name__ == "__main__":
    # 從環境變數讀取排程時間，預設凌晨 3:00
    hour = int(os.environ.get("SCHEDULER_HOUR", 3))
    minute = int(os.environ.get("SCHEDULER_MINUTE", 0))

    scheduler = BlockingScheduler()

    # 註冊任務
    scheduler.add_job(
        job_build_log_10min,
        trigger=CronTrigger(hour=hour, minute=minute),
        id='build_log_10min_daily',
        name='每日 log_10min 預聚合',
        replace_existing=True,
        misfire_grace_time=3600
    )

    # 註冊 check_alive 任務 (每 15 分鐘執行一次)
    scheduler.add_job(
        run_check_alive,
        trigger=CronTrigger(minute='*/15'),
        id='check_alive_periodic',
        name='定期檢查裝置存活狀態',
        replace_existing=True,
        misfire_grace_time=300
    )

    logger.info("=" * 50)
    logger.info(f"獨立排程器已啟動，預計每日 {hour:02d}:{minute:02d} 執行任務")
    logger.info("已排程 check_alive 任務，每 15 分鐘執行一次")
    logger.info("=" * 50)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("排程器已停止")
