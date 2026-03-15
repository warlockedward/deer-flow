import hashlib
import json
import logging
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.config.ontology_config import CondensedEmbaOntology, get_condensed_emba_ontology, write_condensed_emba_ontology
from src.config.paths import get_paths
from src.config.update_agent_verifier import decide_hitl
from src.models import create_chat_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ontology/condensed-emba", tags=["ontology"])


class OntologyUploadResponse(BaseModel):
    success: bool
    version: str | None = None
    node_count: int = 0
    edge_count: int = 0
    path: str | None = None


class OntologyCurrentResponse(BaseModel):
    exists: bool
    version: str | None = None
    node_count: int = 0
    edge_count: int = 0
    updated: float | None = None


class OntologyUpdateRunRequest(BaseModel):
    thread_id: str
    filename: str | None = None
    content: str | None = None
    industries: list[str] | None = None
    apply: bool = False
    hitl_approved: bool = False
    reviewer: str | None = None
    model_name: str | None = None


class OntologyUpdateRunResponse(BaseModel):
    success: bool
    applied: bool
    audit_id: str
    hitl_decision: str
    review_required: bool = False
    review_recommended: bool = False
    risk_level: str
    confidence: float
    conflicts: list[str]


def _strip_markdown_code_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        parts = t.split("\n")
        if len(parts) >= 2 and parts[-1].strip() == "```":
            return "\n".join(parts[1:-1]).strip()
    return t


def _extract_response_text(content: str | list) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append(str(block.get("text", "")))
        return "\n".join(out)
    return str(content)


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(mode="w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8")
    try:
        json.dump(data, fd, ensure_ascii=False, indent=2)
        fd.close()
        Path(fd.name).replace(path)
    except BaseException:
        fd.close()
        Path(fd.name).unlink(missing_ok=True)
        raise


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False))
        f.write("\n")


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


_ALLOWED_RAR_SECTIONS: set[str] = {"Strategy", "Performance", "Finance", "Team", "Marketing"}


def _edge_key(*, source: str, relation: str, target: str) -> str:
    raw = f"{source}|{relation}|{target}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:12]


def _normalize_ontology_data(ontology_data: dict) -> dict:
    nodes_raw = ontology_data.get("nodes")
    edges_raw = ontology_data.get("edges")

    nodes: list[dict] = []
    if isinstance(nodes_raw, list):
        for n in nodes_raw:
            if isinstance(n, dict):
                nodes.append(n)
    ontology_data["nodes"] = nodes

    edges: list[dict] = []
    if isinstance(edges_raw, list):
        for e in edges_raw:
            if not isinstance(e, dict):
                continue
            source = str(e.get("source") or "").strip()
            target = str(e.get("target") or "").strip()
            if not source or not target:
                raise HTTPException(status_code=400, detail="Invalid edge: missing source/target")

            relation = e.get("relation")
            relation_str = str(relation).strip() if isinstance(relation, str) else ""
            if not relation_str:
                relation_str = "causes"
            e["relation"] = relation_str

            section = e.get("section")
            if not isinstance(section, str) or section not in _ALLOWED_RAR_SECTIONS:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid edge: missing or invalid section (must be one of Strategy, Performance, Finance, Team, Marketing)",
                )

            source_quote = e.get("source_quote")
            if not isinstance(source_quote, str) or not source_quote.strip():
                raise HTTPException(status_code=400, detail="Invalid edge: missing or empty source_quote")

            strength = e.get("strength")
            strength_str = str(strength).strip() if isinstance(strength, str) else ""
            e["strength"] = strength_str if strength_str else "medium"
            e["edge_key"] = str(e.get("edge_key") or _edge_key(source=source, relation=relation_str, target=target)).strip()
            e["source"] = source
            e["target"] = target

            edges.append(e)
    ontology_data["edges"] = edges
    return ontology_data


