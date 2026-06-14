import sys
import types
import unittest
from unittest import mock


class ChatOutboxWorkerMainTest(unittest.TestCase):
    def test_run_worker_uses_resolved_core_env_and_runs_outbox_worker(self):
        import chat_outbox_worker_main

        events = []

        class FakeWorker:
            def run(self):
                events.append("run")

        fake_chat_realtime = types.SimpleNamespace(OutboxWorker=FakeWorker)

        with mock.patch.object(
            chat_outbox_worker_main,
            "resolve_core_env_dir",
            return_value="/srv/webroot/env_a",
        ) as resolve_mock, mock.patch.object(
            chat_outbox_worker_main,
            "prepare_core_env_import",
        ) as prepare_mock, mock.patch.object(
            chat_outbox_worker_main.importlib,
            "import_module",
            return_value=fake_chat_realtime,
        ) as import_mock:
            chat_outbox_worker_main.run_worker()

        resolve_mock.assert_called_once_with(required_file="chat_realtime.py")
        prepare_mock.assert_called_once_with("/srv/webroot/env_a")
        import_mock.assert_called_once_with("chat_realtime")
        self.assertEqual(["run"], events)

    def test_run_worker_reimports_chat_realtime_from_active_env(self):
        import chat_outbox_worker_main

        class FakeWorker:
            def run(self):
                pass

        stale_module = types.ModuleType("chat_realtime")
        setattr(stale_module, "OutboxWorker", FakeWorker)
        sys.modules["chat_realtime"] = stale_module
        try:
            with mock.patch.object(
                chat_outbox_worker_main,
                "resolve_core_env_dir",
                return_value="/srv/webroot/env_b",
            ), mock.patch.object(
                chat_outbox_worker_main,
                "prepare_core_env_import",
            ), mock.patch.object(
                chat_outbox_worker_main.importlib,
                "import_module",
                return_value=stale_module,
            ) as import_mock:
                chat_outbox_worker_main.run_worker()

            self.assertNotIn("chat_realtime", sys.modules)
            import_mock.assert_called_once_with("chat_realtime")
        finally:
            sys.modules.pop("chat_realtime", None)


if __name__ == "__main__":
    unittest.main()
