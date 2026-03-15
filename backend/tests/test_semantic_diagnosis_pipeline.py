import json
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config.paths import Paths


def _now() -> str:
    return datetime.now(tz=UTC).date().isoformat()


class FakeRunner:
    def __init__(self, outputs: dict[str, dict | str]):
        self.outputs = outputs
        self.calls: list[str] = []
        self.prompts: dict[str, str] = {}

    def run(self, *, subagent_name: str, prompt: str, thread_id: str, model_name: str | None) -> str:
        self.calls.append(subagent_name)
        self.prompts[subagent_name] = prompt
        out = self.outputs[subagent_name]
        if isinstance(out, str):
            return out
        return json.dumps(out)


def _write_industry(tmp_path, name: str, extra: dict | None = None) -> None:
    (tmp_path / "industry_maps").mkdir(parents=True, exist_ok=True)
    payload = {
        "industry": name,
        "benchmarks": {"avg_gross_margin": 0.2},
        "industry_mapping": {},
        "logic_mapping": {"Management_Gap": {"benchmark_deviation_threshold": 0.3, "benchmark_factors": ["avg_gross_margin"], "conflict_amplifier": 1.5}},
        "signals": {"decay_rate_months": 12, "multi_source_threshold": 2},
        "failure_boundaries": {
            "B": {
                "min_sources": 2,
                "min_confidence": 0.6,
                "min_business_exposure": 0.4,
                "environment_signal_names": [
                    "Industry_Access_Restricted_Suddenly",
                    "Industry_Access_Catalog_Changed",
                    "Import_Export_Tariff_Adjusted",
                    "Regulatory_Directive_Issued",
                ],
            }
        },
        "policy_shock": {"expansion_signal_decay_days": 30, "expansion_oriented_signals": ["Hiring_Expansion", "Capex_Expansion", "New_Site_Planning"]},
        "trigger_rules": [
            {
                "signal": "Policy_Mutation_Alert + High_Business_Exposure",
                "threshold": "Critical",
                "inference_chain": "Logic_Recalibration -> Compliance_Risk -> Strategic_Pivot",
                "emba_module": "Strategic_Focus_101",
                "action_script": "Generate_Report: 'Policy Shock Survival Guide'",
            }
        ],
        "confidence": {
            "threshold": 0.6,
            "min_verified_symptoms": 1,
            "min_sources_total": 2,
            "min_dimensions": 1,
            "benchmark_indifference_epsilon": 0.05,
            "signal_dimensions": {"CTO_departure": "talent"},
        },
        "causal_relationships": [{"cause": "Management_Gap", "effect": "CTO_departure", "strength": "medium"}],
        "conflict_rules": [],
    }
    if isinstance(extra, dict):
        payload.update(extra)
    (tmp_path / "industry_maps" / f"{name}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_pipeline_blocks_when_benchmarks_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    runner = FakeRunner(
        {
            "sensor_agent": {"signals": [{"name": "CTO_departure", "timestamp": _now(), "source": "s1", "value": "1"}], "benchmarks": {}},
        }
    )

    from src.subagents.semantic_diagnosis_pipeline import run_semantic_diagnosis_pipeline

    result = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner)
    assert result["hitl_decision"] == "mandatory"
    assert result["allow_briefing"] is False
    assert "MISSING_BENCHMARKS" in result["reasons"]


