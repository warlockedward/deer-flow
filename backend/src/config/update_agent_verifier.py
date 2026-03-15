from __future__ import annotations

from dataclasses import dataclass

from src.config.ontology_config import CondensedEmbaOntology


@dataclass(frozen=True)
class UpdateDecisionReport:
    risk_level: str
    confidence: float
    conflicts: list[str]
    hitl_decision: str


def _detect_cycles(ontology: CondensedEmbaOntology) -> bool:
    adj: dict[str, list[str]] = {}
    for e in ontology.edges:
        adj.setdefault(e.source, []).append(e.target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(n: str) -> bool:
        if n in visiting:
            return True
        if n in visited:
            return False
        visiting.add(n)
        for nxt in adj.get(n, []):
            if dfs(nxt):
                return True
        visiting.remove(n)
        visited.add(n)
        return False

    for node in adj:
        if dfs(node):
            return True
    return False


def _node_ids(ontology: CondensedEmbaOntology) -> set[str]:
    return {n.id for n in ontology.nodes}


def _grounded_new_node_ratio(current: CondensedEmbaOntology, proposed: CondensedEmbaOntology) -> float:
    current_ids = _node_ids(current)
    new_nodes = [n for n in proposed.nodes if n.id not in current_ids]
    if not new_nodes:
        return 1.0
    grounded = 0
    for n in new_nodes:
        sq = getattr(n, "source_quote", None)
        if isinstance(sq, str) and sq.strip():
            grounded += 1
    return grounded / max(1, len(new_nodes))


def _confidence_score(current: CondensedEmbaOntology, proposed: CondensedEmbaOntology) -> float:
    ratio = _grounded_new_node_ratio(current, proposed)
    if ratio <= 0:
        return 0.0
    if current.nodes and ratio > 0:
        return min(0.94, ratio)
    return ratio


def _risk_level(current: CondensedEmbaOntology, proposed: CondensedEmbaOntology, conflicts: list[str]) -> str:
    if conflicts:
        return "high"

    current_ids = _node_ids(current)
    proposed_ids = _node_ids(proposed)
    if current_ids - proposed_ids:
        return "high"

    current_edges = {(e.source, e.target, e.relation) for e in current.edges}
    proposed_edges = {(e.source, e.target, e.relation) for e in proposed.edges}
    if current_edges - proposed_edges:
        return "high"

    if proposed_ids - current_ids:
        return "medium" if current.nodes else "low"

    if proposed_edges - current_edges:
        return "medium" if current.edges else "low"

    return "low"


def decide_hitl(*, current: CondensedEmbaOntology, proposed: CondensedEmbaOntology) -> UpdateDecisionReport:
    conflicts: list[str] = []

    node_ids = _node_ids(proposed)
    for e in proposed.edges:
        if e.source not in node_ids:
            conflicts.append(f"MISSING_NODE:{e.source}")
        if e.target not in node_ids:
            conflicts.append(f"MISSING_NODE:{e.target}")

    if _detect_cycles(proposed):
        conflicts.append("DAG_CYCLE")

    confidence = float(_confidence_score(current, proposed))
    risk = _risk_level(current, proposed, conflicts)

    if conflicts:
        hitl = "mandatory"
    elif risk == "high":
        hitl = "mandatory"
    elif confidence < 0.85:
        hitl = "mandatory"
    elif confidence < 0.95:
        hitl = "recommended"
    else:
        hitl = "none"

    return UpdateDecisionReport(
        risk_level=risk,
        confidence=confidence,
        conflicts=conflicts,
        hitl_decision=hitl,
    )

