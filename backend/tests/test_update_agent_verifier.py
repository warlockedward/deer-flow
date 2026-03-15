from src.config.ontology_config import CondensedEmbaOntology


def test_hitl_mandatory_when_conflict_present():
    from src.config.update_agent_verifier import decide_hitl

    current = CondensedEmbaOntology(version="1", nodes=[{"id": "a", "title": "A"}], edges=[])
    proposed = CondensedEmbaOntology(version="2", nodes=[{"id": "a", "title": "A"}], edges=[{"source": "a", "target": "a", "relation": "cause"}])

    report = decide_hitl(current=current, proposed=proposed)
    assert report.hitl_decision == "mandatory"
    assert report.conflicts


def test_hitl_mandatory_when_confidence_below_threshold():
    from src.config.update_agent_verifier import decide_hitl

    current = CondensedEmbaOntology(version="1", nodes=[{"id": "a", "title": "A"}], edges=[])
    proposed = CondensedEmbaOntology(
        version="2",
        nodes=[{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
        edges=[],
    )

    report = decide_hitl(current=current, proposed=proposed)
    assert report.confidence < 0.85
    assert report.hitl_decision == "mandatory"


def test_hitl_recommended_when_confidence_in_middle_band():
    from src.config.update_agent_verifier import decide_hitl

    current = CondensedEmbaOntology(version="1", nodes=[{"id": "a", "title": "A"}], edges=[])
    proposed = CondensedEmbaOntology(
        version="2",
        nodes=[{"id": "a", "title": "A"}, {"id": "b", "title": "B", "source_quote": "p3: ..."}],
        edges=[],
    )

    report = decide_hitl(current=current, proposed=proposed)
    assert 0.85 <= report.confidence < 0.95
    assert report.hitl_decision == "recommended"


def test_hitl_none_when_high_confidence_no_conflict_low_risk():
    from src.config.update_agent_verifier import decide_hitl

    current = CondensedEmbaOntology(version="1", nodes=[], edges=[])
    proposed = CondensedEmbaOntology(version="2", nodes=[{"id": "b", "title": "B", "source_quote": "p3: ..."}], edges=[])

    report = decide_hitl(current=current, proposed=proposed)
    assert report.confidence >= 0.95
    assert report.hitl_decision == "none"