def test_pipeline_boundary_b_returns_pause_manifesto(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    runner = FakeRunner(
        {
            "sensor_agent": {
                "signals": [],
                "benchmarks": {},
                "environment_events": [
                    {
                        "boundary": "B",
                        "boundary_id": "B-2026-Q1-POLICY-SHIFT-CHN-FINTECH",
                        "triggered_at": "2026-03-15T12:32:18+08:00",
                        "sources": ["Shanghai Stock Exchange", "Baidu Index"],
                        "evidence_summary": [
                            "Policy notice issued (2026-03-14)",
                            "Compliance costs rose sharply YoY",
                            "Keyword search volume surged within 24h",
                        ],
                        "affected_ontology_nodes": ["licence moat"],
                        "confidence": 0.82,
                        "business_exposure": 0.5,
                        "provisional_insight": {
                            "type": "contextual_anchor",
                            "content": "Policy baseline shifted; priors invalidated; awaiting human validation.",
                            "source_lesson": "EMBA-Crisis-Module-07-FirstPrinciplesReanchor",
                            "confidence": 0.62,
                        },
                    }
                ],
            }
        }
    )

    from src.subagents.semantic_diagnosis_pipeline import run_semantic_diagnosis_pipeline

    result = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner)
    assert result["allow_briefing"] is False
    assert result["hitl_decision"] == "mandatory"
    assert "BOUNDARY_B_ACTIVE" in result["reasons"]
    assert result["briefing"] is None
    assert result["conflicts"] is None
    assert result["anomalies"] is None
    assert result["pause_manifesto"]["status"] == "boundary_B_active"
    assert result["pause_manifesto"]["boundary_id"] == "B-2026-Q1-POLICY-SHIFT-CHN-FINTECH"
    assert result["pause_manifesto"]["human_intervention_required"] is True
    assert "review_packet" in result
    assert "drafts" in result


def test_pipeline_boundary_b_allows_rerun_after_hitl_seal(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    boundary_event = {
        "name": "Industry_Access_Restricted_Suddenly",
        "boundary": "B",
        "boundary_id": "B-2026-POLICY-SHOCK",
        "triggered_at": "2026-03-15T12:32:18+08:00",
        "sources": ["SourceA", "SourceB"],
        "evidence_summary": ["Access catalog tightened", "Multiple regulator signals"],
        "confidence": 0.82,
        "business_exposure": 0.5,
    }

    runner1 = FakeRunner({"sensor_agent": {"signals": [], "benchmarks": {}, "environment_events": [boundary_event]}})
    from src.subagents.semantic_diagnosis_pipeline import resolve_hitl_task, run_semantic_diagnosis_pipeline

    first = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner1)
    assert first["hitl_decision"] == "mandatory"
    task_id = first["hitl_task_id"]

    resolve_hitl_task(task_id=task_id, reviewer="r1", decision="approve", review_notes="ok", seal_logical_gap=True, patch={"policy": "ok"})

    runner2 = FakeRunner(
        {
            "sensor_agent": {
                "signals": [
                    {"name": "Hiring_Expansion", "timestamp": "2025-12-01", "source": "s0", "value": "plan"},
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s1", "value": "1"},
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s2", "value": "1"},
                ],
                "benchmarks": {"avg_gross_margin": 0.2},
                "environment_events": [boundary_event],
            },
            "interpreter_agent": {"symptoms": [], "features": []},
            "anomaly_detection_agent": {"exceptions": [], "verdict": "main inference chain is sound"},
            "composer_agent": "briefing",
            "distribution_agent": {
                "primary_channel": "email",
                "send_window_local": "next business day 09:30-11:00",
                "final_copy": {"subject": "s", "body": "b"},
                "guardrails": ["permission_based", "opt_out_present", "no_sales_pitch"],
                "tracking": {"client": "c", "industry": "test_industry", "signal_names": ["CTO_departure"]},
            },
        }
    )

    second = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner2, hitl_task_id=task_id)
    assert second["hitl_decision"] == "none"
    assert second["allow_briefing"] is True
    assert second["briefing"] == "briefing"
    assert second["policy_shock"]["active"] is True
    assert second["policy_shock"]["mode"] is True
    assert "BOUNDARY_B_ACTIVE" in second["reasons"]
    assert "POLICY_SHOCK_DECAY_APPLIED" in second["reasons"]

    ip = runner2.prompts.get("interpreter_agent") or ""
    assert "Logic_Recalibration -> Compliance_Risk -> Strategic_Pivot" in ip


def test_pipeline_boundary_b_not_confirmed_with_noise_sources(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    runner = FakeRunner(
        {
            "sensor_agent": {
                "signals": [],
                "benchmarks": {},
                "environment_events": [
                    {
                        "boundary": "B",
                        "boundary_id": "B-TEST",
                        "triggered_at": "2026-03-15T12:32:18+08:00",
                        "sources": ["press release", "Baidu Index"],
                        "evidence_summary": ["x"],
                        "confidence": 0.9,
                    }
                ],
            }
        }
    )

    from src.subagents.semantic_diagnosis_pipeline import run_semantic_diagnosis_pipeline

    result = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner)
    assert "BOUNDARY_B_ACTIVE" not in result["reasons"]
    assert "NO_SIGNALS" in result["reasons"]


