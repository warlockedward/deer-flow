import json
import math
from datetime import datetime
from pathlib import Path

from langchain.tools import tool
from pgmpy.factors.discrete import TabularCPD
from pgmpy.inference import VariableElimination
from pgmpy.models import DiscreteBayesianNetwork

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
    path = _INDUSTRY_MAPS_DIR / f"{industry}.json"
    if not path.exists():
        raise FileNotFoundError(f"Industry config not found: {path}")
    with path.open() as f:
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
        return {"priors": {}, "signal_weights": {}}
    try:
        with _FEEDBACK_FILE.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"priors": {}, "signal_weights": {}}


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


@tool("calculate_bayesian_risk", parse_docstring=True)
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
    decay_rate = config["signals"]["decay_rate_months"]
    multi_source_threshold = config["signals"]["multi_source_threshold"]

    source_map: dict[str, set[str]] = {}
    for sig in symptoms:
        name = sig["name"]
        source = sig.get("source", "unknown")
        timestamp = sig.get("timestamp", datetime.now().strftime("%Y-%m-%d"))
        signal_date = datetime.fromisoformat(timestamp)
        age_months = (datetime.now() - signal_date).days / 30.0
        if age_months > decay_rate:
            continue
        source_map.setdefault(name, set()).add(source)

    verified = {name for name, sources in source_map.items() if len(sources) >= multi_source_threshold}
    return _infer_from_config(config, verified)


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
