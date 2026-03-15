from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from src.config.paths import get_paths
from src.subagents import SubagentExecutor, get_subagent_config
from src.subagents.executor import SubagentStatus
from src.tools import get_available_tools
from src.tools.builtins.bayesian_inference import compute_circuit_breaker_state, load_industry_config

logger = logging.getLogger(__name__)

_BOUNDARY_B_HITL_DEADLINE_SECONDS = 300
_HITL_TASKS_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _hitl_tasks_path() -> Path:
    return get_paths().base_dir / "diagnosis" / "hitl_tasks.json"


def _load_hitl_tasks() -> dict:
    path = _hitl_tasks_path()
    if not path.exists():
        return {"version": _HITL_TASKS_VERSION, "tasks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": _HITL_TASKS_VERSION, "tasks": {}}
    if not isinstance(data, dict):
        return {"version": _HITL_TASKS_VERSION, "tasks": {}}
    if "version" not in data:
        data["version"] = _HITL_TASKS_VERSION
    if "tasks" not in data or not isinstance(data.get("tasks"), dict):
        data["tasks"] = {}
    return data


def _save_hitl_tasks(state: dict) -> None:
    if not isinstance(state, dict):
        state = {"version": _HITL_TASKS_VERSION, "tasks": {}}
    if "version" not in state:
        state["version"] = _HITL_TASKS_VERSION
    if "tasks" not in state or not isinstance(state.get("tasks"), dict):
        state["tasks"] = {}
    _atomic_write_json(_hitl_tasks_path(), state)


def _upsert_hitl_task(task: dict) -> dict:
    state = _load_hitl_tasks()
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        tasks = {}
        state["tasks"] = tasks
    tid = str(task.get("task_id") or task.get("audit_id") or "").strip()
    if not tid:
        raise ValueError("Missing task_id")
    task["task_id"] = tid
    if "created_at" not in task:
        task["created_at"] = _utc_now_iso()
    existing = tasks.get(tid)
    if isinstance(existing, dict):
        status = str(existing.get("status", "")).strip() or "pending"
        if status in {"claimed", "resolved"}:
            task["status"] = status
            if existing.get("reviewer"):
                task["reviewer"] = existing.get("reviewer")
            if existing.get("claimed_at"):
                task["claimed_at"] = existing.get("claimed_at")
            if existing.get("decision"):
                task["decision"] = existing.get("decision")
            if existing.get("resolved_at"):
                task["resolved_at"] = existing.get("resolved_at")
            if existing.get("review_notes"):
                task["review_notes"] = existing.get("review_notes")
            if existing.get("seal_logical_gap") is True:
                task["seal_logical_gap"] = True
            if isinstance(existing.get("patch"), dict):
                task["patch"] = existing.get("patch")
    tasks[tid] = task
    _save_hitl_tasks(state)
    return task


def get_hitl_task(task_id: str) -> dict | None:
    tid = (task_id or "").strip()
    if not tid:
        return None
    state = _load_hitl_tasks()
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return None
    t = tasks.get(tid)
    return t if isinstance(t, dict) else None


def list_hitl_tasks(*, status: str | None = None) -> list[dict]:
    state = _load_hitl_tasks()
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return []
    out: list[dict] = []
    for t in tasks.values():
        if not isinstance(t, dict):
            continue
        if status:
            if str(t.get("status", "")).strip() != status:
                continue
        out.append(t)
    out.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return out


def claim_hitl_task(*, task_id: str, reviewer: str) -> dict:
    tid = (task_id or "").strip()
    r = (reviewer or "").strip()
    if not tid:
        raise ValueError("Missing task_id")
    if not r:
        raise ValueError("Missing reviewer")
    state = _load_hitl_tasks()
    tasks = state.get("tasks")
    if not isinstance(tasks, dict) or tid not in tasks or not isinstance(tasks.get(tid), dict):
        raise FileNotFoundError(f"Unknown task_id: {tid}")
    task = dict(tasks[tid])
    if str(task.get("status", "")).strip() == "resolved":
        return task
    task["status"] = "claimed"
    task["reviewer"] = r
    task["claimed_at"] = _utc_now_iso()
    tasks[tid] = task
    _save_hitl_tasks(state)
    return task


def resolve_hitl_task(*, task_id: str, reviewer: str, decision: str, review_notes: str = "", seal_logical_gap: bool = True, patch: dict | None = None) -> dict:
    tid = (task_id or "").strip()
    r = (reviewer or "").strip()
    d = (decision or "").strip().lower()
    if not tid:
        raise ValueError("Missing task_id")
    if not r:
        raise ValueError("Missing reviewer")
    if d not in {"approve", "reject", "modify"}:
        raise ValueError("Invalid decision")
    state = _load_hitl_tasks()
    tasks = state.get("tasks")
    if not isinstance(tasks, dict) or tid not in tasks or not isinstance(tasks.get(tid), dict):
        raise FileNotFoundError(f"Unknown task_id: {tid}")
    task = dict(tasks[tid])
    task["status"] = "resolved"
    task["reviewer"] = r
    task["decision"] = d
    task["review_notes"] = str(review_notes or "").strip()
    task["seal_logical_gap"] = bool(seal_logical_gap) and d == "approve"
    if isinstance(patch, dict):
        task["patch"] = patch
    task["resolved_at"] = _utc_now_iso()
    tasks[tid] = task
    _save_hitl_tasks(state)
    return task


class SubagentRunner(Protocol):
    def run(self, *, subagent_name: str, prompt: str, thread_id: str, model_name: str | None) -> str: ...


class DefaultSubagentRunner:
    def run(self, *, subagent_name: str, prompt: str, thread_id: str, model_name: str | None) -> str:
        config = get_subagent_config(subagent_name)
        if config is None:
            raise ValueError(f"Unknown subagent: {subagent_name}")
        tools = get_available_tools(model_name=model_name, subagent_enabled=False)
        executor = SubagentExecutor(config=config, tools=tools, parent_model=model_name, thread_id=thread_id)
        result = executor.execute(prompt)
        if result.status != SubagentStatus.COMPLETED:
            raise RuntimeError(result.error or f"Subagent failed: {subagent_name}")
        return result.result or ""


