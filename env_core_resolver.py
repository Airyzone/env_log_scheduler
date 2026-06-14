import os
import sys
from pathlib import Path
from typing import Optional


DEFAULT_NGINX_LINK = "/etc/nginx/conf.d/current_env.conf"
CORE_DIR_OVERRIDE_ENV = "ENV_CORE_DIR"
NGINX_LINK_ENV = "ENV_NGINX_CURRENT_CONF"


class EnvCoreResolverError(RuntimeError):
    pass


def default_webroot_dir() -> str:
    return str(Path(__file__).resolve().parent.parent)


def _slot_from_nginx_target(target_path: str) -> str:
    target_name = Path(target_path).name
    if target_name == "env_target_a.map":
        return "env_a"
    if target_name == "env_target_b.map":
        return "env_b"
    raise EnvCoreResolverError(
        f"Unknown nginx current env target: {target_path}"
    )


def _validate_core_dir(path: Path, required_file: str) -> str:
    if not path.is_dir():
        raise EnvCoreResolverError(f"Core env directory not found: {path}")
    required_path = path / required_file
    if required_file and not required_path.exists():
        raise EnvCoreResolverError(
            f"Core env directory missing {required_file}: {path}"
        )
    return str(path)


def resolve_core_env_dir(
    *,
    webroot_dir: Optional[str] = None,
    nginx_link: Optional[str] = None,
    required_file: str = "check_alive.py",
) -> str:
    """
    Resolve the core Python/env directory used by scheduler tasks.

    Production mode follows the nginx active env symlink and only accepts
    env_a/env_b. pet must be selected explicitly with ENV_CORE_DIR for manual
    testing.
    """
    override = os.environ.get(CORE_DIR_OVERRIDE_ENV, "").strip()
    if override:
        return _validate_core_dir(Path(override).expanduser().resolve(), required_file)

    root = Path(webroot_dir or default_webroot_dir()).resolve()
    current_link = Path(
        nginx_link or os.environ.get(NGINX_LINK_ENV, DEFAULT_NGINX_LINK)
    )
    if not current_link.exists():
        raise EnvCoreResolverError(f"Nginx current env link not found: {current_link}")

    target = os.path.realpath(str(current_link))
    slot_dir_name = _slot_from_nginx_target(target)
    return _validate_core_dir(root / slot_dir_name, required_file)


def prepare_core_env_import(core_env_dir: str) -> None:
    """
    Put the resolved core env directory first in sys.path and load its .env.
    """
    if core_env_dir in sys.path:
        sys.path.remove(core_env_dir)
    sys.path.insert(0, core_env_dir)

    dotenv_path = Path(core_env_dir) / ".env"
    if dotenv_path.exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(dotenv_path=dotenv_path, override=True)
        except Exception:
            # Import path correctness is more important than dotenv availability;
            # imported modules may still rely on process environment variables.
            pass
