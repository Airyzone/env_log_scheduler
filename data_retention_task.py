"""依目前正式槽位執行每日資料保留工作。"""
import logging
import os
from pathlib import Path
import subprocess

from env_core_resolver import resolve_core_env_dir

logger = logging.getLogger(__name__)


def run_data_retention():
    core = Path(resolve_core_env_dir(required_file='scripts/process_data_retention.py'))
    result = subprocess.run([
        str(core / '.venv/bin/python'), str(core / 'scripts/process_data_retention.py'),
        '--limit', '200', '--apply'], cwd=str(core),
        env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(core)},
        capture_output=True, text=True, timeout=120, check=True)
    logger.info('Data retention slot=%s summary=%s', core.name, result.stdout.strip()[:1000])
