import asyncio
import json

from src.config.paths import Paths
from src.gateway.routers import ontology


def test_submit_update_feedback_persists_weights(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.paths._paths", Paths(tmp_path))
    (tmp_path / "ontology").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ontology" / "condensed_emba.json").write_text(
        json.dumps(
            {
                "version": "1",
                "nodes": [{"id": "n1", "title": "N1"}],
                "edges": [{"source": "n1", "target": "n1", "relation": "causes", "edge_key": "e1"}],
            }
        ),
        encoding="utf-8",
    )

    req = ontology.OntologyUpdateFeedbackRequest(
        audit_id="a1",
        outcome="positive",
        node_ids=["n1"],
        edge_keys=["e1"],
    )
    result = asyncio.run(ontology.submit_update_feedback(req))

    assert result.success is True
    fp = tmp_path / "ontology" / "update_feedback.json"
    assert fp.exists()
    data = json.loads(fp.read_text(encoding="utf-8"))
    weights = data["weights"]
    assert weights["node:n1"]["weight"] > 1.0
    assert weights["edge:e1"]["weight"] > 1.0
