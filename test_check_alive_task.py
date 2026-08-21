import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import check_alive_task


class CheckAliveTaskSlotLoadingTest(unittest.TestCase):
    def test_switching_slots_reloads_check_alive_and_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_a = root / "env_a"
            env_b = root / "env_b"
            env_a.mkdir()
            env_b.mkdir()

            for env_dir, source in (
                (env_a, "env_a"),
                (env_b, "env_b"),
            ):
                (env_dir / "slot_dependency.py").write_text(
                    f"SOURCE = '{source}'\n",
                    encoding="utf-8",
                )
                (env_dir / "check_alive.py").write_text(
                    "import slot_dependency\n"
                    f"SOURCE = '{source}'\n"
                    "DEPENDENCY_SOURCE = slot_dependency.SOURCE\n"
                    "def check_and_wake_phones():\n"
                    "    return SOURCE\n",
                    encoding="utf-8",
                )

            original_sys_path = list(sys.path)
            original_check_alive = sys.modules.pop("check_alive", None)
            original_dependency = sys.modules.pop("slot_dependency", None)
            try:
                with mock.patch.object(
                    check_alive_task,
                    "resolve_core_env_dir",
                    side_effect=[str(env_b), str(env_a)],
                ), mock.patch.object(
                    check_alive_task,
                    "logger",
                ) as logger_mock:
                    check_alive_task.run_check_alive()
                    first_module = sys.modules["check_alive"]
                    self.assertEqual(first_module.SOURCE, "env_b")
                    self.assertEqual(first_module.DEPENDENCY_SOURCE, "env_b")

                    check_alive_task.run_check_alive()
                    second_module = sys.modules["check_alive"]
                    self.assertEqual(second_module.SOURCE, "env_a")
                    self.assertEqual(
                        second_module.DEPENDENCY_SOURCE,
                        "env_a",
                    )
                    self.assertNotEqual(first_module, second_module)
                    self.assertTrue(
                        any(
                            "env_a/check_alive.py" in str(call)
                            for call in logger_mock.info.call_args_list
                        )
                    )
            finally:
                sys.path[:] = original_sys_path
                sys.modules.pop("check_alive", None)
                sys.modules.pop("slot_dependency", None)
                if original_check_alive is not None:
                    sys.modules["check_alive"] = original_check_alive
                if original_dependency is not None:
                    sys.modules["slot_dependency"] = original_dependency


if __name__ == "__main__":
    unittest.main()
