import importlib
import logging
import os
import sys
from pathlib import Path

from env_core_resolver import CORE_DIR_OVERRIDE_ENV, prepare_core_env_import, resolve_core_env_dir


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
CHAT_QUEUE_ROLLBACK_SUPPORTED = True


def _supports_chat_push_queue(core: Path) -> bool:
    try:
        source = (core / "chat_realtime.py").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    return any(line.startswith("CHAT_PUSH_QUEUE_VERSION = ") for line in source.splitlines())


def select_chat_worker_core(active: Path) -> Path:
    if os.environ.get(CORE_DIR_OVERRIDE_ENV, "").strip() or _supports_chat_push_queue(active):
        return active
    other_slot = {"env_a": "env_b", "env_b": "env_a"}.get(active.name)
    if other_slot is None:
        return active
    fallback = active.with_name(other_slot)
    if _supports_chat_push_queue(fallback):
        logger.warning("Active API slot %s uses the legacy queue; keeping chat worker on %s", active, fallback)
        return fallback
    return active


def run_worker() -> None:
    active = Path(resolve_core_env_dir(required_file="chat_realtime.py"))
    core_env_dir = str(select_chat_worker_core(active))
    if core_env_dir == str(active):
        prepare_core_env_import(core_env_dir)
    else:
        prepare_core_env_import(core_env_dir, config_env_dir=str(active))
    sys.modules.pop("chat_realtime", None)

    logger.info("Starting chat outbox worker from %s", core_env_dir)
    chat_realtime = importlib.import_module("chat_realtime")
    worker = chat_realtime.OutboxWorker()
    worker.run()


if __name__ == "__main__":
    run_worker()
