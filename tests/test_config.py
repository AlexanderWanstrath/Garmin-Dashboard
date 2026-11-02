from pathlib import Path

import pytest

from runlog.config import ConfigError, load_config

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yaml"


def test_example_config_loads():
    config = load_config(EXAMPLE)
    assert "events" in config
    assert "warnings" in config


def test_missing_file_mentions_example(tmp_path):
    with pytest.raises(ConfigError, match="config.example.yaml"):
        load_config(tmp_path / "config.yaml")


def test_invalid_yaml(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("events: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(path)


def test_top_level_must_be_mapping(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(path)
