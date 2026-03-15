import asyncio
import json
from unittest.mock import MagicMock

import pytest

from src.config.paths import Paths
from src.gateway.routers import ontology


def test_update_run_prompt_requests_causal_vectors_and_rar_anchors(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))

    captured: dict = {}
    fake_model = MagicMock()

    calls: list[str] = []

    def _invoke(prompt: str):
        calls.append(prompt)
        if "prompt" not in captured:
            captured["prompt"] = prompt
        if len(calls) == 1:
            return MagicMock(
                content=json.dumps(
                    {
                        "ontology": {"version": "2", "nodes": [{"id": "b", "title": "B", "source_quote": "p3"}], "edges": []},
                        "industry_overrides": {},
                    }
                )
            )
        if len(calls) == 2:
            return MagicMock(
                content=json.dumps(
                    {
                        "symptoms": [{"symptom": "X", "severity": "high", "triggered_by": ["RD_drop"], "evidence": "e"}],
                        "features": [],
                    }
                )
            )
        return MagicMock(content=json.dumps({"exceptions": [], "verdict": "main inference chain is sound"}))

    fake_model.invoke.side_effect = _invoke
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content", apply=False)
    result = asyncio.run(ontology.run_update(req))

    assert result.success is True
    p = captured.get("prompt") or ""
    assert "Knowledge Deconstruction" in p
    assert "Phenomenon" in p and "Root Cause" in p and "Solution" in p
    assert "Strategy, Performance, Finance, Team, Marketing" in p
    assert "conflict_rules" in p
    assert "R&D" in p and "3%" in p


def test_update_run_rejects_edges_without_valid_section(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))

    fake_model = MagicMock()
    fake_model.invoke.return_value = MagicMock(
        content=json.dumps(
            {
                "ontology": {
                    "version": "2",
                    "nodes": [{"id": "a", "title": "A", "source_quote": "p1"}, {"id": "b", "title": "B", "source_quote": "p2"}],
                    "edges": [{"source": "a", "target": "b", "relation": "causes"}],
                },
                "industry_overrides": {},
            }
        )
    )
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content", apply=False)
    with pytest.raises(Exception) as e:
        asyncio.run(ontology.run_update(req))
    assert "section" in str(e.value).lower()


def test_update_run_rejects_edges_without_source_quote(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))

    fake_model = MagicMock()
    fake_model.invoke.return_value = MagicMock(
        content=json.dumps(
            {
                "ontology": {
                    "version": "2",
                    "nodes": [{"id": "a", "title": "A", "source_quote": "p1"}, {"id": "b", "title": "B", "source_quote": "p2"}],
                    "edges": [{"source": "a", "target": "b", "relation": "causes", "section": "Strategy"}],
                },
                "industry_overrides": {},
            }
        )
    )
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content", apply=False)
    with pytest.raises(Exception) as e:
        asyncio.run(ontology.run_update(req))
    assert "source_quote" in str(e.value).lower()


def test_update_run_persists_edge_keys_and_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))

    fake_model = MagicMock()
    fake_model.invoke.side_effect = [
        MagicMock(
            content=json.dumps(
                {
                    "ontology": {
                        "version": "2",
                        "nodes": [{"id": "a", "title": "A", "source_quote": "p1"}, {"id": "b", "title": "B", "source_quote": "p2"}],
                        "edges": [
                            {"source": "a", "target": "b", "relation": "phenomenon->root_cause", "section": "Strategy", "source_quote": "p_edge"},
                        ],
                    },
                    "industry_overrides": {},
                }
            )
        ),
        MagicMock(
            content=json.dumps(
                {
                    "symptoms": [{"symptom": "X", "severity": "high", "triggered_by": ["RD_drop"], "evidence": "e"}],
                    "features": [],
                }
            )
        ),
        MagicMock(content=json.dumps({"exceptions": [], "verdict": "main inference chain is sound"})),
    ]
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content p1 p2 p_edge", apply=True)
    result = asyncio.run(ontology.run_update(req))

    assert result.hitl_decision == "none"
    stored = json.loads((tmp_path / "ontology" / "condensed_emba.json").read_text(encoding="utf-8"))
    assert stored["edges"][0]["edge_key"]
    assert stored["edges"][0]["strength"] == "medium"


