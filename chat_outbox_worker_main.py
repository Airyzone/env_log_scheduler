import importlib
import logging
import sys

from env_core_resolver import prepare_core_env_import, resolve_core_env_dir


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_worker() -> None:
    core_env_dir = resolve_core_env_dir(required_file="chat_realtime.py")
    prepare_core_env_import(core_env_dir)
    sys.modules.pop("chat_realtime", None)

    logger.info("Starting chat outbox worker from %s", core_env_dir)
    chat_realtime = importlib.import_module("chat_realtime")
    worker = chat_realtime.OutboxWorker()
    worker.run()


if __name__ == "__main__":
    run_worker()