def test_pipeline_blocks_on_high_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    runner = FakeRunner(
        {
            "sensor_agent": {
                "signals": [
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s1", "value": "1"},
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s2", "value": "1"},
                ],
                "benchmarks": {"avg_gross_margin": 0.2},
            },
            "interpreter_agent": {"symptoms": [{"symptom": "X", "severity": "high", "triggered_by": ["CTO_departure"], "evidence": "e"}], "features": []},
            "anomaly_detection_agent": {"exceptions": [], "verdict": "main inference chain is sound"},
        }
    )

    from src.subagents.semantic_diagnosis_pipeline import run_semantic_diagnosis_pipeline

    result = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner)
    assert result["hitl_decision"] == "mandatory"
    assert result["allow_briefing"] is False
    assert "CONFLICT_DETECTED" in result["reasons"]


def test_pipeline_blocks_on_anomaly_reexamine(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    runner = FakeRunner(
        {
            "sensor_agent": {
                "signals": [
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s1", "value": "1"},
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s2", "value": "1"},
                ],
                "benchmarks": {"avg_gross_margin": 0.2},
            },
            "interpreter_agent": {"symptoms": [], "features": []},
            "anomaly_detection_agent": {
                "exceptions": [
                    {"exception": "ex", "standard_pattern": "sp", "actual_context": "ac", "recommendation": "re-examine"},
                ]
            },
        }
    )

    from src.subagents.semantic_diagnosis_pipeline import run_semantic_diagnosis_pipeline

    result = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner)
    assert result["hitl_decision"] == "mandatory"
    assert result["allow_briefing"] is False
    assert "ANOMALY_REEXAMINE" in result["reasons"]


def test_pipeline_blocks_on_anomaly_bypass_template_and_emits_override_recommendation(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    override = {"bypass_gates": ["circuit_breaker"], "rationale": "context-specific exception", "required_evidence": ["verify unit economics"]}
    runner = FakeRunner(
        {
            "sensor_agent": {
                "signals": [
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s1", "value": "1"},
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s2", "value": "1"},
                ],
                "benchmarks": {"avg_gross_margin": 0.2},
            },
            "interpreter_agent": {"symptoms": [], "features": []},
            "anomaly_detection_agent": {
                "exceptions": [
                    {
                        "title": "Exception",
                        "recommendation": "bypass_template",
                        "evidence": "e",
                        "why_template_fails": "w",
                        "alternate_hypothesis": "h",
                        "what_to_verify_next": ["x"],
                        "override_recommendation": override,
                    }
                ],
                "verdict": "exceptions_found",
            },
        }
    )

    from src.subagents.semantic_diagnosis_pipeline import get_hitl_task, run_semantic_diagnosis_pipeline

    result = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner)
    assert result["hitl_decision"] == "mandatory"
    assert result["allow_briefing"] is False
    assert "ANOMALY_OVERRIDE_RECOMMENDED" in result["reasons"]

    ap = runner.prompts.get("anomaly_detection_agent") or ""
    assert "Benchmarks:" in ap
    assert "PolicyShock:" in ap
    assert "TriggerRules:" in ap

    task = get_hitl_task(str(result.get("hitl_task_id") or ""))
    assert isinstance(task, dict)
    assert task.get("override_recommendation") == override
    rp = result.get("review_packet") or {}
    assert (rp.get("analysis_bundle") or {}).get("override_recommendation") == override


