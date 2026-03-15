from __future__ import annotations

import json
import math
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain.tools import tool

from src.config.paths import get_paths

_INDUSTRY_MAPS_DIR = Path(__file__).parent.parent.parent / "config" / "industry_maps"
_DEFAULT_INDUSTRY = "traditional_manufacturing"
_FEEDBACK_FILE = Path(__file__).parent.parent.parent / "data" / "bayesian_feedback.json"

_HIGH_VALUE_CONTRACT_VALUE = 1_000_000.0
_RECENCY_CUTOFF_DAYS = 180.0
_HOT_WINDOW_MINUTES = 15.0


def _load_feedback() -> dict[str, Any]:
    if not _FEEDBACK_FILE.exists():
        return {"priors": {}, "signal_weights": {}, "confidence_thresholds": {}, "review_records": [], "conversion_path_weights": {}}
    try:
        with _FEEDBACK_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"priors": {}, "signal_weights": {}, "confidence_thresholds": {}, "review_records": [], "conversion_path_weights": {}}
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
    except Exception:
        return {"priors": {}, "signal_weights": {}, "confidence_thresholds": {}, "review_records": [], "conversion_path_weights": {}}


def _save_feedback(data: dict[str, Any]) -> None:
    _FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(mode="w", dir=_FEEDBACK_FILE.parent, suffix=".tmp", delete=False, encoding="utf-8")
    try:
        json.dump(data, fd, ensure_ascii=False, indent=2)
        fd.close()
        Path(fd.name).replace(_FEEDBACK_FILE)
    except BaseException:
        fd.close()
        Path(fd.name).unlink(missing_ok=True)
        raise


def record_conversion_feedback(*, client: str, industry: str, outcome: str) -> float:
    out = (outcome or "").strip().lower()
    if out not in {"positive", "negative", "neutral"}:
        raise ValueError("Invalid outcome")

    feedback = _load_feedback()
    path_weights = feedback.get("conversion_path_weights")
    if not isinstance(path_weights, dict):
        path_weights = {}
        feedback["conversion_path_weights"] = path_weights

    key = f"{client}:{industry}"
    current = _safe_float(path_weights.get(key))
    w = 1.0 if current is None else float(current)
    if out == "positive":
        w = min(1.2, w + 0.02)
    elif out == "negative":
        w = max(0.8, w - 0.02)
    path_weights[key] = round(w, 4)
    feedback["last_updated"] = datetime.now(tz=UTC).isoformat()
    _save_feedback(feedback)
    return float(path_weights[key])


def load_industry_config(industry: str) -> dict[str, Any]:
    override_path = get_paths().base_dir / "industry_maps" / f"{industry}.json"
    if override_path.exists():
        return json.loads(override_path.read_text(encoding="utf-8"))

    path = _INDUSTRY_MAPS_DIR / f"{industry}.json"
    if not path.exists():
        raise FileNotFoundError(f"Industry config not found: {path}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Industry config must be a JSON object")
        return data


