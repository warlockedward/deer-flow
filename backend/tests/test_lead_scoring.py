from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config.paths import Paths
from src.gateway.routers import leads as leads_router
from src.tools.builtins.lead_scoring import compute_lead_score


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _write_industry(tmp_path, name: str) -> None:
    (tmp_path / "industry_maps").mkdir(parents=True, exist_ok=True)
    (tmp_path / "industry_maps" / f"{name}.json").write_text(
        """
{
  "industry": "test_industry",
  "benchmarks": {"avg_pe_ratio": 20.0},
  "industry_mapping": {},
  "logic_mapping": {},
  "signals": {"decay_rate_months": 6, "multi_source_threshold": 2},
  "confidence": {"min_verified_symptoms": 2, "min_sources_total": 2, "min_dimensions": 1},
  "causal_relationships": [{"cause": "Management_Gap", "effect": "CTO_departure", "strength": "medium"}],
  "conflict_rules": []
}
""".strip(),
        encoding="utf-8",
    )


def test_high_value_contract_triggers_hitl_and_category_a(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    lead = {
        "industry": "test_industry",
        "estimated_contract_value": 1_200_000,
        "signals": [
            {"name": "CTO_departure", "timestamp": _iso(datetime.now(tz=UTC)), "source": "s1", "dimension": "talent"},
            {"name": "CTO_departure", "timestamp": _iso(datetime.now(tz=UTC)), "source": "s2", "dimension": "talent"},
        ],
    }

    result = compute_lead_score(lead=lead, client="action_education")
    assert result.hitl_required is True
    assert result.category == "A"
    assert "HIGH_VALUE_CONTRACT" in result.reasons


def test_cross_validation_increases_logic_confidence(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    now = datetime.now(tz=UTC)
    lead_single = {
        "industry": "test_industry",
        "signals": [{"name": "CTO_departure", "timestamp": _iso(now), "source": "s1", "dimension": "talent"}],
    }
    lead_multi = {
        "industry": "test_industry",
        "signals": [
            {"name": "CTO_departure", "timestamp": _iso(now), "source": "s1", "dimension": "talent"},
            {"name": "CTO_departure", "timestamp": _iso(now), "source": "s2", "dimension": "talent"},
        ],
    }

    r1 = compute_lead_score(lead=lead_single, client="action_education")
    r2 = compute_lead_score(lead=lead_multi, client="action_education")
    assert r2.components["logic_confidence"] > r1.components["logic_confidence"]


def test_time_decay_drops_old_signals(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    old = datetime.now(tz=UTC) - timedelta(days=200)
    lead = {
        "industry": "test_industry",
        "signals": [
            {"name": "CTO_departure", "timestamp": _iso(old), "source": "s1", "dimension": "talent"},
            {"name": "CTO_departure", "timestamp": _iso(old), "source": "s2", "dimension": "talent"},
        ],
    }

    result = compute_lead_score(lead=lead, client="action_education")
    assert result.components["recency_time_decay"] == 0.0


def test_conflict_index_detects_innovation_vs_low_rd(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    now = datetime.now(tz=UTC)
    lead = {
        "industry": "test_industry",
        "vision_statement": "We are innovation-driven and will lead with R&D",
        "investment_flows": {"r_and_d_ratio": 0.02},
        "signals": [
            {"name": "CTO_departure", "timestamp": _iso(now), "source": "s1", "dimension": "talent"},
            {"name": "CTO_departure", "timestamp": _iso(now), "source": "s2", "dimension": "talent"},
        ],
    }

    result = compute_lead_score(lead=lead, client="action_education")
    assert result.components["conflict_index"] >= 0.8
    assert "VISION_BEHAVIOR_CONFLICT" in result.reasons


def test_leads_score_api_returns_result(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    app = FastAPI()
    app.include_router(leads_router.router)
    with TestClient(app) as client:
        resp = client.post(
            "/api/leads/score",
            json={
                "client": "action_education",
                "lead": {
                    "industry": "test_industry",
                    "estimated_contract_value": 10_000,
                    "signals": [
                        {"name": "CTO_departure", "timestamp": _iso(datetime.now(tz=UTC)), "source": "s1", "dimension": "talent"},
                        {"name": "CTO_departure", "timestamp": _iso(datetime.now(tz=UTC)), "source": "s2", "dimension": "talent"},
                    ],
                },
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "total_score" in body
        assert "category" in body
        assert "hitl_required" in body
        assert "components" in body


def test_leads_feedback_api_updates_conversion_weight(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    fb = tmp_path / "bayesian_feedback.json"
    monkeypatch.setattr("src.tools.builtins.lead_scoring._FEEDBACK_FILE", fb)
    monkeypatch.setattr("src.tools.builtins.bayesian_inference._FEEDBACK_FILE", fb)

    app = FastAPI()
    app.include_router(leads_router.router)
    with TestClient(app) as client:
        resp1 = client.post("/api/leads/feedback", json={"client": "action_education", "industry": "test_industry", "outcome": "positive"})
        assert resp1.status_code == 200
        assert abs(resp1.json()["conversion_path_weight"] - 1.02) < 1e-9

        resp2 = client.post("/api/leads/feedback", json={"client": "action_education", "industry": "test_industry", "outcome": "positive"})
        assert resp2.status_code == 200
        assert abs(resp2.json()["conversion_path_weight"] - 1.04) < 1e-9

        resp3 = client.post("/api/leads/feedback", json={"client": "action_education", "industry": "test_industry", "outcome": "negative"})
        assert resp3.status_code == 200
        assert abs(resp3.json()["conversion_path_weight"] - 1.02) < 1e-9


def test_leads_feedback_api_updates_signal_weights(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    fb = tmp_path / "bayesian_feedback.json"
    monkeypatch.setattr("src.tools.builtins.lead_scoring._FEEDBACK_FILE", fb)
    monkeypatch.setattr("src.tools.builtins.bayesian_inference._FEEDBACK_FILE", fb)

    app = FastAPI()
    app.include_router(leads_router.router)
    with TestClient(app) as client:
        resp = client.post(
            "/api/leads/feedback",
            json={
                "client": "action_education",
                "industry": "test_industry",
                "outcome": "positive",
                "signal_names": ["CTO_departure"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["signal_updates"] == {"CTO_departure": 0.05}

    data = fb.read_text(encoding="utf-8")
    assert "signal_weights" in data
    assert "CTO_departure" in data


def test_leads_feedback_rejects_unknown_signal_names(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    fb = tmp_path / "bayesian_feedback.json"
    monkeypatch.setattr("src.tools.builtins.lead_scoring._FEEDBACK_FILE", fb)
    monkeypatch.setattr("src.tools.builtins.bayesian_inference._FEEDBACK_FILE", fb)

    app = FastAPI()
    app.include_router(leads_router.router)
    with TestClient(app) as client:
        resp = client.post(
            "/api/leads/feedback",
            json={
                "client": "action_education",
                "industry": "test_industry",
                "outcome": "positive",
                "signal_names": ["Not_A_Real_Signal"],
            },
        )
        assert resp.status_code == 422
