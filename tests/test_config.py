import json

from ownyourship import config as cfg
from ownyourship.scanner import _EXT_PATTERNS


def test_load_returns_defaults_when_absent(tmp_path):
    loaded = cfg.load_config(tmp_path)
    assert loaded["disclaimer_acknowledged"] is False
    assert ".py" in loaded["included_extensions"]


def test_default_extensions_all_have_scanner_support():
    # Regression guard for the empty-scan fix: every default extension must
    # be parseable (Python AST or a regex pattern set).
    for ext in cfg.DEFAULT_CONFIG["included_extensions"]:
        assert ext == ".py" or ext in _EXT_PATTERNS, ext


def test_stored_config_merges_over_defaults(tmp_path):
    (tmp_path / ".oys").mkdir()
    (tmp_path / ".oys" / "config.json").write_text(
        json.dumps({"cost_warning_threshold_usd": 2.5}), encoding="utf-8"
    )
    loaded = cfg.load_config(tmp_path)
    assert loaded["cost_warning_threshold_usd"] == 2.5      # stored value wins
    assert ".py" in loaded["included_extensions"]           # default still present


def test_corrupt_config_falls_back_to_defaults(tmp_path):
    (tmp_path / ".oys").mkdir()
    (tmp_path / ".oys" / "config.json").write_text("{ not valid json", encoding="utf-8")
    loaded = cfg.load_config(tmp_path)
    assert loaded["included_extensions"] == cfg.DEFAULT_CONFIG["included_extensions"]


def test_acknowledge_disclaimer_round_trip(tmp_path):
    assert cfg.is_disclaimer_acknowledged(tmp_path) is False
    cfg.acknowledge_disclaimer(tmp_path)
    assert cfg.is_disclaimer_acknowledged(tmp_path) is True
    loaded = cfg.load_config(tmp_path)
    assert loaded["disclaimer_acknowledged_at"] is not None
