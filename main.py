"""
GitHub Copilot - 2025-12-19 15:05:00
獨立排程器專案 - 每日 log_10min 預聚合任務
"""

import os
import logging
from logging.handlers import TimedRotatingFileHandler
import subprocess
import sys
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from build_log_10min import build_log_10min
from check_alive_task import run_check_alive

# 載入環境變數
load_dotenv()

# 設定 logging
LOG_DIR = os.environ.get("ENV_SCHEDULER_LOG_DIR",
                         os.path.join(os.getcwd(), "logs"))
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "env_scheduler.log")

root_logger = logging.getLogger()
if root_logger.handlers:
    root_logger.handlers.clear()
root_logger.setLevel(logging.INFO)

log_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

file_handler = TimedRotatingFileHandler(
    LOG_FILE,
    when="midnight",
    interval=1,
    backupCount=14,
    encoding="utf-8"
)
file_handler.setFormatter(log_formatter)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)

root_logger.addHandler(file_handler)
root_logger.addHandler(stream_handler)

# GPT-5.2-Codex 2026-02-06 17:53:36 CST
logger = logging.getLogger(__name__)


def job_prune_raw_log():
    """僅清理已由 log_10min 完整涵蓋、且超過保留期的 raw log。"""
    retention_days = int(os.environ.get("RAW_LOG_RETENTION_DAYS", 30))
    if retention_days < 30:
        raise ValueError("RAW_LOG_RETENTION_DAYS 不得小於 30")

    cutoff = (
        datetime.now().replace(microsecond=0)
        - timedelta(days=retention_days)
    )
    prune_script = os.path.join(os.path.dirname(__file__), "prune_raw_log.py")
    command = [
        sys.executable,
        prune_script,
        "--cutoff",
        cutoff.isoformat(),
        "--batch-hours",
        os.environ.get("RAW_LOG_PRUNE_BATCH_HOURS", "24"),
        "--max-batches",
        os.environ.get("RAW_LOG_PRUNE_MAX_BATCHES", "7"),
        "--minimum-retention-days",
        str(retention_days),
        "--pause-seconds",
        os.environ.get("RAW_LOG_PRUNE_PAUSE_SECONDS", "2"),
        "--execute",
    ]

    logger.info(
        "開始執行 raw log 清理，保留 %s 天，cutoff=%s",
        retention_days,
        cutoff.isoformat(),
    )
    result = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        for line in result.stdout.splitlines():
            logger.info("raw log 清理: %s", line)
    if result.stderr:
        for line in result.stderr.splitlines():
            logger.warning("raw log 清理 stderr: %s", line)
    logger.info("raw log 清理任務完成")


def job_build_log_10min():
    """執行預聚合任務"""
    try:
        logger.info("開始執行 log_10min 預聚合任務...")
        # 執行核心邏輯
        build_log_10min(thing_id=None, days=None, batch_days=7, force=False)
        logger.info("log_10min 預聚合任務完成")
    except Exception as e:
        logger.error(f"log_10min 預聚合任務失敗: {e}", exc_info=True)
        return

    try:
        job_prune_raw_log()
    except Exception as e:
        logger.error(f"raw log 清理任務失敗: {e}", exc_info=True)


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

    # 註冊 check_alive 任務 (每 5 分鐘執行一次，實際 silent push 冷卻 10 分鐘)
    scheduler.add_job(
        run_check_alive,
        trigger=CronTrigger(minute='*/5'),
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