def test_update_run_requires_verbatim_source_quotes(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))

    fake_model = MagicMock()
    fake_model.invoke.side_effect = [
        MagicMock(
            content=json.dumps(
                {
                    "ontology": {
                        "version": "2",
                        "nodes": [{"id": "a", "title": "A", "source_quote": "p1"}, {"id": "b", "title": "B", "source_quote": "p2"}],
                        "edges": [{"source": "a", "target": "b", "relation": "causes", "section": "Strategy", "source_quote": "missing_quote"}],
                    },
                    "industry_overrides": {},
                }
            )
        ),
        MagicMock(content=json.dumps({"symptoms": [], "features": []})),
        MagicMock(content=json.dumps({"exceptions": [], "verdict": "main inference chain is sound"})),
    ]
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content with p1 and p2", apply=True)
    result = asyncio.run(ontology.run_update(req))

    assert result.hitl_decision == "mandatory"
    assert result.applied is False
    assert any("RAR_UNGROUNDED_EDGE_QUOTE" in c for c in result.conflicts)


def test_update_run_merges_partial_industry_override_into_executable_shape(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))

    fake_model = MagicMock()
    fake_model.invoke.side_effect = [
        MagicMock(
            content=json.dumps(
                {
                    "ontology": {"version": "2", "nodes": [{"id": "b", "title": "B", "source_quote": "p3"}], "edges": []},
                    "industry_overrides": {"high_tech": {"diagnostic_chains": [["CTO_departure", "Knowledge_Loss", "Talent_Echelon_Collapse"]]}},
                }
            )
        ),
        MagicMock(
            content=json.dumps(
                {
                    "symptoms": [{"symptom": "X", "severity": "high", "triggered_by": ["RD_drop"], "evidence": "e"}],
                    "features": [],
                }
            )
        ),
        MagicMock(content=json.dumps({"exceptions": [], "verdict": "main inference chain is sound"})),
    ]
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content p3", apply=True)
    result = asyncio.run(ontology.run_update(req))

    assert result.hitl_decision == "none"
    cfg = json.loads((tmp_path / "industry_maps" / "high_tech.json").read_text(encoding="utf-8"))
    assert isinstance(cfg.get("signals"), dict)
    assert isinstance(cfg.get("confidence"), dict)
    assert isinstance(cfg.get("conflict_rules"), list)
    assert isinstance(cfg.get("causal_relationships"), list)
    assert cfg.get("diagnostic_chains") == [["CTO_departure", "Knowledge_Loss", "Talent_Echelon_Collapse"]]


def test_update_run_returns_hitl_mandatory_when_confidence_low(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))

    fake_model = MagicMock()
    fake_model.invoke.side_effect = [
        MagicMock(
            content=json.dumps(
                {
                    "ontology": {"version": "2", "nodes": [{"id": "b", "title": "B"}], "edges": []},
                    "industry_overrides": {},
                }
            )
        ),
        MagicMock(content=json.dumps({"symptoms": [], "features": []})),
        MagicMock(content=json.dumps({"exceptions": [], "verdict": "main inference chain is sound"})),
    ]
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content", apply=True)
    result = asyncio.run(ontology.run_update(req))

    assert result.hitl_decision == "mandatory"
    assert result.applied is False


def test_update_run_applies_when_hitl_none(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))

    fake_model = MagicMock()
    fake_model.invoke.side_effect = [
        MagicMock(
            content=json.dumps(
                {
                    "ontology": {"version": "2", "nodes": [{"id": "b", "title": "B", "source_quote": "p3"}], "edges": []},
                    "industry_overrides": {"high_tech": {"industry": "high_tech", "override_marker": 9}},
                }
            )
        ),
        MagicMock(
            content=json.dumps(
                {
                    "symptoms": [{"symptom": "X", "severity": "high", "triggered_by": ["RD_drop"], "evidence": "e"}],
                    "features": [],
                }
            )
        ),
        MagicMock(content=json.dumps({"exceptions": [], "verdict": "main inference chain is sound"})),
    ]
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content p3", apply=True)
    result = asyncio.run(ontology.run_update(req))

    assert result.hitl_decision == "none"
    assert result.applied is True
    assert result.audit_id
    assert (tmp_path / "ontology" / "condensed_emba.json").exists()
    assert (tmp_path / "industry_maps" / "high_tech.json").exists()
    audit_path = tmp_path / "ontology" / "update_audit.jsonl"
    assert audit_path.exists()
    assert result.audit_id in audit_path.read_text(encoding="utf-8")


