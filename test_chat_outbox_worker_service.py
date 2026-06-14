from pathlib import Path
import unittest


class ChatOutboxWorkerServiceTest(unittest.TestCase):
    def test_service_runs_chat_outbox_worker_entrypoint(self):
        service_text = Path("chat_outbox_worker.service").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "WorkingDirectory=/home/azureuser/webroot/env_log_scheduler",
            service_text,
        )
        self.assertIn(
            "ExecStart=/home/azureuser/webroot/env_log_scheduler/.venv/bin/python chat_outbox_worker_main.py",
            service_text,
        )
        self.assertIn("Restart=always", service_text)


if __name__ == "__main__":
    unittest.main()