def test_pipeline_runs_composer_when_all_gates_pass(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    runner = FakeRunner(
        {
            "sensor_agent": {
                "signals": [
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s1", "value": "1"},
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s2", "value": "1"},
                ],
                "benchmarks": {"avg_gross_margin": 0.2},
            },
            "interpreter_agent": {"symptoms": [], "features": []},
            "anomaly_detection_agent": {"exceptions": [], "verdict": "main inference chain is sound"},
            "composer_agent": "briefing",
            "distribution_agent": {
                "primary_channel": "email",
                "send_window_local": "next business day 09:30-11:00",
                "final_copy": {"subject": "s", "body": "b"},
                "guardrails": ["permission_based", "opt_out_present", "no_sales_pitch"],
                "tracking": {"client": "c", "industry": "test_industry", "signal_names": ["CTO_departure"]},
            },
        }
    )

    from src.subagents.semantic_diagnosis_pipeline import run_semantic_diagnosis_pipeline

    result = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner)
    assert result["hitl_decision"] == "none"
    assert result["allow_briefing"] is True
    assert result["briefing"] == "briefing"
    assert "review_packet" in result
    assert "drafts" in result
    assert isinstance(result.get("outreach_plan"), dict)
    assert isinstance((result.get("review_packet") or {}).get("distribution_bundle"), dict)
    assert runner.calls == ["sensor_agent", "interpreter_agent", "anomaly_detection_agent", "composer_agent", "distribution_agent"]


def test_pipeline_includes_industry_overrides_in_prompts(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(
        tmp_path,
        "test_industry",
        extra={
            "trigger_rules": [{"id": "tr1", "when": "X"}],
            "inference_chain": [{"id": "ic1", "then": "Y"}],
            "action_script": {"title": "AS1", "next": ["do_1"]},
        },
    )

    runner = FakeRunner(
        {
            "sensor_agent": {
                "signals": [
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s1", "value": "1"},
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s2", "value": "1"},
                ],
                "benchmarks": {"avg_gross_margin": 0.2},
            },
            "interpreter_agent": {"symptoms": [], "features": []},
            "anomaly_detection_agent": {"exceptions": [], "verdict": "main inference chain is sound"},
            "composer_agent": "briefing",
            "distribution_agent": {
                "primary_channel": "email",
                "send_window_local": "next business day 09:30-11:00",
                "final_copy": {"subject": "s", "body": "b"},
                "guardrails": ["permission_based", "opt_out_present", "no_sales_pitch"],
                "tracking": {"client": "c", "industry": "test_industry", "signal_names": ["CTO_departure"]},
            },
        }
    )

    from src.subagents.semantic_diagnosis_pipeline import run_semantic_diagnosis_pipeline

    result = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner)
    assert result["hitl_decision"] == "none"
    assert result["allow_briefing"] is True

    ip = runner.prompts.get("interpreter_agent") or ""
    assert "TriggerRules:" in ip and "tr1" in ip
    assert "InferenceChain:" in ip and "ic1" in ip

    cp = runner.prompts.get("composer_agent") or ""
    assert "ActionScript:" in cp and "AS1" in cp