def test_update_run_does_not_apply_when_hitl_recommended_without_approval(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    (tmp_path / "ontology").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ontology" / "condensed_emba.json").write_text(json.dumps({"version": "1", "nodes": [{"id": "a", "title": "A"}], "edges": []}), encoding="utf-8")

    fake_model = MagicMock()
    fake_model.invoke.side_effect = [
        MagicMock(
            content=json.dumps(
                {
                    "ontology": {"version": "2", "nodes": [{"id": "a", "title": "A"}, {"id": "b", "title": "B", "source_quote": "p3"}], "edges": []},
                    "industry_overrides": {},
                }
            )
        ),
        MagicMock(
            content=json.dumps(
                {
                    "symptoms": [{"symptom": "X", "severity": "high", "triggered_by": ["RD_drop"], "evidence": "e"}],
                    "features": [],
                }
            )
        ),
        MagicMock(content=json.dumps({"exceptions": [], "verdict": "main inference chain is sound"})),
    ]
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content p3", apply=True)
    result = asyncio.run(ontology.run_update(req))

    assert result.hitl_decision == "recommended"
    assert result.applied is False


def test_update_run_applies_when_hitl_recommended_with_approval(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    (tmp_path / "ontology").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ontology" / "condensed_emba.json").write_text(json.dumps({"version": "1", "nodes": [{"id": "a", "title": "A"}], "edges": []}), encoding="utf-8")

    fake_model = MagicMock()
    fake_model.invoke.side_effect = [
        MagicMock(
            content=json.dumps(
                {
                    "ontology": {"version": "2", "nodes": [{"id": "a", "title": "A"}, {"id": "b", "title": "B", "source_quote": "p3"}], "edges": []},
                    "industry_overrides": {},
                }
            )
        ),
        MagicMock(
            content=json.dumps(
                {
                    "symptoms": [{"symptom": "X", "severity": "high", "triggered_by": ["RD_drop"], "evidence": "e"}],
                    "features": [],
                }
            )
        ),
        MagicMock(content=json.dumps({"exceptions": [], "verdict": "main inference chain is sound"})),
    ]
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content p3", apply=True, hitl_approved=True, reviewer="r1")
    result = asyncio.run(ontology.run_update(req))

    assert result.hitl_decision == "recommended"
    assert result.applied is True


def test_update_run_blocks_apply_when_conflict_stress_test_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))

    fake_model = MagicMock()
    fake_model.invoke.side_effect = [
        MagicMock(
            content=json.dumps(
                {
                    "ontology": {"version": "2", "nodes": [{"id": "b", "title": "B", "source_quote": "p3"}], "edges": []},
                    "industry_overrides": {"high_tech": {"industry": "high_tech", "override_marker": 9}},
                }
            )
        ),
        MagicMock(content=json.dumps({"symptoms": [], "features": []})),
        MagicMock(content=json.dumps({"exceptions": [], "verdict": "main inference chain is sound"})),
    ]
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content", apply=True)
    result = asyncio.run(ontology.run_update(req))

    assert result.hitl_decision == "mandatory"
    assert result.applied is False
    assert any("VALIDATION_CONFLICT_STRESS_FAIL" in c for c in result.conflicts)


def test_update_run_blocks_apply_when_anomaly_recommends_reexamine(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))

    fake_model = MagicMock()
    fake_model.invoke.side_effect = [
        MagicMock(
            content=json.dumps(
                {
                    "ontology": {"version": "2", "nodes": [{"id": "b", "title": "B", "source_quote": "p3"}], "edges": []},
                    "industry_overrides": {"high_tech": {"industry": "high_tech", "override_marker": 9}},
                }
            )
        ),
        MagicMock(
            content=json.dumps(
                {
                    "symptoms": [{"symptom": "X", "severity": "high", "triggered_by": ["RD_drop"], "evidence": "e"}],
                    "features": [],
                }
            )
        ),
        MagicMock(
            content=json.dumps(
                {
                    "exceptions": [
                        {
                            "exception": "ex",
                            "standard_pattern": "sp",
                            "actual_context": "ac",
                            "recommendation": "re-examine",
                        }
                    ]
                }
            )
        ),
    ]
    monkeypatch.setattr(ontology, "create_chat_model", lambda **kwargs: fake_model)

    req = ontology.OntologyUpdateRunRequest(thread_id="t1", content="new course content", apply=True)
    result = asyncio.run(ontology.run_update(req))

    assert result.hitl_decision == "mandatory"
    assert result.applied is False
    assert any("VALIDATION_ANOMALY_REEXAMINE" in c for c in result.conflicts)