def _parse_dt(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _text_contains_any(haystack: str, needles: list[str]) -> bool:
    h = (haystack or "").lower()
    return any(n.lower() in h for n in needles)


def _source_map(signals: list[dict[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for s in signals:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip()
        if not name:
            continue
        source = str(s.get("source", "unknown")).strip() or "unknown"
        out.setdefault(name, set()).add(source)
    return out


def _extract_dimensions(signals: list[dict[str, Any]]) -> set[str]:
    dims: set[str] = set()
    for s in signals:
        if not isinstance(s, dict):
            continue
        dim = str(s.get("dimension", "")).strip()
        if dim and dim != "unknown":
            dims.add(dim)
    return dims


def _recency_score(signals: list[dict[str, Any]]) -> float:
    now = datetime.now(tz=UTC)
    weights: list[float] = []
    hot = 0.0
    for s in signals:
        if not isinstance(s, dict):
            continue
        ts = _parse_dt(str(s.get("timestamp", "")))
        if ts is None:
            continue
        age_minutes = (now - ts).total_seconds() / 60.0
        age_days = age_minutes / (60.0 * 24.0)
        if age_days > _RECENCY_CUTOFF_DAYS:
            continue
        weights.append(math.exp(-age_days / 60.0))
        if age_minutes <= _HOT_WINDOW_MINUTES:
            hot = 1.0
    if not weights:
        return 0.0
    base = sum(weights) / float(len(weights))
    return _clamp01(0.7 * base + 0.3 * hot)


def _benchmark_deviation_score(benchmark_deviations: dict[str, Any] | None) -> float:
    if not benchmark_deviations:
        return 0.0
    vals: list[float] = []
    for v in benchmark_deviations.values():
        fv = _safe_float(v)
        if fv is None:
            continue
        vals.append(abs(fv))
    if not vals:
        return 0.0
    max_abs = max(vals)
    return _clamp01(max_abs / 0.30)


def _conflict_index(*, vision_statement: str | None, rd_ratio: float | None) -> float:
    if not vision_statement:
        return 0.0
    claims_innovation = _text_contains_any(vision_statement, ["innovation", "innovative", "研发", "科技创新", "技术驱动"])
    if not claims_innovation:
        return 0.0
    if rd_ratio is None:
        return 0.3
    if rd_ratio < 0.03:
        return 1.0
    if rd_ratio < 0.06:
        return 0.5
    return 0.0


def _potential_value_score(*, estimated_contract_value: float | None, company_profile: dict[str, Any] | None) -> tuple[float, list[str], bool]:
    reasons: list[str] = []
    hitl_mandatory = False

    contract_score = 0.0
    if estimated_contract_value is not None:
        if estimated_contract_value >= _HIGH_VALUE_CONTRACT_VALUE:
            hitl_mandatory = True
            reasons.append("HIGH_VALUE_CONTRACT")
        contract_score = _clamp01(estimated_contract_value / _HIGH_VALUE_CONTRACT_VALUE)

    size_score = 0.0
    if company_profile and isinstance(company_profile, dict):
        employees = _safe_float(company_profile.get("employees"))
        revenue = _safe_float(company_profile.get("annual_revenue"))
        cash = _safe_float(company_profile.get("cash"))

        parts: list[float] = []
        if employees is not None:
            parts.append(_clamp01(math.log10(max(1.0, employees)) / 5.0))
        if revenue is not None:
            parts.append(_clamp01(math.log10(max(1.0, revenue)) / 10.0))
        if cash is not None:
            parts.append(_clamp01(math.log10(max(1.0, cash)) / 10.0))

        if parts:
            size_score = sum(parts) / float(len(parts))

    return _clamp01(0.65 * contract_score + 0.35 * size_score), reasons, hitl_mandatory


def _severity_urgency_score(*, financial_indicators: dict[str, Any] | None, signals: list[dict[str, Any]]) -> float:
    fin = financial_indicators if isinstance(financial_indicators, dict) else {}
    profit_decline = _safe_float(fin.get("profit_decline_rate"))
    ar_turnover_decline = _safe_float(fin.get("accounts_receivable_turnover_decline_rate"))

    fin_parts: list[float] = []
    if profit_decline is not None:
        fin_parts.append(_clamp01(profit_decline / 0.30))
    if ar_turnover_decline is not None:
        fin_parts.append(_clamp01(ar_turnover_decline / 0.25))
    fin_score = sum(fin_parts) / float(len(fin_parts)) if fin_parts else 0.0

    critical_names = ["CTO_departure", "Key_talent_departure", "urgent recruitment", "frontline sales", "sales staff", "cash_flow_crisis"]
    behavior_score = 0.0
    for s in signals:
        name = str(s.get("name", "")).strip()
        sev = str(s.get("severity", "")).strip().lower()
        if sev in {"critical", "high"}:
            behavior_score = max(behavior_score, 1.0 if sev == "critical" else 0.8)
        if name and _text_contains_any(name, critical_names):
            behavior_score = max(behavior_score, 0.8)

    return _clamp01(0.55 * fin_score + 0.45 * behavior_score)


def _logic_confidence_score(*, signals: list[dict[str, Any]], industry_config: dict[str, Any], benchmark_deviations: dict[str, Any] | None) -> tuple[float, list[str], bool]:
    reasons: list[str] = []

    signals_cfg = industry_config.get("signals") or {}
    multi_source_threshold = int(signals_cfg.get("multi_source_threshold", 2))

    confidence_cfg = industry_config.get("confidence") or {}
    min_verified_symptoms = int(confidence_cfg.get("min_verified_symptoms", 2))
    min_sources_total = int(confidence_cfg.get("min_sources_total", 2))
    min_dimensions = int(confidence_cfg.get("min_dimensions", 2))

    source_map = _source_map(signals)
    verified = {name for name, sources in source_map.items() if len(sources) >= multi_source_threshold}
    unique_symptoms = set(source_map.keys())

    verified_ratio = 0.0
    if unique_symptoms:
        verified_ratio = len(verified) / float(len(unique_symptoms))

    sources_total = len({src for sources in source_map.values() for src in sources})
    dims = _extract_dimensions(signals)

    completeness = _clamp01(
        0.45 * _clamp01(len(verified) / max(1.0, float(min_verified_symptoms)))
        + 0.35 * _clamp01(sources_total / max(1.0, float(min_sources_total)))
        + 0.20 * _clamp01(len(dims) / max(1.0, float(min_dimensions)))
    )

    circuit_breaker = False
    if len(verified) < min_verified_symptoms:
        reasons.append("TOO_SPARSE")
        circuit_breaker = True
    if sources_total < min_sources_total:
        reasons.append("INSUFFICIENT_SOURCES")
        circuit_breaker = True
    if len(dims) < min_dimensions:
        reasons.append("SINGLE_DIMENSION")

    benchmark_ok = benchmark_deviations is not None and len(benchmark_deviations) > 0
    if not benchmark_ok:
        reasons.append("MISSING_BENCHMARK_DEVIATIONS")

    score = _clamp01(0.55 * verified_ratio + 0.45 * completeness)
    if not benchmark_ok:
        score *= 0.85

    return score, reasons, circuit_breaker


@dataclass(frozen=True)
class LeadScoreResult:
    total_score: float
    category: str
    hitl_required: bool
    reasons: list[str]
    components: dict[str, float]
    circuit_breaker_triggered: bool

    def model_dump(self) -> dict[str, Any]:
        return {
            "total_score": float(self.total_score),
            "category": self.category,
            "hitl_required": bool(self.hitl_required),
            "reasons": list(self.reasons),
            "components": {k: float(v) for k, v in self.components.items()},
            "circuit_breaker_triggered": bool(self.circuit_breaker_triggered),
        }


def compute_lead_score(*, lead: dict[str, Any], client: str = "action_education") -> LeadScoreResult:
    industry = str(lead.get("industry") or _DEFAULT_INDUSTRY)
    industry_config = load_industry_config(industry)

    signals_raw = lead.get("signals") or []
    signals: list[dict[str, Any]] = [s for s in signals_raw if isinstance(s, dict)]

    estimated_contract_value = _safe_float(lead.get("estimated_contract_value"))
    company_profile = lead.get("company_profile") if isinstance(lead.get("company_profile"), dict) else None
    financial_indicators = lead.get("financial_indicators") if isinstance(lead.get("financial_indicators"), dict) else None
    benchmark_deviations = lead.get("benchmark_deviations") if isinstance(lead.get("benchmark_deviations"), dict) else None
    vision_statement = str(lead.get("vision_statement") or "")

    rd_ratio = None
    if isinstance(lead.get("investment_flows"), dict):
        rd_ratio = _safe_float(lead["investment_flows"].get("r_and_d_ratio") or lead["investment_flows"].get("rd_ratio") or lead["investment_flows"].get("rd_budget_pct"))
    if rd_ratio is None:
        rd_ratio = _safe_float(lead.get("r_and_d_ratio"))

    potential_value, pv_reasons, hitl_by_value = _potential_value_score(estimated_contract_value=estimated_contract_value, company_profile=company_profile)
    severity = _severity_urgency_score(financial_indicators=financial_indicators, signals=signals)
    logic_conf, lc_reasons, circuit_breaker = _logic_confidence_score(signals=signals, industry_config=industry_config, benchmark_deviations=benchmark_deviations)
    conflict = _conflict_index(vision_statement=vision_statement, rd_ratio=rd_ratio)
    benchmark = _benchmark_deviation_score(benchmark_deviations)
    recency = _recency_score(signals)

    feedback = _load_feedback()
    path_weights = feedback.get("conversion_path_weights") if isinstance(feedback, dict) else None
    fb_multiplier = 1.0
    if isinstance(path_weights, dict):
        raw = _safe_float(path_weights.get(f"{client}:{industry}"))
        if raw is not None:
            fb_multiplier = max(0.8, min(1.2, raw))

    components = {
        "potential_value": potential_value,
        "pain_severity_urgency": severity,
        "logic_confidence": logic_conf,
        "conflict_index": conflict,
        "industry_benchmark_deviation": benchmark,
        "recency_time_decay": recency,
        "feedback_loop_weight": _clamp01((fb_multiplier - 0.8) / 0.4),
    }

    base = (
        0.32 * potential_value
        + 0.26 * severity
        + 0.20 * logic_conf
        + 0.10 * conflict
        + 0.08 * benchmark
        + 0.04 * recency
    )
    total = 100.0 * _clamp01(base) * fb_multiplier

    reasons: list[str] = []
    reasons.extend(pv_reasons)
    reasons.extend(lc_reasons)
    if conflict >= 0.8:
        reasons.append("VISION_BEHAVIOR_CONFLICT")
    if recency >= 0.7:
        reasons.append("FRESH_SIGNAL_WINDOW")

    category = "C"
    if hitl_by_value:
        category = "A"
    elif total >= 80.0:
        category = "A"
    elif total >= 50.0:
        category = "B"

    hitl_required = hitl_by_value or category == "A"
    if hitl_required and "HITL_REQUIRED" not in reasons:
        reasons.append("HITL_REQUIRED")

    return LeadScoreResult(
        total_score=round(total, 3),
        category=category,
        hitl_required=hitl_required,
        reasons=reasons,
        components=components,
        circuit_breaker_triggered=circuit_breaker,
    )


@tool("score_lead")
def score_lead(
    runtime: Any,
    lead: dict[str, Any],
    client: str = "action_education",
) -> dict[str, Any]:
    """为企业线索计算自动评分与 A/B/C 分类，并在高价值时触发 HITL。"""
    _ = runtime.context.get("thread_id") if runtime is not None else None
    return compute_lead_score(lead=lead, client=client).model_dump()
