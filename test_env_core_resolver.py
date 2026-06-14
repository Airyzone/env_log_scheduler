import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class EnvCoreResolverTest(unittest.TestCase):
    def test_resolves_active_env_a_from_nginx_symlink(self):
        from env_core_resolver import resolve_core_env_dir

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "env_a" / "check_alive.py").parent.mkdir()
            (root / "env_a" / "check_alive.py").write_text("", encoding="utf-8")
            maps = root / "maps"
            maps.mkdir()
            target = maps / "env_target_a.map"
            target.write_text("", encoding="utf-8")
            link = root / "current_env.conf"
            link.symlink_to(target)

            resolved = resolve_core_env_dir(
                webroot_dir=str(root),
                nginx_link=str(link),
                required_file="check_alive.py",
            )

        self.assertEqual(str((root / "env_a").resolve()), resolved)

    def test_rejects_missing_active_env_instead_of_falling_back_to_pet(self):
        from env_core_resolver import EnvCoreResolverError, resolve_core_env_dir

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pet" / "check_alive.py").parent.mkdir()
            (root / "pet" / "check_alive.py").write_text("", encoding="utf-8")
            maps = root / "maps"
            maps.mkdir()
            target = maps / "env_target_a.map"
            target.write_text("", encoding="utf-8")
            link = root / "current_env.conf"
            link.symlink_to(target)

            with self.assertRaises(EnvCoreResolverError):
                resolve_core_env_dir(
                    webroot_dir=str(root),
                    nginx_link=str(link),
                    required_file="check_alive.py",
                )

    def test_allows_explicit_pet_override_for_manual_testing(self):
        from env_core_resolver import resolve_core_env_dir

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pet = root / "pet"
            pet.mkdir()
            (pet / "check_alive.py").write_text("", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {"ENV_CORE_DIR": str(pet)},
                clear=False,
            ):
                resolved = resolve_core_env_dir(
                    webroot_dir=str(root),
                    nginx_link=str(root / "missing.conf"),
                    required_file="check_alive.py",
                )

        self.assertEqual(str(pet.resolve()), resolved)


if __name__ == "__main__":
    unittest.main()
