import subprocess
import sys

import pytest

from runlog.cli import COMMANDS, main


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    for name in COMMANDS:
        assert name in out


@pytest.mark.parametrize("name", [c for c in COMMANDS if c not in ("sync", "log", "check", "mcp")])
def test_unimplemented_command_fails_with_stage(name, capsys):
    assert main([name]) == 1
    assert f"stage {COMMANDS[name][1]}" in capsys.readouterr().err


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "runlog" in capsys.readouterr().out


def test_module_entry_point():
    result = subprocess.run([sys.executable, "-m", "runlog.cli", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "sync" in result.stdout
