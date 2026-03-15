import json
import math
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId
from langgraph.types import Command
from pgmpy.factors.discrete import TabularCPD
from pgmpy.inference import VariableElimination
from pgmpy.models import DiscreteBayesianNetwork

from src.config.paths import get_paths

MANAGEMENT_GAP = "Management_Gap"

STRENGTH_CPD_VALUES: dict[str, list[list[float]]] = {
    "strong": [[0.9, 0.2], [0.1, 0.8]],
    "medium": [[0.7, 0.3], [0.3, 0.7]],
    "weak": [[0.6, 0.4], [0.4, 0.6]],
}

_INDUSTRY_MAPS_DIR = Path(__file__).parent.parent.parent / "config" / "industry_maps"

_DEFAULT_INDUSTRY = "traditional_manufacturing"
_FEEDBACK_FILE = Path(__file__).parent.parent.parent / "data" / "bayesian_feedback.json"

CTO_DEPARTURE = "CTO_departure"
RD_DROP = "R&D_drop"
_V1_KNOWN_SYMPTOMS = {CTO_DEPARTURE, RD_DROP}


def load_industry_config(industry: str) -> dict:
    override_path = get_paths().base_dir / "industry_maps" / f"{industry}.json"
    if override_path.exists():
        return json.loads(override_path.read_text(encoding="utf-8"))

    path = _INDUSTRY_MAPS_DIR / f"{industry}.json"
    if not path.exists():
        raise FileNotFoundError(f"Industry config not found: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def build_network(config: dict) -> DiscreteBayesianNetwork:
    relationships = config.get("causal_relationships", [])
    edges = [(MANAGEMENT_GAP, r["effect"]) for r in relationships]
    if not edges:
        raise ValueError("causal_relationships must contain at least one entry")

    model = DiscreteBayesianNetwork(edges)

    cpd_mg = TabularCPD(variable=MANAGEMENT_GAP, variable_card=2, values=[[0.8], [0.2]])
    model.add_cpds(cpd_mg)

    for rel in relationships:
        effect = rel["effect"]
        strength = rel.get("strength", "medium")
        cpd_values = STRENGTH_CPD_VALUES.get(strength, STRENGTH_CPD_VALUES["medium"])
        cpd = TabularCPD(
            variable=effect,
            variable_card=2,
            values=cpd_values,
            evidence=[MANAGEMENT_GAP],
            evidence_card=[2],
        )
        model.add_cpds(cpd)

    if not model.check_model():
        raise ValueError("Built Bayesian network failed validation")
    return model


def apply_time_decay(timestamp: str, decay_rate_months: float) -> float:
    signal_date = datetime.fromisoformat(timestamp)
    age_months = (datetime.now() - signal_date).days / 30.0
    return math.exp(-age_months / decay_rate_months)


def _load_feedback() -> dict:
    """Load RLHF feedback data for dynamic prior adjustment."""
    if not _FEEDBACK_FILE.exists():
        return {"priors": {}, "signal_weights": {}, "confidence_thresholds": {}, "review_records": [], "conversion_path_weights": {}}
    try:
        with _FEEDBACK_FILE.open() as f:
            data = json.load(f)
            if "priors" not in data:
                data["priors"] = {}
            if "signal_weights" not in data:
                data["signal_weights"] = {}
            if "confidence_thresholds" not in data:
                data["confidence_thresholds"] = {}
            if "review_records" not in data:
                data["review_records"] = []
            if "conversion_path_weights" not in data:
                data["conversion_path_weights"] = {}
            return data
    except (json.JSONDecodeError, FileNotFoundError):
        return {"priors": {}, "signal_weights": {}, "confidence_thresholds": {}, "review_records": [], "conversion_path_weights": {}}


def _get_confidence_config(industry_config: dict) -> dict[str, Any]:
    confidence_cfg = industry_config.get("confidence") or {}
    return {
        "threshold": float(confidence_cfg.get("threshold", 0.6)),
        "min_verified_symptoms": int(confidence_cfg.get("min_verified_symptoms", 2)),
        "min_sources_total": int(confidence_cfg.get("min_sources_total", 2)),
        "min_dimensions": int(confidence_cfg.get("min_dimensions", 2)),
        "benchmark_indifference_epsilon": float(confidence_cfg.get("benchmark_indifference_epsilon", 0.05)),
        "signal_dimensions": dict(confidence_cfg.get("signal_dimensions") or {}),
    }


def _extract_dimensions(symptoms: list[dict[str, Any]], signal_dimensions: dict[str, str]) -> set[str]:
    dims: set[str] = set()
    for sig in symptoms:
        name = str(sig.get("name", ""))
        dim = sig.get("dimension")
        if dim is None:
            dim = signal_dimensions.get(name)
        if not dim:
            dim = "unknown"
        if dim != "unknown":
            dims.add(str(dim))
    return dims


def _prepare_v2_evidence(symptoms: list[dict[str, Any]], industry_config: dict) -> tuple[set[str], dict[str, set[str]], list[dict[str, Any]]]:
    decay_rate = float(industry_config["signals"]["decay_rate_months"])
    multi_source_threshold = int(industry_config["signals"]["multi_source_threshold"])

    feedback = _load_feedback()
    signal_weight_adjustments = feedback.get("signal_weights") if isinstance(feedback, dict) else None
    if not isinstance(signal_weight_adjustments, dict):
        signal_weight_adjustments = {}

    source_map: dict[str, set[str]] = {}
    retained: list[dict[str, Any]] = []
    multipliers: dict[str, float] = {}

    for sig in symptoms:
        name = str(sig.get("name", "")).strip()
        if not name:
            continue
        source = str(sig.get("source", "unknown"))
        timestamp = str(sig.get("timestamp", datetime.now().strftime("%Y-%m-%d")))
        try:
            signal_date = datetime.fromisoformat(timestamp)
        except ValueError:
            continue

        age_months = (datetime.now() - signal_date).days / 30.0
        if age_months > decay_rate:
            continue

        retained.append({**sig, "name": name, "source": source, "timestamp": timestamp})
        source_map.setdefault(name, set()).add(source)

        if name not in multipliers:
            adj = signal_weight_adjustments.get(name, 0.0)
            try:
                adj_f = float(adj)
            except Exception:
                adj_f = 0.0
            multipliers[name] = max(0.1, min(2.0, 1.0 + adj_f))

    verified: set[str] = set()
    for name, sources in source_map.items():
        mult = multipliers.get(name, 1.0)
        if mult >= 1.0:
            required = max(1, int(math.ceil(multi_source_threshold / min(2.0, mult))))
        else:
            required = max(1, int(math.ceil(multi_source_threshold / max(0.25, mult))))
        required = min(5, required)
        if len(sources) >= required:
            verified.add(name)
    return verified, source_map, retained


def _save_feedback(feedback_data: dict) -> None:
    """Save RLHF feedback data."""
    _FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _FEEDBACK_FILE.open("w") as f:
        json.dump(feedback_data, f, indent=2)


def _infer_from_config(config: dict, verified_symptom_names: set[str]) -> float:
    # Apply RLHF feedback to adjust priors if available
    feedback = _load_feedback()
    prior_adjustments = feedback.get("priors", {})

    model = build_network(config)

    # Get the base priors
    cpd_mg = TabularCPD(variable=MANAGEMENT_GAP, variable_card=2, values=[[0.8], [0.2]])

    # Apply feedback adjustments to the Management_Gap prior
    if MANAGEMENT_GAP in prior_adjustments:
        adjustment = prior_adjustments[MANAGEMENT_GAP]
        # Adjust the prior probability of Management_Gap being present (index 1)
        base_prob_present = cpd_mg.values[1][0]
        adjusted_prob_present = min(0.95, max(0.05, base_prob_present + adjustment))
        cpd_mg.values = [[[1 - adjusted_prob_present]], [adjusted_prob_present]]

    model.add_cpds(cpd_mg)

    relationships = config.get("causal_relationships", [])
    for rel in relationships:
        effect = rel["effect"]
        strength = rel.get("strength", "medium")
        cpd_values = STRENGTH_CPD_VALUES.get(strength, STRENGTH_CPD_VALUES["medium"])
        cpd = TabularCPD(
            variable=effect,
            variable_card=2,
            values=cpd_values,
            evidence=[MANAGEMENT_GAP],
            evidence_card=[2],
        )
        model.add_cpds(cpd)

    if not model.check_model():
        raise ValueError("Built Bayesian network failed validation")

    infer = VariableElimination(model)
    effect_names = {r["effect"] for r in config.get("causal_relationships", [])}
    evidence = {name: 1 for name in verified_symptom_names if name in effect_names}
    result = infer.query(variables=[MANAGEMENT_GAP], evidence=evidence)
    return float(result.values[1])


def _run_v1_inference(symptoms: list[str]) -> float:
    model = DiscreteBayesianNetwork([(MANAGEMENT_GAP, CTO_DEPARTURE), (MANAGEMENT_GAP, RD_DROP)])
    cpd_mg = TabularCPD(variable=MANAGEMENT_GAP, variable_card=2, values=[[0.8], [0.2]])
    cpd_cd = TabularCPD(variable=CTO_DEPARTURE, variable_card=2, values=[[0.9, 0.3], [0.1, 0.7]], evidence=[MANAGEMENT_GAP], evidence_card=[2])
    cpd_rd = TabularCPD(variable=RD_DROP, variable_card=2, values=[[0.8, 0.2], [0.2, 0.8]], evidence=[MANAGEMENT_GAP], evidence_card=[2])
    model.add_cpds(cpd_mg, cpd_cd, cpd_rd)
    infer = VariableElimination(model)
    evidence = {s: 1 for s in symptoms if s in _V1_KNOWN_SYMPTOMS}
    result = infer.query(variables=[MANAGEMENT_GAP], evidence=evidence)
    return float(result.values[1])


@tool("calculate_bayesian_risk")
def calculate_bayesian_risk(symptoms: list) -> float:
    """Calculate the probability of a Management Gap given observed symptoms.

    Args:
        symptoms: A list of observed symptoms. Each item may be either a plain
            string (V1 API, e.g. "CTO_departure") or a dict with keys
            ``name``, ``timestamp`` (ISO date), and ``source`` (V2 API).
    """
    if not symptoms:
        return _run_v1_inference([])

    if isinstance(symptoms[0], str):
        return _run_v1_inference(symptoms)

    config = load_industry_config(_DEFAULT_INDUSTRY)
    verified, _, _ = _prepare_v2_evidence(symptoms, config)
    return _infer_from_config(config, verified)


def compute_circuit_breaker_state(*, symptoms: list, industry: str | None = None, benchmark_deviations: dict[str, float] | None = None) -> dict[str, Any]:
    resolved_industry = industry or _DEFAULT_INDUSTRY

    if not symptoms:
        return {
            "triggered": True,
            "industry": resolved_industry,
            "posterior_risk": float(_run_v1_inference([])),
            "confidence_score": 0.0,
            "allow_briefing": False,
            "reasons": ["NO_SIGNALS"],
            "verified_symptoms": [],
            "dimensions": [],
            "sources_total": 0,
        }

    if isinstance(symptoms[0], str):
        posterior = float(_run_v1_inference([str(s) for s in symptoms]))
        return {
            "triggered": True,
            "industry": resolved_industry,
            "posterior_risk": posterior,
            "confidence_score": 0.2,
            "allow_briefing": False,
            "reasons": ["V1_UNSTRUCTURED_SIGNALS"],
            "verified_symptoms": list(dict.fromkeys([str(s) for s in symptoms])),
            "dimensions": [],
            "sources_total": 0,
        }

    config = load_industry_config(resolved_industry)
    confidence_cfg = _get_confidence_config(config)

    feedback = _load_feedback()
    threshold_override = (feedback.get("confidence_thresholds") or {}).get(resolved_industry)
    if threshold_override is not None:
        confidence_threshold = float(threshold_override)
    else:
        confidence_threshold = float(confidence_cfg["threshold"])

    verified, source_map, retained = _prepare_v2_evidence(symptoms, config)
    posterior_risk = float(_infer_from_config(config, verified))

    sources_total = len({src for sources in source_map.values() for src in sources})
    dims = _extract_dimensions(retained, confidence_cfg["signal_dimensions"])

    if retained:
        recency = sum(apply_time_decay(str(sig["timestamp"]), float(config["signals"]["decay_rate_months"])) for sig in retained) / float(len(retained))
    else:
        recency = 0.0

    coverage_score = min(1.0, len(verified) / max(1, confidence_cfg["min_verified_symptoms"]))
    source_score = min(1.0, sources_total / max(1, confidence_cfg["min_sources_total"]))
    dimension_score = min(1.0, len(dims) / max(1, confidence_cfg["min_dimensions"]))

    benchmark_ok = True
    if benchmark_deviations is not None and len(benchmark_deviations) > 0:
        eps = float(confidence_cfg["benchmark_indifference_epsilon"])
        benchmark_ok = any(abs(float(v)) >= eps for v in benchmark_deviations.values())

    confidence_score = 0.35 * coverage_score + 0.25 * dimension_score + 0.2 * source_score + 0.2 * recency
    if not benchmark_ok:
        confidence_score *= 0.5

    reasons: list[str] = []
    if len(verified) < confidence_cfg["min_verified_symptoms"]:
        reasons.append("TOO_SPARSE")
    if sources_total < confidence_cfg["min_sources_total"]:
        reasons.append("INSUFFICIENT_SOURCES")
    if len(dims) < confidence_cfg["min_dimensions"]:
        reasons.append("SINGLE_DIMENSION")
    if not benchmark_ok:
        reasons.append("BENCHMARK_INDIFFERENT")
    if confidence_score < confidence_threshold:
        reasons.append("BELOW_CONFIDENCE_THRESHOLD")

    triggered = len(reasons) > 0
    return {
        "triggered": triggered,
        "industry": resolved_industry,
        "posterior_risk": posterior_risk,
        "confidence_score": float(confidence_score),
        "confidence_threshold": float(confidence_threshold),
        "allow_briefing": not triggered,
        "reasons": reasons,
        "verified_symptoms": sorted(verified),
        "dimensions": sorted(dims),
        "sources_total": sources_total,
    }


@tool("diagnose_management_gap")
def diagnose_management_gap(
    runtime: Any,
    symptoms: list,
    tool_call_id: Annotated[str, InjectedToolCallId],
    industry: str | None = None,
    benchmark_deviations: dict[str, float] | None = None,
) -> Command:
    """Compute posterior risk plus low-confidence circuit-breaker state."""
    runtime.context.get("thread_id") if runtime is not None else None
    cb_state = compute_circuit_breaker_state(symptoms=symptoms, industry=industry, benchmark_deviations=benchmark_deviations)
    msg = (
        f"Management_Gap posterior={float(cb_state.get('posterior_risk', 0.0)):.3f}, "
        f"confidence={float(cb_state.get('confidence_score', 0.0)):.3f} "
        f"(threshold={float(cb_state.get('confidence_threshold', 0.0)):.3f}), "
        f"triggered={bool(cb_state.get('triggered', True))}, reasons={cb_state.get('reasons', [])}"
    )
    return Command(update={"circuit_breaker": cb_state, "messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})


@tool("run_semantic_diagnosis")
def run_semantic_diagnosis(
    runtime: Any,
    company_name: str,
    industry: str,
    hitl_approved: bool = False,
    reviewer: str | None = None,
) -> dict:
    """运行确定性的语义诊断管线，并返回带硬门禁与审计信息的结果。"""
    from src.subagents.semantic_diagnosis_pipeline import run_semantic_diagnosis_pipeline

    thread_id = runtime.context.get("thread_id") if runtime is not None else None
    if not thread_id:
        raise ValueError("Thread ID is not available in runtime context")

    metadata = runtime.config.get("metadata", {}) if runtime is not None else {}
    model_name = metadata.get("model_name") if isinstance(metadata, dict) else None

    return run_semantic_diagnosis_pipeline(
        thread_id=str(thread_id),
        company_name=company_name,
        industry=industry,
        model_name=str(model_name) if model_name else None,
        hitl_approved=hitl_approved,
        reviewer=reviewer,
    )


def update_priors(signal_name: str = None, adjustment: float = 0.0, feedback_type: str = "prior") -> None:
    """Update priors based on RLHF feedback.

    Args:
        signal_name: Name of the signal to adjust (for signal weight adjustment)
        adjustment: Amount to adjust the prior/weight by (positive or negative)
        feedback_type: Type of feedback - "prior" for Management_Gap prior, "signal" for signal weight
    """
    feedback_data = _load_feedback()

    if feedback_type == "prior":
        if MANAGEMENT_GAP not in feedback_data["priors"]:
            feedback_data["priors"][MANAGEMENT_GAP] = 0.0
        feedback_data["priors"][MANAGEMENT_GAP] += adjustment
        # Keep adjustments within reasonable bounds
        feedback_data["priors"][MANAGEMENT_GAP] = max(-0.5, min(0.5, feedback_data["priors"][MANAGEMENT_GAP]))
    elif feedback_type == "signal" and signal_name:
        if "signal_weights" not in feedback_data:
            feedback_data["signal_weights"] = {}
        if signal_name not in feedback_data["signal_weights"]:
            feedback_data["signal_weights"][signal_name] = 0.0
        feedback_data["signal_weights"][signal_name] += adjustment
        # Keep signal weights within reasonable bounds
        feedback_data["signal_weights"][signal_name] = max(-1.0, min(1.0, feedback_data["signal_weights"][signal_name]))

    _save_feedback(feedback_data)


def store_review_record(lead_id: str, decision: str, reviewer_notes: str = "", comprehensive_score: float = 0.0, classification: str = "") -> None:
    """Store review records for algorithm optimization feedback.

    Args:
        lead_id: Unique identifier for the lead
        decision: Review decision (APPROVE/REJECT/MODIFY)
        reviewer_notes: Optional notes from the reviewer
        comprehensive_score: The calculated comprehensive value score
        classification: Lead classification (S/A/B/Observation)
    """
    feedback_data = _load_feedback()

    if "review_records" not in feedback_data:
        feedback_data["review_records"] = []

    record = {"lead_id": lead_id, "timestamp": datetime.now().isoformat(), "decision": decision, "reviewer_notes": reviewer_notes, "comprehensive_score": comprehensive_score, "classification": classification}

    feedback_data["review_records"].append(record)

    # Keep only last 1000 records to prevent unbounded growth
    if len(feedback_data["review_records"]) > 1000:
        feedback_data["review_records"] = feedback_data["review_records"][-1000:]

    _save_feedback(feedback_data)
