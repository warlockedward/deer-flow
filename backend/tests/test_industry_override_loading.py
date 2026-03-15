import json

from src.config.paths import Paths


def test_load_industry_config_prefers_deer_flow_home_override(tmp_path, monkeypatch):
    from src.tools.builtins import bayesian_inference

    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))

    override_dir = tmp_path / "industry_maps"
    override_dir.mkdir(parents=True, exist_ok=True)
    override_path = override_dir / "traditional_manufacturing.json"
    override_path.write_text(json.dumps({"industry": "traditional_manufacturing", "override_marker": 123}), encoding="utf-8")

    loaded = bayesian_inference.load_industry_config("traditional_manufacturing")
    assert loaded.get("override_marker") == 123

