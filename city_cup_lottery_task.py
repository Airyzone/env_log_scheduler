"""抽獎背景工作跟隨正式 env 槽位，使用該槽自己的 Python 與環境。"""
import logging
import os
from pathlib import Path
import subprocess

from env_core_resolver import EnvCoreResolverError, resolve_core_env_dir

logger = logging.getLogger(__name__)


def run_city_cup_lottery():
    try:
        core = Path(resolve_core_env_dir(required_file="scripts/process_city_cup_lottery.py"))
        interpreter = core / ".venv/bin/python"
        if not interpreter.is_file():
            raise EnvCoreResolverError("Active slot lottery interpreter is unavailable")
        result = subprocess.run([str(interpreter), str(core / "scripts/process_city_cup_lottery.py"), "--limit", "50"],
            cwd=str(core), env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(core)},
            capture_output=True, text=True, timeout=45, check=True)
        logger.info("City Cup lottery slot=%s summary=%s", core.name, result.stdout.strip()[:500])
    except (EnvCoreResolverError, OSError, subprocess.SubprocessError) as exc:
        # 不回退到另一個槽位或另一個 interpreter。
        logger.warning("City Cup lottery maintenance unavailable: %s", type(exc).__name__)
