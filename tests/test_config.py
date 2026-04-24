"""Tests for split configuration loading."""

from pathlib import Path

from morning_digest.config import load_config


def test_load_config_merges_split_files():
    config = load_config(Path(__file__).parent.parent)

    assert config["pipeline"]["stages"][0]["name"] == "collect"
    assert config["rss"]["feeds"]
    assert config["delivery"]["method"] == "smtp"
    assert config["digest"]["at_a_glance"]["max_items"] == 7


def test_seams_turns_stay_below_fireworks_forced_stream_threshold():
    config = load_config(Path(__file__).parent.parent)
    seams_stage = next(
        stage
        for stage in config["pipeline"]["stages"]
        if stage.get("name") == "seams"
    )

    assert seams_stage["model"]["model"] == "accounts/fireworks/models/kimi-k2p6"
    assert seams_stage["model"]["max_tokens"] <= 4096
    assert seams_stage["turns"]["candidates"]["max_tokens"] <= 4096
    assert seams_stage["turns"]["annotations"]["max_tokens"] <= 4096


def test_legacy_config_yaml_overrides_split_config(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "pipeline.yaml").write_text(
        "pipeline:\n  retry:\n    max_retries: 1\n",
        encoding="utf-8",
    )
    (config_dir / "sources.yaml").write_text(
        "rss:\n  provider: direct\n",
        encoding="utf-8",
    )
    (config_dir / "delivery.yaml").write_text(
        "delivery:\n  method: smtp\n",
        encoding="utf-8",
    )
    (tmp_path / "config.yaml").write_text(
        "pipeline:\n  retry:\n    max_retries: 3\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config["pipeline"]["retry"]["max_retries"] == 3
    assert config["rss"]["provider"] == "direct"
    assert config["delivery"]["method"] == "smtp"


def test_split_marker_config_yaml_does_not_override(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "pipeline.yaml").write_text(
        "pipeline:\n  retry:\n    max_retries: 1\n",
        encoding="utf-8",
    )
    (config_dir / "sources.yaml").write_text("", encoding="utf-8")
    (config_dir / "delivery.yaml").write_text("", encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        "_split_config: true\npipeline:\n  retry:\n    max_retries: 3\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config["pipeline"]["retry"]["max_retries"] == 1