def _grounding_conflicts(*, current: CondensedEmbaOntology, proposed: CondensedEmbaOntology, course_text: str) -> list[str]:
    if not course_text:
        return ["RAR_MISSING_COURSE_CONTENT"]

    current_ids = {n.id for n in current.nodes if isinstance(n.id, str) and n.id.strip()}
    conflicts: list[str] = []

    for n in proposed.nodes:
        if not isinstance(getattr(n, "id", None), str):
            continue
        nid = n.id.strip()
        if not nid or nid in current_ids:
            continue
        sq = getattr(n, "source_quote", None)
        if not isinstance(sq, str) or not sq.strip() or sq.strip() not in course_text:
            conflicts.append(f"RAR_UNGROUNDED_NODE_QUOTE:{nid}")

    for e in proposed.edges:
        try:
            d = e.model_dump(mode="json")
        except Exception:
            continue
        sq = d.get("source_quote")
        if not isinstance(sq, str) or not sq.strip():
            continue
        if sq.strip() not in course_text:
            ek = d.get("edge_key")
            if isinstance(ek, str) and ek.strip():
                conflicts.append(f"RAR_UNGROUNDED_EDGE_QUOTE:{ek.strip()}")
            else:
                src = str(d.get("source", "")).strip()
                rel = str(d.get("relation", "")).strip()
                tgt = str(d.get("target", "")).strip()
                conflicts.append(f"RAR_UNGROUNDED_EDGE_QUOTE:{src}|{rel}|{tgt}")

    return conflicts


def _default_industry_baseline_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "industry_maps" / "traditional_manufacturing.json"


def _deep_merge(base: object, override: object) -> object:
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            if k in out:
                out[k] = _deep_merge(out[k], v)
            else:
                out[k] = v
        return out
    return override


