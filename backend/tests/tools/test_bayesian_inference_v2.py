"""V2 tests for the Bayesian inference engine.

Tests cover:
- Dynamic DAG construction from industry JSON config
- Time-decay weighting (signals > 6 months old → weight → 0)
- Multi-source verification (>= 2 independent sources required)
- Backward-compat: existing list[str] call still works
"""

import json
import math
from datetime import datetime, timedelta

import pytest

from src.tools.builtins.bayesian_inference import (
    apply_time_decay,
    build_network,
    calculate_bayesian_risk,
    load_industry_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _recent(months_ago: float = 1.0) -> str:
    """Return an ISO date that is ``months_ago`` months in the past."""
    days = int(months_ago * 30)
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def _old(months_ago: float = 8.0) -> str:
    """Return an ISO date that is more than 6 months old."""
    days = int(months_ago * 30)
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Task 2: Dynamic DAG loading
# ---------------------------------------------------------------------------


class TestLoadIndustryConfig:
    def test_load_traditional_manufacturing(self):
        config = load_industry_config("traditional_manufacturing")
        assert config["industry"] == "traditional_manufacturing"
        assert "signals" in config
        assert "causal_relationships" in config

    def test_load_high_tech(self):
        config = load_industry_config("high_tech")
        assert config["industry"] == "high_tech"
        assert "signals" in config
        assert "causal_relationships" in config

    def test_unknown_industry_raises(self):
        with pytest.raises((FileNotFoundError, KeyError, ValueError)):
            load_industry_config("nonexistent_industry")


class TestBuildNetwork:
    def test_build_network_from_traditional_manufacturing(self):
        config = load_industry_config("traditional_manufacturing")
        model = build_network(config)
        # Model must be checkable (valid CPDs)
        assert model.check_model()

    def test_build_network_from_high_tech(self):
        config = load_industry_config("high_tech")
        model = build_network(config)
        assert model.check_model()

    def test_network_contains_management_gap_node(self):
        config = load_industry_config("traditional_manufacturing")
        model = build_network(config)
        assert "Management_Gap" in model.nodes()

    def test_network_edges_match_causal_relationships(self):
        config = load_industry_config("traditional_manufacturing")
        model = build_network(config)
        edges = list(model.edges())
        # Expect edges from Management_Gap to each effect in causal_relationships
        effects = [r["effect"] for r in config["causal_relationships"]]
        for effect in effects:
            assert ("Management_Gap", effect) in edges


# ---------------------------------------------------------------------------
# Task 3: Time-decay weighting
# ---------------------------------------------------------------------------


class TestApplyTimeDecay:
    def test_recent_signal_has_high_weight(self):
        weight = apply_time_decay(timestamp=_recent(1), decay_rate_months=6)
        assert weight > 0.8  # exp(-1/6) ≈ 0.846

    def test_old_signal_has_near_zero_weight(self):
        weight = apply_time_decay(timestamp=_old(8), decay_rate_months=6)
        assert weight < 0.35  # exp(-8/6) ≈ 0.264

    def test_exactly_at_boundary_moderate_weight(self):
        weight = apply_time_decay(timestamp=_recent(6), decay_rate_months=6)
        expected = math.exp(-1.0)  # exp(-6/6) ≈ 0.368
        assert abs(weight - expected) < 0.05

    def test_very_old_signal_nearly_zero(self):
        # 24 months old → exp(-24/6) = exp(-4) ≈ 0.018
        weight = apply_time_decay(timestamp=_old(24), decay_rate_months=6)
        assert weight < 0.05


# ---------------------------------------------------------------------------
# Task 3: Multi-source verification + full V2 calculate_bayesian_risk
# ---------------------------------------------------------------------------


class TestCalculateBayesianRiskV2:
    def test_signal_objects_with_recent_timestamps(self):
        """V2 API: signals as list of dicts with metadata."""
        signals = [
            {"name": "CTO_departure", "timestamp": _recent(1), "source": "LinkedIn"},
            {"name": "CTO_departure", "timestamp": _recent(2), "source": "TechCrunch"},
        ]
        risk = calculate_bayesian_risk.invoke({"symptoms": signals})
        assert isinstance(risk, float)
        assert 0.0 <= risk <= 1.0

    def test_single_source_below_threshold_returns_zero(self):
        """Only 1 unique source → multi-source threshold not met → no signal contribution."""
        signals = [
            {"name": "CTO_departure", "timestamp": _recent(1), "source": "LinkedIn"},
        ]
        risk = calculate_bayesian_risk.invoke({"symptoms": signals})
        # With threshold=2 and only 1 source, signal is excluded → prior only (~0.2)
        assert isinstance(risk, float)
        assert risk < 0.5  # Should be near prior, not inflated

    def test_two_sources_meet_threshold(self):
        """2 independent sources → threshold met → signal included → higher risk."""
        signals = [
            {"name": "CTO_departure", "timestamp": _recent(1), "source": "LinkedIn"},
            {"name": "CTO_departure", "timestamp": _recent(1), "source": "Glassdoor"},
        ]
        risk_two_sources = calculate_bayesian_risk.invoke({"symptoms": signals})

        signals_one_source = [
            {"name": "CTO_departure", "timestamp": _recent(1), "source": "LinkedIn"},
        ]
        risk_one_source = calculate_bayesian_risk.invoke({"symptoms": signals_one_source})

        assert risk_two_sources > risk_one_source

    def test_old_signals_effectively_excluded(self):
        """Signals older than decay window contribute negligibly."""
        signals_old = [
            {"name": "CTO_departure", "timestamp": _old(24), "source": "LinkedIn"},
            {"name": "CTO_departure", "timestamp": _old(24), "source": "Glassdoor"},
        ]
        signals_recent = [
            {"name": "CTO_departure", "timestamp": _recent(1), "source": "LinkedIn"},
            {"name": "CTO_departure", "timestamp": _recent(2), "source": "Glassdoor"},
        ]
        risk_old = calculate_bayesian_risk.invoke({"symptoms": signals_old})
        risk_recent = calculate_bayesian_risk.invoke({"symptoms": signals_recent})
        # Recent signals should produce higher risk
        assert risk_recent > risk_old

    def test_backward_compat_string_list(self):
        """V1 API: list of strings must still work."""
        symptoms = ["CTO_departure", "R&D_drop"]
        risk = calculate_bayesian_risk.invoke({"symptoms": symptoms})
        assert isinstance(risk, float)
        assert risk > 0.5  # Both symptoms present → high risk

    def test_backward_compat_no_symptoms(self):
        risk = calculate_bayesian_risk.invoke({"symptoms": []})
        assert isinstance(risk, float)
        assert 0.19 < risk < 0.21  # Prior only

    def test_backward_compat_unknown_symptoms(self):
        risk = calculate_bayesian_risk.invoke({"symptoms": ["Unknown_X", "Unknown_Y"]})
        assert isinstance(risk, float)
        assert 0.19 < risk < 0.21  # Unknown symptoms → prior only

    def test_positive_signal_weight_can_lower_source_requirement(self, tmp_path, monkeypatch):
        import src.tools.builtins.bayesian_inference as mod

        fb = tmp_path / "bayesian_feedback.json"
        fb.write_text(json.dumps({"signal_weights": {"CTO_departure": 1.0}}), encoding="utf-8")
        monkeypatch.setattr(mod, "_FEEDBACK_FILE", fb)

        signals = [
            {"name": "CTO_departure", "timestamp": _recent(1), "source": "LinkedIn"},
        ]
        risk = calculate_bayesian_risk.invoke({"symptoms": signals})
        assert risk > 0.5

    def test_negative_signal_weight_can_raise_source_requirement(self, tmp_path, monkeypatch):
        import src.tools.builtins.bayesian_inference as mod

        fb = tmp_path / "bayesian_feedback.json"
        fb.write_text(json.dumps({"signal_weights": {"CTO_departure": -0.75}}), encoding="utf-8")
        monkeypatch.setattr(mod, "_FEEDBACK_FILE", fb)

        signals = [
            {"name": "CTO_departure", "timestamp": _recent(1), "source": "LinkedIn"},
            {"name": "CTO_departure", "timestamp": _recent(1), "source": "Glassdoor"},
        ]
        risk = calculate_bayesian_risk.invoke({"symptoms": signals})
        assert risk < 0.5