def test_api_diagnosis_run_calls_shared_pipeline(monkeypatch):
    from src.gateway.routers import diagnosis

    app = FastAPI()
    app.include_router(diagnosis.router)

    called: dict = {}

    def _fake_run(**kwargs):
        called.update(kwargs)
        return {
            "success": True,
            "allow_briefing": False,
            "hitl_decision": "mandatory",
            "reasons": ["X"],
            "briefing": None,
            "review_packet": {"send_policy": "human_send_only"},
            "drafts": {"email": {"subject": "s", "body": "b"}},
        }

    monkeypatch.setattr(diagnosis, "run_semantic_diagnosis_pipeline", _fake_run)

    with TestClient(app) as client:
        resp = client.post(
            "/api/diagnosis/run",
            json={
                "thread_id": "t1",
                "company_name": "c",
                "industry": "test_industry",
                "model_name": "m1",
                "hitl_approved": True,
                "reviewer": "r",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "review_packet" in resp.json()
        assert "drafts" in resp.json()

    assert called == {
        "thread_id": "t1",
        "company_name": "c",
        "industry": "test_industry",
        "model_name": "m1",
        "hitl_approved": True,
        "reviewer": "r",
        "hitl_task_id": None,
    }


def test_hitl_task_lifecycle_and_seal_enables_briefing(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    from src.subagents.semantic_diagnosis_pipeline import resolve_hitl_task, run_semantic_diagnosis_pipeline

    runner = FakeRunner(
        {
            "sensor_agent": {
                "signals": [
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s1", "value": "1"},
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s2", "value": "1"},
                ],
                "benchmarks": {"avg_gross_margin": 0.2},
                "environment_events": [],
            },
            "interpreter_agent": {"symptoms": [{"symptom": "X", "severity": "high", "triggered_by": ["RD_drop"], "evidence": "e"}], "features": []},
            "anomaly_detection_agent": {"exceptions": [], "verdict": "main inference chain is sound"},
            "composer_agent": "briefing",
            "distribution_agent": {
                "primary_channel": "email",
                "send_window_local": "next business day 09:30-11:00",
                "final_copy": {"subject": "s", "body": "b"},
                "guardrails": ["permission_based", "opt_out_present", "no_sales_pitch"],
                "tracking": {"client": "c", "industry": "test_industry", "signal_names": ["CTO_departure"]},
            },
        }
    )

    first = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner)
    assert first["hitl_decision"] == "mandatory"
    task_id = first.get("hitl_task_id")
    assert isinstance(task_id, str) and task_id

    resolve_hitl_task(task_id=task_id, reviewer="r1", decision="approve", review_notes="ok", seal_logical_gap=True, patch={"add": "x"})

    second = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner, hitl_task_id=task_id)
    assert second["hitl_decision"] == "none"
    assert second["allow_briefing"] is True
    assert second["briefing"] == "briefing"
    assert isinstance(second.get("review_packet"), dict)
    assert isinstance(second.get("drafts"), dict)


def test_api_hitl_task_endpoints_work(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    _write_industry(tmp_path, "test_industry")

    runner = FakeRunner(
        {
            "sensor_agent": {
                "signals": [
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s1", "value": "1"},
                    {"name": "CTO_departure", "timestamp": _now(), "source": "s2", "value": "1"},
                ],
                "benchmarks": {"avg_gross_margin": 0.2},
                "environment_events": [],
            },
            "interpreter_agent": {"symptoms": [{"symptom": "X", "severity": "high", "triggered_by": ["RD_drop"], "evidence": "e"}], "features": []},
            "anomaly_detection_agent": {"exceptions": [], "verdict": "main inference chain is sound"},
            "composer_agent": "briefing",
        }
    )

    from src.subagents.semantic_diagnosis_pipeline import run_semantic_diagnosis_pipeline

    result = run_semantic_diagnosis_pipeline(thread_id="t1", company_name="c", industry="test_industry", runner=runner)
    task_id = result.get("hitl_task_id")
    assert isinstance(task_id, str) and task_id

    from src.gateway.routers import diagnosis

    app = FastAPI()
    app.include_router(diagnosis.router)
    with TestClient(app) as client:
        resp1 = client.get("/api/diagnosis/hitl/tasks", params={"status": "pending"})
        assert resp1.status_code == 200
        pending = resp1.json()["tasks"]
        assert any(t.get("task_id") == task_id for t in pending)

        resp2 = client.post(f"/api/diagnosis/hitl/tasks/{task_id}/claim", json={"reviewer": "r1"})
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "claimed"

        resp3 = client.post(
            f"/api/diagnosis/hitl/tasks/{task_id}/resolve",
            json={"reviewer": "r1", "decision": "approve", "review_notes": "ok", "seal_logical_gap": True, "patch": {"k": 1}},
        )
        assert resp3.status_code == 200
        assert resp3.json()["status"] == "resolved"
        assert resp3.json()["decision"] == "approve"

        resp4 = client.get(f"/api/diagnosis/hitl/tasks/{task_id}")
        assert resp4.status_code == 200
        assert resp4.json()["task_id"] == task_id


def test_tool_run_semantic_diagnosis_calls_shared_pipeline(monkeypatch):
    from src.tools.builtins import bayesian_inference

    called: dict = {}

    def _fake_run(**kwargs):
        called.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr("src.subagents.semantic_diagnosis_pipeline.run_semantic_diagnosis_pipeline", _fake_run)

    runtime = SimpleNamespace(
        context={"thread_id": "t1"},
        config={"metadata": {"model_name": "m1"}},
        state={},
    )

    out = bayesian_inference.run_semantic_diagnosis.func(
        runtime=runtime,
        company_name="c",
        industry="test_industry",
        hitl_approved=True,
        reviewer="r",
    )
    assert out == {"ok": True}
    assert called == {
        "thread_id": "t1",
        "company_name": "c",
        "industry": "test_industry",
        "model_name": "m1",
        "hitl_approved": True,
        "reviewer": "r",
    }