def _load_json_dict(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load JSON: {path.name}: {e}") from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail=f"Invalid JSON object: {path.name}")
    return data


def _validate_industry_config(cfg: dict) -> None:
    signals = cfg.get("signals")
    if not isinstance(signals, dict):
        raise HTTPException(status_code=400, detail="Invalid industry override: missing signals object")
    if not isinstance(signals.get("decay_rate_months"), int | float):
        raise HTTPException(status_code=400, detail="Invalid industry override: signals.decay_rate_months must be number")
    if not isinstance(signals.get("multi_source_threshold"), int):
        raise HTTPException(status_code=400, detail="Invalid industry override: signals.multi_source_threshold must be int")

    confidence = cfg.get("confidence")
    if not isinstance(confidence, dict):
        raise HTTPException(status_code=400, detail="Invalid industry override: missing confidence object")
    if not isinstance(confidence.get("threshold"), int | float):
        raise HTTPException(status_code=400, detail="Invalid industry override: confidence.threshold must be number")
    for k in ("min_verified_symptoms", "min_sources_total", "min_dimensions"):
        if not isinstance(confidence.get(k), int):
            raise HTTPException(status_code=400, detail=f"Invalid industry override: confidence.{k} must be int")

    conflict_rules = cfg.get("conflict_rules")
    if not isinstance(conflict_rules, list):
        raise HTTPException(status_code=400, detail="Invalid industry override: conflict_rules must be a list")

    causal_relationships = cfg.get("causal_relationships")
    if not isinstance(causal_relationships, list):
        raise HTTPException(status_code=400, detail="Invalid industry override: causal_relationships must be a list")

    trigger_rules = cfg.get("trigger_rules")
    if trigger_rules is not None and not isinstance(trigger_rules, list):
        raise HTTPException(status_code=400, detail="Invalid industry override: trigger_rules must be a list when provided")
    if isinstance(trigger_rules, list):
        for tr in trigger_rules:
            if not isinstance(tr, dict):
                raise HTTPException(status_code=400, detail="Invalid industry override: trigger_rules entries must be objects")

    inference_chain = cfg.get("inference_chain")
    if inference_chain is not None and not isinstance(inference_chain, list):
        raise HTTPException(status_code=400, detail="Invalid industry override: inference_chain must be a list when provided")
    if isinstance(inference_chain, list):
        for ic in inference_chain:
            if not isinstance(ic, dict):
                raise HTTPException(status_code=400, detail="Invalid industry override: inference_chain entries must be objects")

    action_script = cfg.get("action_script")
    if action_script is not None and not isinstance(action_script, dict):
        raise HTTPException(status_code=400, detail="Invalid industry override: action_script must be an object when provided")


def _merge_industry_override(*, industry: str, override_cfg: dict, out_path: Path) -> dict:
    base_cfg: dict
    if out_path.exists():
        base_cfg = _load_json_dict(out_path)
    else:
        base_cfg = _load_json_dict(_default_industry_baseline_path())

    merged = _deep_merge(base_cfg, override_cfg)
    if not isinstance(merged, dict):
        raise HTTPException(status_code=400, detail="Invalid industry override: must be an object")
    merged["industry"] = industry
    _validate_industry_config(merged)
    return merged


def _parse_model_json_response(response: object) -> dict:
    raw = _strip_markdown_code_fence(_extract_response_text(getattr(response, "content", "")))
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Model output must be a JSON object")
    return data


def _run_conflict_stress_test(*, model: object, industry: str, industry_config: dict) -> dict:
    now_iso = datetime.now(tz=UTC).isoformat()
    signals = [
        {"name": "RD_drop", "timestamp": now_iso, "source": "synthetic_source_1", "value": "0.01"},
        {"name": "RD_drop", "timestamp": now_iso, "source": "synthetic_source_2", "value": "0.01"},
    ]
    benchmarks = industry_config.get("benchmarks") if isinstance(industry_config.get("benchmarks"), dict) else {}

    prompt = (
        "You are a conflict detection validator.\n"
        "Goal: verify the proposed causal vectors can detect words-vs-deeds contradictions.\n"
        "Output MUST be JSON only: {\"symptoms\": [...], \"features\": [...]}\n"
        "Use the provided industry_config JSON; do not assume file access.\n"
        f"Industry: {industry}\n"
        f"industry_config: {json.dumps(industry_config, ensure_ascii=False)}\n"
        f"Benchmarks: {json.dumps(benchmarks, ensure_ascii=False)}\n"
        f"Signals: {json.dumps(signals, ensure_ascii=False)}\n"
        "Simulated scenario: company claims innovation but R&D is < 3%.\n"
        "Validation rules:\n"
        "- Emit at least one Symptom with non-empty evidence if conflict_rules trigger.\n"
        "- Never emit symptoms without concrete evidence.\n"
    )
    response = model.invoke(prompt)
    return _parse_model_json_response(response)


def _run_anomaly_counter_check(*, model: object, industry: str, industry_config: dict, signals: list[dict], diagnosis: dict, conflicts: dict) -> dict:
    prompt = (
        "You are an anomaly detection validator.\n"
        "Goal: counter-check whether the new vector degenerates into template overreach.\n"
        "Output MUST be JSON only.\n"
        "Use the provided industry_config JSON; do not assume file access.\n"
        f"Industry: {industry}\n"
        f"industry_config: {json.dumps(industry_config, ensure_ascii=False)}\n"
        f"Signals: {json.dumps(signals, ensure_ascii=False)}\n"
        f"Diagnosis: {json.dumps(diagnosis, ensure_ascii=False)}\n"
        f"Conflicts: {json.dumps(conflicts, ensure_ascii=False)}\n"
        "Hard rules:\n"
        "- If you recommend re-examine or escalate, include it explicitly in exceptions.\n"
    )
    response = model.invoke(prompt)
    return _parse_model_json_response(response)


def _validate_dynamic_vectors(*, model: object, industries: list[str], overrides: dict) -> tuple[list[str], dict]:
    conflicts: list[str] = []
    summary: dict[str, dict] = {}
    if not isinstance(overrides, dict):
        return conflicts, summary

    for industry in industries:
        cfg = overrides.get(industry)
        if not isinstance(cfg, dict):
            continue
        summary[industry] = {}
        signals_cfg = cfg.get("signals")
        if isinstance(signals_cfg, dict):
            try:
                ms = int(signals_cfg.get("multi_source_threshold"))
            except Exception:
                ms = 0
            if ms < 2:
                conflicts.append(f"VALIDATION_MULTISOURCE_TOO_LOW:{industry}")
            summary[industry]["multi_source_threshold"] = ms

        try:
            conflict_payload = _run_conflict_stress_test(model=model, industry=industry, industry_config=cfg)
        except Exception:
            conflicts.append(f"VALIDATION_MODEL_ERROR:conflict:{industry}")
            summary[industry]["conflict_model_error"] = True
            continue

        symptoms = conflict_payload.get("symptoms")
        valid_symptom = False
        symptom_count = 0
        if isinstance(symptoms, list):
            symptom_count = len(symptoms)
            for s in symptoms:
                if not isinstance(s, dict):
                    continue
                sev = str(s.get("severity", "")).strip().lower()
                ev = str(s.get("evidence", "")).strip()
                if sev in {"high", "medium", "low", "critical"} and ev:
                    valid_symptom = True
                    break
        summary[industry]["conflict_symptom_count"] = symptom_count
        summary[industry]["conflict_valid_symptom"] = valid_symptom
        if not valid_symptom:
            conflicts.append(f"VALIDATION_CONFLICT_STRESS_FAIL:{industry}")

        try:
            now_iso = datetime.now(tz=UTC).isoformat()
            synthetic_signals = [
                {"name": "RD_drop", "timestamp": now_iso, "source": "synthetic_source_1", "value": "0.01"},
                {"name": "RD_drop", "timestamp": now_iso, "source": "synthetic_source_2", "value": "0.01"},
            ]
            anomaly_payload = _run_anomaly_counter_check(
                model=model,
                industry=industry,
                industry_config=cfg,
                signals=synthetic_signals,
                diagnosis={"verdict": "synthetic_validation"},
                conflicts=conflict_payload,
            )
        except Exception:
            conflicts.append(f"VALIDATION_MODEL_ERROR:anomaly:{industry}")
            summary[industry]["anomaly_model_error"] = True
            continue

        exceptions = anomaly_payload.get("exceptions")
        anomaly_exception_count = 0
        anomaly_requires_reexamine = False
        if isinstance(exceptions, list):
            anomaly_exception_count = len(exceptions)
            for ex in exceptions:
                if not isinstance(ex, dict):
                    continue
                rec = str(ex.get("recommendation", "")).strip().lower()
                if rec in {"re-examine", "reexamine", "escalate"}:
                    anomaly_requires_reexamine = True
                    conflicts.append(f"VALIDATION_ANOMALY_REEXAMINE:{industry}")
                    break
        summary[industry]["anomaly_exception_count"] = anomaly_exception_count
        summary[industry]["anomaly_requires_reexamine"] = anomaly_requires_reexamine

    return conflicts, summary


class OntologyUpdateFeedbackRequest(BaseModel):
    audit_id: str
    outcome: str
    node_ids: list[str] | None = None
    edge_keys: list[str] | None = None
    reviewer: str | None = None
    notes: str | None = None


class OntologyUpdateFeedbackResponse(BaseModel):
    success: bool


@router.post("/update/run", response_model=OntologyUpdateRunResponse)
async def run_update(request: OntologyUpdateRunRequest) -> OntologyUpdateRunResponse:
    audit_id = uuid.uuid4().hex
    text = (request.content or "").strip()
    if not text and request.filename:
        uploads_dir = get_paths().sandbox_uploads_dir(request.thread_id)
        safe_name = Path(request.filename).name
        file_path = uploads_dir / safe_name
        if not file_path.exists() and file_path.suffix.lower() != ".md":
            md_path = file_path.with_suffix(".md")
            if md_path.exists():
                file_path = md_path

        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {request.filename}")
        text = file_path.read_text(encoding="utf-8", errors="ignore").strip()

    if not text:
        raise HTTPException(status_code=400, detail="Missing content or filename")

    prompt = (
        "You are an Update Agent that converts new Condensed EMBA course content into an updated ontology.\n"
        "Output MUST be valid JSON only (no markdown).\n"
        'Schema: {"ontology": {"version": "...", "nodes": [...], "edges": [...]}, "industry_overrides": {}}\n'
        "Rules:\n"
        "- Every NEW node must include a non-empty `source_quote` string.\n"
        "- Edges must reference existing node ids.\n"
        "- Keep ontology acyclic (DAG).\n\n"
        "Knowledge Deconstruction:\n"
        "- Extract abstract management concepts as nodes (e.g., first principles, strategic loss).\n"
        "- Extract observable business patterns as trigger nodes (e.g., sales growth but declining profits).\n"
        "- Extract causal vectors using the chain: [Phenomenon] -> [Root Cause] -> [Solution].\n"
        "- For each causal edge, include:\n"
        "  - `relation` (one of: phenomenon->root_cause, root_cause->solution, causes)\n"
        "  - `section` anchored to exactly one of: Strategy, Performance, Finance, Team, Marketing\n"
        "  - `source_quote` grounding that appears verbatim in the course content\n"
        "  - optional `strength` (weak|medium|strong)\n"
        "- Also produce `industry_overrides` for executable diagnostics:\n"
        "  - `causal_relationships`: list of {cause,effect,strength}\n"
        "  - `conflict_rules`: list of claim vs behavior mismatches (e.g., innovation claim with R&D < 3%)\n"
        "  - optional `diagnostic_chains`: list of node-id chains (multi-hop)\n\n"
        "  - optional `trigger_rules`: list of signal-combo triggers (thresholded rules)\n"
        "  - optional `inference_chain`: list of dynamic logical pathways (cause expansion)\n"
        "  - optional `action_script`: object describing output titles/templates and next-actions\n\n"
        "Course Content:\n"
        f"{text}\n"
    )

    try:
        model = create_chat_model(name=request.model_name, thinking_enabled=False)
        response = model.invoke(prompt)
        payload = _parse_model_json_response(response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model invocation or JSON parse failed: {e}") from e

    ontology_data = payload.get("ontology")
    if not isinstance(ontology_data, dict):
        raise HTTPException(status_code=400, detail="Missing 'ontology' object in model output")

    proposed = CondensedEmbaOntology.model_validate(_normalize_ontology_data(ontology_data))
    current = get_condensed_emba_ontology()
    report = decide_hitl(current=current, proposed=proposed)
    grounding_conflicts = _grounding_conflicts(current=current, proposed=proposed, course_text=text)

    overrides_obj = payload.get("industry_overrides") or {}
    overrides_merged: dict[str, dict] = {}
    if isinstance(overrides_obj, dict):
        for industry, cfg in overrides_obj.items():
            if not isinstance(industry, str) or not isinstance(cfg, dict):
                continue
            safe = Path(f"{industry}.json").name
            out_path = get_paths().base_dir / "industry_maps" / safe
            overrides_merged[industry] = _merge_industry_override(industry=industry, override_cfg=cfg, out_path=out_path)

    validation_conflicts, validation_summary = _validate_dynamic_vectors(
        model=model,
        industries=sorted(overrides_merged.keys()),
        overrides=overrides_merged,
    )

    combined_conflicts = list(report.conflicts) + grounding_conflicts + validation_conflicts
    if validation_conflicts or grounding_conflicts:
        final_hitl_decision = "mandatory"
        final_risk = "high"
        final_confidence = min(0.5, float(report.confidence))
    else:
        final_hitl_decision = report.hitl_decision
        final_risk = report.risk_level
        final_confidence = float(report.confidence)

    review_required = final_hitl_decision == "mandatory"
    review_recommended = final_hitl_decision == "recommended"

    applied = False
    can_apply = final_hitl_decision == "none" or request.hitl_approved
    if request.apply and can_apply:
        write_condensed_emba_ontology(proposed.model_dump(mode="json"))

        for industry, cfg in overrides_merged.items():
            safe = Path(f"{industry}.json").name
            out_path = get_paths().base_dir / "industry_maps" / safe
            _atomic_write_json(out_path, cfg)
        applied = True

    override_industries: list[str] = []
    if isinstance(overrides_obj, dict):
        override_industries = [k for k in overrides_obj.keys() if isinstance(k, str)]

    audit_path = get_paths().base_dir / "ontology" / "update_audit.jsonl"
    _append_jsonl(
        audit_path,
        {
            "type": "update_run",
            "ts": _utc_now_iso(),
            "audit_id": audit_id,
            "thread_id": request.thread_id,
            "filename": request.filename,
            "model_name": request.model_name,
            "apply_requested": request.apply,
            "hitl_approved": request.hitl_approved,
            "reviewer": request.reviewer,
            "hitl_decision": final_hitl_decision,
            "risk_level": final_risk,
            "confidence": final_confidence,
            "conflicts": combined_conflicts,
            "validation_summary": validation_summary,
            "applied": applied,
            "proposed": {
                "version": proposed.version,
                "node_count": len(proposed.nodes),
                "edge_count": len(proposed.edges),
            },
            "override_industries": override_industries,
        },
    )

    return OntologyUpdateRunResponse(
        success=True,
        applied=applied,
        audit_id=audit_id,
        hitl_decision=final_hitl_decision,
        review_required=review_required,
        review_recommended=review_recommended,
        risk_level=final_risk,
        confidence=final_confidence,
        conflicts=combined_conflicts,
    )


@router.post("/update/feedback", response_model=OntologyUpdateFeedbackResponse)
async def submit_update_feedback(request: OntologyUpdateFeedbackRequest) -> OntologyUpdateFeedbackResponse:
    outcome = (request.outcome or "").strip().lower()
    if outcome not in {"positive", "negative", "neutral"}:
        raise HTTPException(status_code=400, detail="Invalid outcome")

    node_ids = [nid.strip() for nid in (request.node_ids or []) if isinstance(nid, str) and nid.strip()]
    edge_keys = [ek.strip() for ek in (request.edge_keys or []) if isinstance(ek, str) and ek.strip()]
    if not node_ids and not edge_keys:
        raise HTTPException(status_code=400, detail="Missing node_ids or edge_keys")

    current = get_condensed_emba_ontology()
    known_node_ids = {n.id for n in current.nodes if isinstance(n.id, str) and n.id.strip()}
    known_edge_keys: set[str] = set()
    for e in current.edges:
        try:
            d = e.model_dump(mode="json")
        except Exception:
            continue
        ek = d.get("edge_key")
        if isinstance(ek, str) and ek.strip():
            known_edge_keys.add(ek.strip())

    unknown_nodes = [nid for nid in node_ids if nid not in known_node_ids]
    unknown_edges = [ek for ek in edge_keys if ek not in known_edge_keys]
    if unknown_nodes or unknown_edges:
        raise HTTPException(status_code=422, detail={"unknown_node_ids": unknown_nodes, "unknown_edge_keys": unknown_edges})

    paths = get_paths()
    feedback_path = paths.base_dir / "ontology" / "update_feedback.json"
    data: dict = {"version": 1, "weights": {}}
    if feedback_path.exists():
        try:
            data = json.loads(feedback_path.read_text(encoding="utf-8"))
        except Exception:
            data = {"version": 1, "weights": {}}

    weights: dict = data.get("weights") if isinstance(data.get("weights"), dict) else {}
    data["weights"] = weights

    def bump(key: str) -> None:
        entry = weights.get(key)
        if not isinstance(entry, dict):
            entry = {"weight": 1.0, "positive": 0, "negative": 0}
            weights[key] = entry
        w = float(entry.get("weight", 1.0))
        if outcome == "positive":
            entry["positive"] = int(entry.get("positive", 0)) + 1
            w = min(2.0, w + 0.05)
        elif outcome == "negative":
            entry["negative"] = int(entry.get("negative", 0)) + 1
            w = max(0.1, w - 0.05)
        entry["weight"] = w

    for nid in node_ids:
        bump(f"node:{nid}")
    for ek in edge_keys:
        bump(f"edge:{ek}")

    data["last_updated"] = _utc_now_iso()
    _atomic_write_json(feedback_path, data)

    _append_jsonl(
        paths.base_dir / "ontology" / "update_audit.jsonl",
        {
            "type": "update_feedback",
            "ts": _utc_now_iso(),
            "audit_id": request.audit_id,
            "outcome": outcome,
            "reviewer": request.reviewer,
            "notes": request.notes,
            "node_ids": node_ids,
            "edge_keys": edge_keys,
        },
    )

    return OntologyUpdateFeedbackResponse(success=True)


@router.post("/upload", response_model=OntologyUploadResponse)
async def upload_condensed_emba_ontology(file: UploadFile = File(...)) -> OntologyUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    safe_filename = Path(file.filename).name
    if safe_filename.lower() not in {"condensed_emba.json", "condensed-emba.json"} and not safe_filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json ontology uploads are supported")

    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e

    try:
        validated = CondensedEmbaOntology.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ontology validation failed: {e}") from e

    ontology = write_condensed_emba_ontology(validated.model_dump(mode="json"))
    paths = get_paths()
    stored_path = paths.condensed_emba_ontology_file

    logger.info("Uploaded condensed EMBA ontology: nodes=%d edges=%d path=%s", len(ontology.nodes), len(ontology.edges), stored_path)
    return OntologyUploadResponse(
        success=True,
        version=ontology.version,
        node_count=len(ontology.nodes),
        edge_count=len(ontology.edges),
        path=str(stored_path),
    )


@router.get("/current", response_model=OntologyCurrentResponse)
async def get_current_condensed_emba_ontology() -> OntologyCurrentResponse:
    paths = get_paths()
    path = paths.condensed_emba_ontology_file
    if not path.exists():
        return OntologyCurrentResponse(exists=False)

    try:
        ontology = CondensedEmbaOntology.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load stored ontology: {e}") from e

    stat = path.stat()
    return OntologyCurrentResponse(
        exists=True,
        version=ontology.version,
        node_count=len(ontology.nodes),
        edge_count=len(ontology.edges),
        updated=stat.st_mtime,
    )
