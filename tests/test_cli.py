import json
import subprocess
import sys
from typing import Any

import pytest

from pitwall.cli import EXIT_FAILED, main
from tests.conftest import REPO_CONFIG


def _log_lines(stderr: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stderr.splitlines() if line.startswith("{")]


def test_help_lists_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "run" in out
    assert "release" in out


@pytest.mark.integration
def test_module_entry_point_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pitwall", "run", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--session" in result.stdout
    assert "--as-of" in result.stdout


def test_run_stub_fails_loudly_and_logs_inputs(capsys: pytest.CaptureFixture[str]) -> None:
    args = ["run", "--session", "9158", "--as-of", "2026-11-02T10:00+02:00"]
    code = main(["--config", str(REPO_CONFIG), *args])

    assert code == EXIT_FAILED
    lines = _log_lines(capsys.readouterr().err)
    started = next(line for line in lines if line["message"] == "run started")
    assert started["session_key"] == 9158
    assert started["as_of"] == "2026-11-02T08:00:00+00:00"
    assert len({line["run_id"] for line in lines}) == 1
    assert lines[0]["run_id"] is not None


def test_release_stub_fails_loudly() -> None:
    assert main(["--config", str(REPO_CONFIG), "release"]) == EXIT_FAILED


@pytest.mark.parametrize("value", ["2026-11-02T08:00:00", "yesterday"])
def test_as_of_rejects_naive_or_invalid_timestamps(value: str) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--config", str(REPO_CONFIG), "run", "--as-of", value])

    assert exc.value.code == 2


def test_missing_config_exits_with_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--config", "nope.yaml", "run"])

    assert exc.value.code == 2
    assert "config file not found" in capsys.readouterr().err
