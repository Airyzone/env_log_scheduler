import sys
import logging
import importlib
from pathlib import Path

from env_core_resolver import (
    EnvCoreResolverError,
    prepare_core_env_import,
    resolve_core_env_dir,
)

# 設定 logging
logger = logging.getLogger(__name__)


def _module_file(module):
    """Return a resolved module path when the module has a file on disk."""
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return None
    try:
        return Path(module_file).resolve()
    except (OSError, RuntimeError, TypeError):
        return None


def _is_within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _core_env_module_roots(active_env_dir):
    """Return both blue-green slot roots related to the active directory."""
    active_root = Path(active_env_dir).resolve()
    roots = {active_root}

    # A scheduler process can switch between env_a and env_b without exiting.
    # Include the sibling slot so dependencies imported from the previous
    # slot cannot remain in sys.modules after a deployment switch.
    for slot_name in ("env_a", "env_b"):
        sibling_root = active_root.parent / slot_name
        if sibling_root.is_dir():
            roots.add(sibling_root.resolve())
    return roots


def _evict_core_env_modules(active_env_dir):
    """Remove cached modules loaded from either blue-green core slot."""
    roots = _core_env_module_roots(active_env_dir)
    evicted = []

    for module_name, module in list(sys.modules.items()):
        module_path = _module_file(module)
        if module_path and any(_is_within(module_path, root) for root in roots):
            evicted.append(module_name)

    # Keep this explicit even when the module has no usable __file__ so a
    # stale top-level check_alive entry can never bypass the slot check.
    if "check_alive" in sys.modules and "check_alive" not in evicted:
        evicted.append("check_alive")

    for module_name in evicted:
        sys.modules.pop(module_name, None)

    return evicted


def _load_check_alive(active_env_dir):
    """Load check_alive freshly and prove it came from the active slot."""
    _evict_core_env_modules(active_env_dir)
    check_alive = importlib.import_module("check_alive")

    expected_file = (Path(active_env_dir) / "check_alive.py").resolve()
    loaded_file = _module_file(check_alive)
    if loaded_file != expected_file:
        sys.modules.pop("check_alive", None)
        raise ImportError(
            "Loaded check_alive from unexpected path: "
            f"{loaded_file}; expected {expected_file}"
        )

    logger.info("Loaded check_alive module from: %s", loaded_file)
    return check_alive


def run_check_alive():
    """
    執行 check_alive 任務，跟隨正式藍綠部署槽位 (env_a/env_b)。
    """
    try:
        active_env_dir = resolve_core_env_dir(required_file="check_alive.py")
        prepare_core_env_import(active_env_dir)

        logger.info(f"Using environment directory: {active_env_dir}")

        # 每輪重新載入，避免藍綠切換後沿用上一個 slot 的 module cache。
        check_alive = _load_check_alive(active_env_dir)

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
