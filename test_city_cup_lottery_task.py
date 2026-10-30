from pathlib import Path
from types import SimpleNamespace

import city_cup_lottery_task as task


def test_worker_uses_only_the_resolved_slot_and_isolates_parent_credentials(tmp_path, monkeypatch):
    core = tmp_path / "env_b"
    (core / ".venv/bin").mkdir(parents=True)
    (core / ".venv/bin/python").touch()
    monkeypatch.setenv("SECRET_SHOULD_NOT_BE_INHERITED", "test-only")
    monkeypatch.setattr(task, "resolve_core_env_dir", lambda **kw: str(core))
    seen = []
    def run(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(stdout='{"enabled": false}')
    monkeypatch.setattr(task.subprocess, "run", run)
    task.run_city_cup_lottery()
    command, options = seen[0]
    assert command[0] == str(core / ".venv/bin/python")
    assert command[1] == str(core / "scripts/process_city_cup_lottery.py")
    assert options["cwd"] == str(core)
    assert set(options["env"]) == {"PATH", "PYTHONPATH"}
    assert options["timeout"] == 45


def test_missing_slot_interpreter_never_uses_another_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(task, "resolve_core_env_dir", lambda **kw: str(tmp_path / "env_a"))
    called = []
    monkeypatch.setattr(task.subprocess, "run", lambda *a, **kw: called.append(a))
    task.run_city_cup_lottery()
    assert called == []
