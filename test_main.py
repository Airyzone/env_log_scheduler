import os
import unittest
from unittest.mock import Mock, patch

import main


class RawLogPruneJobTest(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "RAW_LOG_RETENTION_DAYS": "30",
            "RAW_LOG_PRUNE_BATCH_HOURS": "24",
            "RAW_LOG_PRUNE_MAX_BATCHES": "7",
            "RAW_LOG_PRUNE_PAUSE_SECONDS": "2",
        },
        clear=False,
    )
    @patch("main.subprocess.run")
    def test_prune_job_executes_guarded_cli(self, run_mock):
        run_mock.return_value = Mock(stdout="", stderr="")

        main.job_prune_raw_log()

        command = run_mock.call_args.args[0]
        self.assertEqual(command[0], main.sys.executable)
        self.assertTrue(command[1].endswith("prune_raw_log.py"))
        self.assertIn("--execute", command)
        self.assertEqual(command[command.index("--batch-hours") + 1], "24")
        self.assertEqual(command[command.index("--max-batches") + 1], "7")
        self.assertEqual(
            command[command.index("--minimum-retention-days") + 1],
            "30",
        )
        run_mock.assert_called_once_with(
            command,
            check=True,
            text=True,
            capture_output=True,
        )

    @patch.dict(
        os.environ,
        {"RAW_LOG_RETENTION_DAYS": "29"},
        clear=False,
    )
    @patch("main.subprocess.run")
    def test_prune_job_rejects_retention_below_30_days(self, run_mock):
        with self.assertRaisesRegex(ValueError, "不得小於 30"):
            main.job_prune_raw_log()

        run_mock.assert_not_called()

    @patch("main.job_prune_raw_log")
    @patch("main.build_log_10min")
    def test_prune_runs_only_after_successful_aggregation(
        self,
        build_mock,
        prune_mock,
    ):
        build_mock.side_effect = RuntimeError("aggregation failed")

        main.job_build_log_10min()

        prune_mock.assert_not_called()

    @patch("main.job_prune_raw_log")
    @patch("main.build_log_10min")
    def test_prune_runs_after_successful_aggregation(
        self,
        build_mock,
        prune_mock,
    ):
        main.job_build_log_10min()

        build_mock.assert_called_once_with(
            thing_id=None,
            days=None,
            batch_days=7,
            force=False,
        )
        prune_mock.assert_called_once_with()


class PhoneLogCompactionJobTest(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "PHONE_LOG_COMPACTION_ENABLED": "1",
            "PHONE_LOG_RAW_RETENTION_DAYS": "30",
            "PHONE_LOG_COMPACTION_BATCH_HOURS": "24",
            "PHONE_LOG_COMPACTION_MAX_BATCHES": "1",
            "PHONE_LOG_COMPACTION_PAUSE_SECONDS": "2",
            "PHONE_LOG_COMPACTION_EXECUTE": "0",
        },
        clear=False,
    )
    @patch("main.subprocess.run")
    def test_phone_compaction_defaults_to_dry_run(self, run_mock):
        run_mock.return_value = Mock(returncode=0, stdout="", stderr="")

        main.job_compress_phone_log()

        command = run_mock.call_args.args[0]
        self.assertTrue(command[1].endswith("compress_phone_log.py"))
        self.assertIn("--cutoff", command)
        self.assertIn("--minimum-retention-days", command)
        self.assertNotIn("--execute", command)
        run_mock.assert_called_once_with(
            command,
            check=False,
            text=True,
            capture_output=True,
        )

    @patch.dict(
        os.environ,
        {
            "PHONE_LOG_COMPACTION_ENABLED": "1",
            "PHONE_LOG_RAW_RETENTION_DAYS": "29",
        },
        clear=False,
    )
    @patch("main.subprocess.run")
    def test_phone_compaction_rejects_retention_below_30(self, run_mock):
        with self.assertRaisesRegex(ValueError, "不得小於 30"):
            main.job_compress_phone_log()

        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