def _strip_markdown_code_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        parts = t.split("\n")
        if len(parts) >= 2 and parts[-1].strip() == "```":
            return "\n".join(parts[1:-1]).strip()
    return t


def _parse_json(text: str) -> dict:
    raw = _strip_markdown_code_fence(text)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")
    return data


def _is_recent_enough(timestamp: str, decay_rate_months: float) -> bool:
    try:
        signal_date = datetime.fromisoformat(timestamp)
    except ValueError:
        return False
    age_months = (datetime.now(tz=UTC) - signal_date.replace(tzinfo=UTC)).days / 30.0
    return age_months <= decay_rate_months


def _sources_by_name(signals: list[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for s in signals:
        name = str(s.get("name", "")).strip()
        if not name:
            continue
        source = str(s.get("source", "unknown")).strip() or "unknown"
        out.setdefault(name, set()).add(source)
    return out


def _format_evidence_lines(signals: list[dict], *, limit: int = 4) -> list[str]:
    lines: list[str] = []
    for s in signals:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip()
        ts = str(s.get("timestamp", "")).strip()
        source = str(s.get("source", "")).strip() or "unknown"
        value = s.get("value")
        if not name:
            continue
        value_str = "" if value is None else str(value).strip()
        parts = [name]
        if ts:
            parts.append(ts)
        if value_str:
            parts.append(value_str)
        parts.append(source)
        lines.append(" - " + " | ".join(parts))
        if len(lines) >= limit:
            break
    return lines


def _draft_subject(company_name: str, signals: list[dict]) -> str:
    top = ""
    for s in signals:
        if not isinstance(s, dict):
            continue
        n = str(s.get("name", "")).strip()
        if n:
            top = n
            break
    if top:
        return f"Quick observation on {company_name} — {top}"
    return f"Quick observation on {company_name}"


def _build_review_packet(
    *,
    audit_id: str,
    thread_id: str,
    company_name: str,
    industry: str,
    model_name: str | None,
    hitl_decision: str,
    allow_briefing: bool,
    reasons: list[str],
    hitl_task_id: str | None,
    sealed_review: dict | None,
    signals: list[dict],
    benchmarks: dict,
    conflicts: dict | None,
    circuit_breaker: dict | None,
    anomalies: dict | None,
    override_recommendation: dict | None = None,
    policy_shock: dict | None = None,
) -> dict:
    evidence_lines = _format_evidence_lines(signals)
    checklist = [
        "Check whether the brief anchors to Condensed EMBA tools (e.g., first principles / role value chain).",
        "Verify each key conclusion is supported by at least 2 independent sources.",
        "Identify any missing causal vectors and patch them with domain common sense (logical sealing).",
        "Confirm anomalies/black-swan context and whether priors should be overridden.",
        "Confirm outreach is permission-based and includes an opt-out line.",
    ]
    return {
        "audit_id": audit_id,
        "thread_id": thread_id,
        "company_name": company_name,
        "industry": industry,
        "model_name": model_name,
        "hitl_decision": hitl_decision,
        "allow_briefing": bool(allow_briefing),
        "reasons": list(reasons),
        "hitl_task_id": hitl_task_id,
        "sealed_review": sealed_review,
        "evidence_bundle": {
            "signals": list(signals),
            "benchmarks": dict(benchmarks) if isinstance(benchmarks, dict) else {},
            "evidence_lines": evidence_lines,
        },
        "analysis_bundle": {
            "conflicts": conflicts,
            "circuit_breaker": circuit_breaker,
            "anomalies": anomalies,
            "override_recommendation": override_recommendation,
            "policy_shock": policy_shock,
        },
        "review_checklist": checklist,
        "send_policy": "human_send_only",
    }


def _build_human_send_drafts(*, company_name: str, industry: str, signals: list[dict], review_packet: dict) -> dict:
    evidence_lines = (review_packet.get("evidence_bundle") or {}).get("evidence_lines") if isinstance(review_packet.get("evidence_bundle"), dict) else None
    if not isinstance(evidence_lines, list):
        evidence_lines = _format_evidence_lines(signals)
    subject = _draft_subject(company_name, signals)

    evidence_block = "\n".join([str(x) for x in evidence_lines]) if evidence_lines else ""
    if evidence_block:
        evidence_block = "\n\nObserved public signals:\n" + evidence_block

    email_body = (
        f"Hello,\n\n"
        f"I’m reaching out with a short, evidence-based observation about {company_name} ({industry}). "
        "If this is not relevant or you’re not the right contact, feel free to ignore.\n"
        f"{evidence_block}\n\n"
        "If you’d like, I can share a 1‑page diagnostic note outlining: (1) observable anomaly, (2) causal hypothesis, "
        "(3) what to verify next. No pitches.\n\n"
        "If you prefer no follow-ups, reply with “no” and I won’t contact you again.\n"
    ).strip()

    linkedin_body = (
        f"Hi — quick, evidence-based observation on {company_name} ({industry}). "
        "If useful, I can share a 1‑page diagnostic note (no pitches). "
        "If you’d rather not receive follow-ups, tell me and I’ll stop."
    ).strip()

    internal_note = (
        f"Human-send-only draft generated from review_packet audit_id={str(review_packet.get('audit_id') or '')}. "
        "Verify recipients/consent and re-check evidence before sending."
    ).strip()

    return {
        "email": {"subject": subject, "body": email_body},
        "linkedin": {"body": linkedin_body},
        "internal_note": internal_note,
    }


def _default_outreach_plan(*, company_name: str, industry: str, signals: list[dict], drafts: dict) -> dict:
    email = drafts.get("email") if isinstance(drafts, dict) else None
    linkedin = drafts.get("linkedin") if isinstance(drafts, dict) else None
    email_copy = email if isinstance(email, dict) else {}
    linkedin_copy = linkedin if isinstance(linkedin, dict) else {}

    primary_channel = "email" if isinstance(email_copy.get("body"), str) else "linkedin"
    final_copy: dict
    if primary_channel == "email":
        final_copy = {
            "subject": str(email_copy.get("subject", "")).strip(),
            "body": str(email_copy.get("body", "")).strip(),
        }
    else:
        final_copy = {"body": str(linkedin_copy.get("body", "")).strip()}

    signal_names: list[str] = []
    for s in signals:
        if not isinstance(s, dict):
            continue
        n = str(s.get("name", "")).strip()
        if n:
            signal_names.append(n)

    return {
        "primary_channel": primary_channel,
        "send_window_local": "next business day 09:30-11:00",
        "final_copy": final_copy,
        "guardrails": ["permission_based", "opt_out_present", "no_sales_pitch"],
        "tracking": {"client": company_name, "industry": industry, "signal_names": signal_names},
    }


def _coerce_outreach_plan(*, raw: object, company_name: str, industry: str, signals: list[dict], drafts: dict) -> dict:
    if not isinstance(raw, dict):
        return _default_outreach_plan(company_name=company_name, industry=industry, signals=signals, drafts=drafts)
    primary = str(raw.get("primary_channel", "")).strip().lower()
    primary_channel = primary if primary in {"email", "linkedin"} else "email"

    send_window_local = str(raw.get("send_window_local", "")).strip() or "next business day 09:30-11:00"
    final_copy_raw = raw.get("final_copy")
    final_copy: dict
    if isinstance(final_copy_raw, dict):
        final_copy = dict(final_copy_raw)
    else:
        final_copy = {}

    if primary_channel == "email":
        if not isinstance(final_copy.get("subject"), str):
            final_copy["subject"] = str((drafts.get("email") or {}).get("subject") if isinstance(drafts.get("email"), dict) else "").strip()
        if not isinstance(final_copy.get("body"), str):
            final_copy["body"] = str((drafts.get("email") or {}).get("body") if isinstance(drafts.get("email"), dict) else "").strip()
        final_copy = {"subject": str(final_copy.get("subject") or "").strip(), "body": str(final_copy.get("body") or "").strip()}
    else:
        if not isinstance(final_copy.get("body"), str):
            final_copy["body"] = str((drafts.get("linkedin") or {}).get("body") if isinstance(drafts.get("linkedin"), dict) else "").strip()
        final_copy = {"body": str(final_copy.get("body") or "").strip()}

    tracking_raw = raw.get("tracking")
    tracking: dict = tracking_raw if isinstance(tracking_raw, dict) else {}
    sn = tracking.get("signal_names")
    signal_names: list[str] = []
    if isinstance(sn, list):
        for x in sn:
            if isinstance(x, str) and x.strip():
                signal_names.append(x.strip())
    if not signal_names:
        for s in signals:
            if not isinstance(s, dict):
                continue
            n = str(s.get("name", "")).strip()
            if n:
                signal_names.append(n)

    client = str(tracking.get("client", "")).strip() or company_name
    ind = str(tracking.get("industry", "")).strip() or industry
    guardrails_raw = raw.get("guardrails")
    guardrails: list[str] = []
    if isinstance(guardrails_raw, list):
        for g in guardrails_raw:
            if isinstance(g, str) and g.strip():
                guardrails.append(g.strip())
    required = {"permission_based", "opt_out_present", "no_sales_pitch"}
    if not required.issubset(set(guardrails)):
        guardrails = ["permission_based", "opt_out_present", "no_sales_pitch"]

    return {
        "primary_channel": primary_channel,
        "send_window_local": send_window_local,
        "final_copy": final_copy,
        "guardrails": guardrails,
        "tracking": {"client": client, "industry": ind, "signal_names": signal_names},
    }


def _has_high_conflict(interpreter_payload: dict) -> bool:
    symptoms = interpreter_payload.get("symptoms")
    if not isinstance(symptoms, list):
        return False
    for s in symptoms:
        if not isinstance(s, dict):
            continue
        sev = str(s.get("severity", "")).strip().lower()
        evidence = str(s.get("evidence", "")).strip()
        if sev in {"high", "critical"} and evidence:
            return True
    return False


def _anomaly_requires_reexamine(anomaly_payload: dict) -> bool:
    exceptions = anomaly_payload.get("exceptions")
    if not isinstance(exceptions, list):
        return False
    for ex in exceptions:
        if not isinstance(ex, dict):
            continue
        rec = str(ex.get("recommendation", "")).strip().lower()
        if rec in {"re-examine", "reexamine", "escalate"}:
            return True
    return False


def _anomaly_override_recommendation(anomaly_payload: dict) -> dict | None:
    exceptions = anomaly_payload.get("exceptions")
    if not isinstance(exceptions, list):
        return None
    for ex in exceptions:
        if not isinstance(ex, dict):
            continue
        rec = str(ex.get("recommendation", "")).strip().lower()
        if rec != "bypass_template":
            continue
        orr = ex.get("override_recommendation")
        if isinstance(orr, dict):
            return dict(orr)
        title = str(ex.get("title", "")).strip()
        evidence = str(ex.get("evidence", "")).strip()
        why = str(ex.get("why_template_fails", "")).strip()
        if title or evidence or why:
            return {"bypass_gates": [], "rationale": title or why or evidence, "required_evidence": [evidence] if evidence else []}
        return {"bypass_gates": [], "rationale": "bypass_template recommended", "required_evidence": []}
    return None


def _is_noise_source(source: str) -> bool:
    s = (source or "").strip().lower()
    if not s:
        return False
    noise_markers = ("press release", "prwire", "sponsored", "advertorial", "marketing", "brand", "soft article", "软文")
    return any(m in s for m in noise_markers)


def _normalize_environment_events(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        boundary = str(e.get("boundary", "")).strip().upper()
        name = str(e.get("name", "")).strip()
        boundary_id = str(e.get("boundary_id", "")).strip()
        triggered_at = str(e.get("triggered_at", "")).strip()
        sources_raw = e.get("sources")
        sources: list[str] = []
        if isinstance(sources_raw, str):
            sources_raw = [sources_raw]
        if isinstance(sources_raw, list):
            for s in sources_raw:
                if not isinstance(s, str):
                    continue
                if _is_noise_source(s):
                    continue
                ss = s.strip()
                if ss:
                    sources.append(ss)
        evidence_summary_raw = e.get("evidence_summary")
        evidence_summary: list[str] = []
        if isinstance(evidence_summary_raw, str):
            evidence_summary_raw = [evidence_summary_raw]
        if isinstance(evidence_summary_raw, list):
            for x in evidence_summary_raw:
                if not isinstance(x, str):
                    continue
                xx = x.strip()
                if xx:
                    evidence_summary.append(xx)
        affected_nodes_raw = e.get("affected_ontology_nodes")
        affected_nodes: list[str] = []
        if isinstance(affected_nodes_raw, list):
            for n in affected_nodes_raw:
                if not isinstance(n, str):
                    continue
                nn = n.strip()
                if nn:
                    affected_nodes.append(nn)

        confidence = e.get("confidence")
        try:
            conf = float(confidence) if confidence is not None else None
        except Exception:
            conf = None

        exposure = e.get("business_exposure")
        try:
            business_exposure = float(exposure) if exposure is not None else None
        except Exception:
            business_exposure = None

        provisional = e.get("provisional_insight")
        provisional_insight: dict | None = None
        if isinstance(provisional, dict):
            provisional_insight = {
                "type": str(provisional.get("type", "")).strip() or "contextual_anchor",
                "content": str(provisional.get("content", "")).strip(),
                "source_lesson": str(provisional.get("source_lesson", "")).strip(),
                "confidence": float(provisional.get("confidence")) if provisional.get("confidence") is not None else None,
            }
            if provisional_insight.get("confidence") is None:
                provisional_insight.pop("confidence", None)

        out.append(
            {
                "name": name,
                "boundary": boundary,
                "boundary_id": boundary_id,
                "triggered_at": triggered_at,
                "sources": sources,
                "evidence_summary": evidence_summary,
                "affected_ontology_nodes": affected_nodes,
                "confidence": conf,
                "business_exposure": business_exposure,
                "provisional_insight": provisional_insight,
            }
        )
    return out


def _select_confirmed_boundary_b(
    events: list[dict],
    *,
    allowed_signal_names: set[str] | None = None,
    min_sources: int = 2,
    min_confidence: float = 0.6,
    min_business_exposure: float | None = None,
) -> dict | None:
    for e in events:
        boundary = str(e.get("boundary", "")).strip().upper()
        name = str(e.get("name", "")).strip()
        if boundary != "B" and (not allowed_signal_names or name not in allowed_signal_names):
            continue
        sources = e.get("sources") or []
        if isinstance(sources, list) and len(set(sources)) < min_sources:
            continue
        conf = e.get("confidence")
        if conf is not None and float(conf) < min_confidence:
            continue
        if min_business_exposure is not None:
            be = e.get("business_exposure")
            if be is None or float(be) < float(min_business_exposure):
                continue
        if not (e.get("boundary_id") or e.get("evidence_summary")):
            continue
        return e
    return None


def _parse_boundary_b_config(config: dict) -> tuple[set[str], int, float, float | None]:
    fb = config.get("failure_boundaries")
    if not isinstance(fb, dict):
        return set(), 2, 0.6, None
    b = fb.get("B")
    if not isinstance(b, dict):
        return set(), 2, 0.6, None
    allowed_raw = b.get("environment_signal_names")
    allowed: set[str] = set()
    if isinstance(allowed_raw, list):
        for x in allowed_raw:
            if isinstance(x, str) and x.strip():
                allowed.add(x.strip())
    try:
        min_sources = int(b.get("min_sources", 2))
    except Exception:
        min_sources = 2
    try:
        min_confidence = float(b.get("min_confidence", 0.6))
    except Exception:
        min_confidence = 0.6
    mbe = b.get("min_business_exposure")
    try:
        min_business_exposure = float(mbe) if mbe is not None else None
    except Exception:
        min_business_exposure = None
    return allowed, min_sources, min_confidence, min_business_exposure


def _select_policy_pivot(*, trigger_rules: object, boundary_event: dict | None) -> dict | None:
    if not isinstance(trigger_rules, list) or not isinstance(boundary_event, dict):
        return None
    be = boundary_event.get("business_exposure")
    try:
        exposure = float(be) if be is not None else None
    except Exception:
        exposure = None
    high_exposure = exposure is not None and exposure >= 0.4
    for r in trigger_rules:
        if not isinstance(r, dict):
            continue
        threshold = str(r.get("threshold", "")).strip().lower()
        if threshold not in {"critical", "high"}:
            continue
        sig_expr = str(r.get("signal", "")).strip()
        if "Policy_Mutation_Alert" not in sig_expr:
            continue
        if "High_Business_Exposure" in sig_expr and not high_exposure:
            continue
        return r
    return None


def _apply_policy_shock_decay(
    signals_raw: list[dict],
    *,
    now: datetime,
    policy_shock_cfg: object,
) -> tuple[list[dict], bool]:
    if not isinstance(policy_shock_cfg, dict):
        return signals_raw, False
    eos = policy_shock_cfg.get("expansion_oriented_signals")
    if not isinstance(eos, list) or not eos:
        return signals_raw, False
    try:
        decay_days = int(policy_shock_cfg.get("expansion_signal_decay_days", 0))
    except Exception:
        decay_days = 0
    if decay_days <= 0:
        return signals_raw, False
    names: set[str] = set()
    for x in eos:
        if isinstance(x, str) and x.strip():
            names.add(x.strip())
    if not names:
        return signals_raw, False
    cutoff = now - timedelta(days=decay_days)
    out: list[dict] = []
    applied = False
    for s in signals_raw:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip()
        ts = str(s.get("timestamp", "")).strip()
        if name in names and ts:
            try:
                dt = datetime.fromisoformat(ts).replace(tzinfo=UTC)
            except Exception:
                dt = None
            if dt is not None and dt < cutoff:
                applied = True
                continue
        out.append(s)
    return out, applied


def _build_pause_manifesto(*, boundary_event: dict, now: datetime) -> dict:
    triggered_at = str(boundary_event.get("triggered_at", "")).strip()
    if not triggered_at:
        triggered_at = now.isoformat()

    boundary_id = str(boundary_event.get("boundary_id", "")).strip()
    if not boundary_id:
        boundary_id = f"B-{now.strftime('%Y%m%d%H%M%S')}"

    evidence_summary = boundary_event.get("evidence_summary")
    if not isinstance(evidence_summary, list):
        evidence_summary = []

    affected_nodes = boundary_event.get("affected_ontology_nodes")
    if not isinstance(affected_nodes, list):
        affected_nodes = []

    provisional = boundary_event.get("provisional_insight")
    if not isinstance(provisional, dict):
        provisional = {
            "type": "contextual_anchor",
            "content": "Boundary B active: regime shift detected. Automated priors are invalidated; awaiting human validation.",
            "source_lesson": "",
            "confidence": 0.5,
        }

    return {
        "status": "boundary_B_active",
        "boundary_id": boundary_id,
        "triggered_at": triggered_at,
        "evidence_summary": evidence_summary,
        "affected_ontology_nodes": affected_nodes,
        "current_reasoning_status": "prior_invalidated",
        "human_intervention_required": True,
        "hitl_deadline_seconds": _BOUNDARY_B_HITL_DEADLINE_SECONDS,
        "fallback_action": "await_consultant_validation",
        "provisional_insight": provisional,
    }


def run_semantic_diagnosis_pipeline(
    *,
    thread_id: str,
    company_name: str,
    industry: str,
    model_name: str | None = None,
    hitl_approved: bool = False,
    reviewer: str | None = None,
    hitl_task_id: str | None = None,
    runner: SubagentRunner | None = None,
) -> dict:
    runner = runner or DefaultSubagentRunner()

    reasons: list[str] = []
    allow_briefing = True

    config = load_industry_config(industry)
    decay_rate_months = float(config["signals"]["decay_rate_months"])
    multi_source_threshold = int(config["signals"]["multi_source_threshold"])
    trigger_rules = config.get("trigger_rules")
    inference_chain = config.get("inference_chain")
    action_script = config.get("action_script")
    conflict_rules = config.get("conflict_rules")
    policy_shock_cfg = config.get("policy_shock")

    sensor_prompt = (
        "Collect structured company signals AND 2026 industry benchmarks.\n"
        "Also detect black-swan environmental regime shifts (Failure Boundary B).\n"
        "Output MUST be JSON only: {\"signals\": [...], \"benchmarks\": {...}, \"environment_events\": [...]}\n"
        f"Industry: {industry}\n"
        f"Company: {company_name}\n"
    )
    sensor_payload = _parse_json(runner.run(subagent_name="sensor_agent", prompt=sensor_prompt, thread_id=thread_id, model_name=model_name))

    signals_raw = sensor_payload.get("signals")
    benchmarks = sensor_payload.get("benchmarks")
    env_events = _normalize_environment_events(sensor_payload.get("environment_events"))
    allowed_names, b_min_sources, b_min_conf, b_min_exposure = _parse_boundary_b_config(config)
    boundary_b = _select_confirmed_boundary_b(
        env_events,
        allowed_signal_names=allowed_names or None,
        min_sources=b_min_sources,
        min_confidence=b_min_conf,
        min_business_exposure=b_min_exposure,
    )

    signals: list[dict] = []
    now = datetime.now(tz=UTC)
    if hitl_task_id:
        task = get_hitl_task(hitl_task_id)
        if isinstance(task, dict) and task.get("status") == "resolved" and task.get("decision") == "approve" and task.get("seal_logical_gap") is True:
            if not hitl_approved:
                hitl_approved = True
            if reviewer is None and isinstance(task.get("reviewer"), str) and task.get("reviewer").strip():
                reviewer = str(task.get("reviewer")).strip()

    policy_shock_mode = boundary_b is not None and hitl_approved
    policy_pivot = _select_policy_pivot(trigger_rules=trigger_rules, boundary_event=boundary_b) if policy_shock_mode else None
    if policy_shock_mode:
        reasons.append("BOUNDARY_B_ACTIVE")
    if isinstance(policy_pivot, dict):
        if policy_pivot.get("inference_chain") is not None:
            inference_chain = policy_pivot.get("inference_chain")
        if policy_pivot.get("action_script") is not None:
            action_script = policy_pivot.get("action_script")

    policy_shock_state = {
        "active": boundary_b is not None,
        "mode": policy_shock_mode,
        "boundary_event": boundary_b,
        "pivot": policy_pivot,
        "config": policy_shock_cfg if isinstance(policy_shock_cfg, dict) else None,
    }

    if boundary_b is not None and not policy_shock_mode:
        reasons.append("BOUNDARY_B_ACTIVE")
        allow_briefing = False
        hitl_decision = "mandatory"
        pause_manifesto = _build_pause_manifesto(boundary_event=boundary_b, now=now)

        audit_id = now.strftime("%Y%m%d%H%M%S%f")
        audit_path = get_paths().base_dir / "diagnosis" / "diagnosis_audit.jsonl"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "audit_id": audit_id,
                        "thread_id": thread_id,
                        "company_name": company_name,
                        "industry": industry,
                        "model_name": model_name,
                        "hitl_approved": hitl_approved,
                        "reviewer": reviewer,
                        "allow_briefing": False,
                        "hitl_decision": hitl_decision,
                        "reasons": reasons,
                        "boundary_b": pause_manifesto.get("boundary_id"),
                    },
                    ensure_ascii=False,
                )
            )
            f.write("\n")

        _upsert_hitl_task(
            {
                "task_id": audit_id,
                "audit_id": audit_id,
                "thread_id": thread_id,
                "company_name": company_name,
                "industry": industry,
                "model_name": model_name,
                "status": "pending",
                "reasons": list(reasons),
                "pause_manifesto": pause_manifesto,
                "policy_shock": policy_shock_state,
                "environment_events": env_events,
                "review_checklist": [
                    "Confirm Condensed EMBA anchors (first principles / job value chain).",
                    "Verify evidence sufficiency for each key conclusion.",
                    "Fill missing causal vectors with industry common sense (logical sealing).",
                    "Check anomaly / black-swan factors and override if needed.",
                ],
            }
        )

        out = {
            "success": True,
            "audit_id": audit_id,
            "allow_briefing": False,
            "hitl_decision": hitl_decision,
            "reasons": reasons,
            "pause_manifesto": pause_manifesto,
            "hitl_task_id": audit_id,
            "policy_shock": policy_shock_state,
            "signals": [],
            "benchmarks": {},
            "conflicts": None,
            "circuit_breaker": {"triggered": True, "allow_briefing": False, "reasons": ["BOUNDARY_B_ACTIVE"]},
            "anomalies": None,
            "briefing": None,
        }
        review_packet = _build_review_packet(
            audit_id=audit_id,
            thread_id=thread_id,
            company_name=company_name,
            industry=industry,
            model_name=model_name,
            hitl_decision=hitl_decision,
            allow_briefing=False,
            reasons=list(reasons),
            hitl_task_id=audit_id,
            sealed_review=None,
            signals=[],
            benchmarks={},
            conflicts=None,
            circuit_breaker={"triggered": True, "allow_briefing": False, "reasons": ["BOUNDARY_B_ACTIVE"]},
            anomalies=None,
            override_recommendation=None,
            policy_shock=policy_shock_state,
        )
        out["review_packet"] = review_packet
        out["drafts"] = _build_human_send_drafts(company_name=company_name, industry=industry, signals=[], review_packet=review_packet)
        return out

    if policy_shock_mode and isinstance(signals_raw, list):
        signals_raw, applied = _apply_policy_shock_decay(signals_raw, now=now, policy_shock_cfg=policy_shock_cfg)
        if applied:
            reasons.append("POLICY_SHOCK_DECAY_APPLIED")

    if not isinstance(signals_raw, list) or len(signals_raw) == 0:
        audit_id = now.strftime("%Y%m%d%H%M%S%f")
        reasons.append("NO_SIGNALS")
        task = _upsert_hitl_task(
            {
                "task_id": audit_id,
                "audit_id": audit_id,
                "thread_id": thread_id,
                "company_name": company_name,
                "industry": industry,
                "model_name": model_name,
                "status": "pending",
                "reasons": list(reasons),
                "review_checklist": [
                    "Confirm Condensed EMBA anchors (first principles / job value chain).",
                    "Verify evidence sufficiency for each key conclusion.",
                    "Fill missing causal vectors with industry common sense (logical sealing).",
                    "Check anomaly / black-swan factors and override if needed.",
                ],
            }
        )
        return {
            "success": True,
            "audit_id": audit_id,
            "allow_briefing": False,
            "hitl_decision": "mandatory",
            "reasons": list(reasons),
            "pause_manifesto": None,
            "hitl_task_id": task.get("task_id"),
            "signals": [],
            "benchmarks": {},
            "conflicts": None,
            "circuit_breaker": {"triggered": True, "allow_briefing": False, "reasons": list(reasons)},
            "anomalies": None,
            "briefing": None,
        }
    if not isinstance(benchmarks, dict) or len(benchmarks) == 0:
        audit_id = now.strftime("%Y%m%d%H%M%S%f")
        reasons.append("MISSING_BENCHMARKS")
        task = _upsert_hitl_task(
            {
                "task_id": audit_id,
                "audit_id": audit_id,
                "thread_id": thread_id,
                "company_name": company_name,
                "industry": industry,
                "model_name": model_name,
                "status": "pending",
                "reasons": list(reasons),
                "review_checklist": [
                    "Confirm Condensed EMBA anchors (first principles / job value chain).",
                    "Verify evidence sufficiency for each key conclusion.",
                    "Fill missing causal vectors with industry common sense (logical sealing).",
                    "Check anomaly / black-swan factors and override if needed.",
                ],
            }
        )
        return {
            "success": True,
            "audit_id": audit_id,
            "allow_briefing": False,
            "hitl_decision": "mandatory",
            "reasons": list(reasons),
            "pause_manifesto": None,
            "hitl_task_id": task.get("task_id"),
            "signals": [],
            "benchmarks": {},
            "conflicts": None,
            "circuit_breaker": {"triggered": True, "allow_briefing": False, "reasons": list(reasons)},
            "anomalies": None,
            "briefing": None,
        }

    for s in signals_raw:
        if not isinstance(s, dict):
            continue
        ts = str(s.get("timestamp", "")).strip()
        if not ts:
            continue
        if not _is_recent_enough(ts, decay_rate_months):
            continue
        name = str(s.get("name", "")).strip()
        if not name:
            continue
        signals.append(
            {
                "name": name,
                "timestamp": ts,
                "source": str(s.get("source", "unknown")),
                "value": s.get("value"),
                "dimension": s.get("dimension"),
            }
        )

    if not signals:
        audit_id = now.strftime("%Y%m%d%H%M%S%f")
        reasons.append("ALL_SIGNALS_EXPIRED")
        task = _upsert_hitl_task(
            {
                "task_id": audit_id,
                "audit_id": audit_id,
                "thread_id": thread_id,
                "company_name": company_name,
                "industry": industry,
                "model_name": model_name,
                "status": "pending",
                "reasons": list(reasons),
                "review_checklist": [
                    "Confirm Condensed EMBA anchors (first principles / job value chain).",
                    "Verify evidence sufficiency for each key conclusion.",
                    "Fill missing causal vectors with industry common sense (logical sealing).",
                    "Check anomaly / black-swan factors and override if needed.",
                ],
            }
        )
        return {
            "success": True,
            "audit_id": audit_id,
            "allow_briefing": False,
            "hitl_decision": "mandatory",
            "reasons": list(reasons),
            "pause_manifesto": None,
            "hitl_task_id": task.get("task_id"),
            "signals": [],
            "benchmarks": benchmarks if isinstance(benchmarks, dict) else {},
            "conflicts": None,
            "circuit_breaker": {"triggered": True, "allow_briefing": False, "reasons": list(reasons)},
            "anomalies": None,
            "briefing": None,
        }

    source_map = _sources_by_name(signals)
    verified = [name for name, sources in source_map.items() if len(sources) >= multi_source_threshold]
    if not verified:
        audit_id = now.strftime("%Y%m%d%H%M%S%f")
        reasons.append("CROSS_VALIDATION_FAILED")
        task = _upsert_hitl_task(
            {
                "task_id": audit_id,
                "audit_id": audit_id,
                "thread_id": thread_id,
                "company_name": company_name,
                "industry": industry,
                "model_name": model_name,
                "status": "pending",
                "reasons": list(reasons),
                "review_checklist": [
                    "Confirm Condensed EMBA anchors (first principles / job value chain).",
                    "Verify evidence sufficiency for each key conclusion.",
                    "Fill missing causal vectors with industry common sense (logical sealing).",
                    "Check anomaly / black-swan factors and override if needed.",
                ],
                "signals": list(signals),
                "benchmarks": dict(benchmarks) if isinstance(benchmarks, dict) else {},
                "sources_by_signal": {k: sorted(list(v)) for k, v in source_map.items()},
            }
        )
        return {
            "success": True,
            "audit_id": audit_id,
            "allow_briefing": False,
            "hitl_decision": "mandatory",
            "reasons": list(reasons),
            "pause_manifesto": None,
            "hitl_task_id": task.get("task_id"),
            "signals": list(signals),
            "benchmarks": dict(benchmarks) if isinstance(benchmarks, dict) else {},
            "conflicts": None,
            "circuit_breaker": {"triggered": True, "allow_briefing": False, "reasons": list(reasons)},
            "anomalies": None,
            "briefing": None,
        }

    interpreter_prompt = (
        "Perform conflict detection (words vs deeds) and benchmark contextualisation.\n"
        "Output MUST be JSON only: {\"symptoms\": [...], \"features\": [...]}\n"
        f"Industry: {industry}\n"
        f"Benchmarks: {json.dumps(benchmarks, ensure_ascii=False)}\n"
        f"Signals: {json.dumps(signals, ensure_ascii=False)}\n"
        f"PolicyShock: {json.dumps(policy_shock_state, ensure_ascii=False)}\n"
        f"ConflictRules: {json.dumps(conflict_rules, ensure_ascii=False)}\n"
        f"TriggerRules: {json.dumps(trigger_rules, ensure_ascii=False)}\n"
        f"InferenceChain: {json.dumps(inference_chain, ensure_ascii=False)}\n"
    )
    interpreter_payload = _parse_json(runner.run(subagent_name="interpreter_agent", prompt=interpreter_prompt, thread_id=thread_id, model_name=model_name))
    if _has_high_conflict(interpreter_payload):
        reasons.append("CONFLICT_DETECTED")
        allow_briefing = False

    cb_state = compute_circuit_breaker_state(symptoms=signals, industry=industry, benchmark_deviations=None)
    if not cb_state.get("allow_briefing", False):
        allow_briefing = False
        for r in cb_state.get("reasons") or []:
            reasons.append(str(r))

    anomaly_prompt = (
        "Run counter-checking for legitimate industry-specific exceptions.\n"
        "Output MUST be JSON only.\n"
        f"Industry: {industry}\n"
        f"Benchmarks: {json.dumps(benchmarks, ensure_ascii=False)}\n"
        f"Signals: {json.dumps(signals, ensure_ascii=False)}\n"
        f"Diagnosis: {json.dumps(cb_state, ensure_ascii=False)}\n"
        f"Conflicts: {json.dumps(interpreter_payload, ensure_ascii=False)}\n"
        f"PolicyShock: {json.dumps(policy_shock_state, ensure_ascii=False)}\n"
        f"TriggerRules: {json.dumps(trigger_rules, ensure_ascii=False)}\n"
    )
    anomaly_payload = _parse_json(runner.run(subagent_name="anomaly_detection_agent", prompt=anomaly_prompt, thread_id=thread_id, model_name=model_name))
    if _anomaly_requires_reexamine(anomaly_payload):
        reasons.append("ANOMALY_REEXAMINE")
        allow_briefing = False
    anomaly_override = _anomaly_override_recommendation(anomaly_payload)
    if anomaly_override is not None:
        reasons.append("ANOMALY_OVERRIDE_RECOMMENDED")
        allow_briefing = False
        if isinstance(anomaly_payload, dict) and "override_recommendation" not in anomaly_payload:
            anomaly_payload["override_recommendation"] = dict(anomaly_override)

    sealed = False
    sealed_review: dict | None = None
    if hitl_task_id:
        task = get_hitl_task(hitl_task_id)
        if isinstance(task, dict) and task.get("status") == "resolved" and task.get("decision") == "approve" and task.get("seal_logical_gap") is True:
            sealed = True
            sealed_review = {
                "task_id": str(task.get("task_id") or hitl_task_id),
                "reviewer": str(task.get("reviewer") or reviewer or ""),
                "decision": "approve",
                "review_notes": str(task.get("review_notes") or ""),
                "patch": task.get("patch") if isinstance(task.get("patch"), dict) else None,
                "resolved_at": str(task.get("resolved_at") or ""),
                "seal_logical_gap": True,
            }
            reasons.append("HITL_SEALED")

    mandatory = bool(reasons) and not hitl_approved
    hitl_decision = "mandatory" if mandatory else "none"

    briefing: str | None = None
    effective_allow_briefing = allow_briefing or sealed
    if effective_allow_briefing and hitl_decision == "none":
        patch = sealed_review.get("patch") if isinstance(sealed_review, dict) else None
        composer_prompt = (
            "Generate the final mentor-style diagnostic briefing.\n"
            f"Industry: {industry}\n"
            f"Signals: {json.dumps(signals, ensure_ascii=False)}\n"
            f"Benchmarks: {json.dumps(benchmarks, ensure_ascii=False)}\n"
            f"Conflicts: {json.dumps(interpreter_payload, ensure_ascii=False)}\n"
            f"Diagnosis: {json.dumps(cb_state, ensure_ascii=False)}\n"
            f"Anomalies: {json.dumps(anomaly_payload, ensure_ascii=False)}\n"
            f"PolicyShock: {json.dumps(policy_shock_state, ensure_ascii=False)}\n"
            f"ConsultantSeal: {json.dumps(sealed_review, ensure_ascii=False)}\n"
            f"ConsultantPatch: {json.dumps(patch, ensure_ascii=False)}\n"
            f"ActionScript: {json.dumps(action_script, ensure_ascii=False)}\n"
        )
        briefing = runner.run(subagent_name="composer_agent", prompt=composer_prompt, thread_id=thread_id, model_name=model_name).strip()

    audit_id = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S%f")
    audit_path = get_paths().base_dir / "diagnosis" / "diagnosis_audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "audit_id": audit_id,
                    "thread_id": thread_id,
                    "company_name": company_name,
                    "industry": industry,
                    "model_name": model_name,
                    "hitl_approved": hitl_approved,
                    "reviewer": reviewer,
                    "allow_briefing": effective_allow_briefing and hitl_decision == "none",
                    "hitl_decision": hitl_decision,
                    "reasons": reasons,
                    "policy_shock": policy_shock_state,
                    "signals_count": len(signals),
                    "verified_count": len(verified),
                    "hitl_task_id": hitl_task_id,
                    "sealed": sealed,
                },
                ensure_ascii=False,
            )
        )
        f.write("\n")

    out = {
        "success": True,
        "audit_id": audit_id,
        "allow_briefing": effective_allow_briefing and hitl_decision == "none",
        "hitl_decision": hitl_decision,
        "reasons": reasons,
        "pause_manifesto": None,
        "hitl_task_id": hitl_task_id,
        "policy_shock": policy_shock_state,
        "sealed_review": sealed_review,
        "signals": signals,
        "benchmarks": benchmarks,
        "conflicts": interpreter_payload,
        "circuit_breaker": cb_state,
        "anomalies": anomaly_payload,
        "briefing": briefing,
    }
    if hitl_decision == "mandatory":
        task = _upsert_hitl_task(
            {
                "task_id": audit_id,
                "audit_id": audit_id,
                "thread_id": thread_id,
                "company_name": company_name,
                "industry": industry,
                "model_name": model_name,
                "status": "pending",
                "reasons": list(reasons),
                "policy_shock": policy_shock_state,
                "review_checklist": [
                    "Confirm Condensed EMBA anchors (first principles / job value chain).",
                    "Verify evidence sufficiency for each key conclusion.",
                    "Fill missing causal vectors with industry common sense (logical sealing).",
                    "Check anomaly / black-swan factors and override if needed.",
                ],
                "signals": list(signals),
                "benchmarks": dict(benchmarks) if isinstance(benchmarks, dict) else {},
                "circuit_breaker": dict(cb_state) if isinstance(cb_state, dict) else {},
                "conflicts": dict(interpreter_payload) if isinstance(interpreter_payload, dict) else {},
                "anomalies": dict(anomaly_payload) if isinstance(anomaly_payload, dict) else {},
                "override_recommendation": dict(anomaly_override) if isinstance(anomaly_override, dict) else None,
            }
        )
        out["hitl_task_id"] = task.get("task_id")

    review_packet = _build_review_packet(
        audit_id=audit_id,
        thread_id=thread_id,
        company_name=company_name,
        industry=industry,
        model_name=model_name,
        hitl_decision=hitl_decision,
        allow_briefing=effective_allow_briefing and hitl_decision == "none",
        reasons=list(reasons),
        hitl_task_id=out.get("hitl_task_id"),
        sealed_review=sealed_review,
        signals=list(signals),
        benchmarks=dict(benchmarks) if isinstance(benchmarks, dict) else {},
        conflicts=interpreter_payload if isinstance(interpreter_payload, dict) else None,
        circuit_breaker=cb_state if isinstance(cb_state, dict) else None,
        anomalies=anomaly_payload if isinstance(anomaly_payload, dict) else None,
        override_recommendation=anomaly_override if isinstance(anomaly_override, dict) else None,
        policy_shock=policy_shock_state,
    )
    out["review_packet"] = review_packet
    drafts = _build_human_send_drafts(company_name=company_name, industry=industry, signals=list(signals), review_packet=review_packet)
    out["drafts"] = drafts
    outreach_plan: dict | None = None
    if out.get("allow_briefing") is True and isinstance(drafts, dict):
        distribution_prompt = (
            "Build a human-send-only outreach plan.\n"
            "Output MUST be JSON only.\n"
            f"Company: {company_name}\n"
            f"Industry: {industry}\n"
            f"ReviewPacket: {json.dumps(review_packet, ensure_ascii=False)}\n"
            f"Drafts: {json.dumps(drafts, ensure_ascii=False)}\n"
        )
        distribution_payload = _parse_json(
            runner.run(subagent_name="distribution_agent", prompt=distribution_prompt, thread_id=thread_id, model_name=model_name)
        )
        outreach_plan = _coerce_outreach_plan(
            raw=distribution_payload,
            company_name=company_name,
            industry=industry,
            signals=list(signals),
            drafts=drafts,
        )
    if outreach_plan is not None:
        out["outreach_plan"] = outreach_plan
        if isinstance(review_packet, dict):
            review_packet["distribution_bundle"] = outreach_plan
    return out
