import subprocess
import sys

import pytest

from runlog.cli import COMMANDS, main


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    for name in COMMANDS:
        assert name in out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "runlog" in capsys.readouterr().out


def test_module_entry_point():
    result = subprocess.run([sys.executable, "-m", "runlog.cli", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "sync" in result.stdout
