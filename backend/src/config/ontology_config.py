import json
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.config.paths import get_paths


class OntologyNode(BaseModel):
    id: str
    title: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    model_config = ConfigDict(extra="allow")


class OntologyEdge(BaseModel):
    source: str
    target: str
    relation: str | None = None
    model_config = ConfigDict(extra="allow")


class CondensedEmbaOntology(BaseModel):
    version: str | None = None
    nodes: list[OntologyNode] = Field(default_factory=list)
    edges: list[OntologyEdge] = Field(default_factory=list)
    model_config = ConfigDict(extra="allow")


_cached_ontology: CondensedEmbaOntology | None = None
_cached_mtime: float | None = None


def _ontology_path() -> Path:
    return get_paths().condensed_emba_ontology_file


def get_condensed_emba_ontology() -> CondensedEmbaOntology:
    global _cached_mtime, _cached_ontology

    path = _ontology_path()
    if not path.exists():
        _cached_ontology = CondensedEmbaOntology(version=None, nodes=[], edges=[])
        _cached_mtime = None
        return _cached_ontology

    mtime = path.stat().st_mtime
    if _cached_ontology is not None and _cached_mtime == mtime:
        return _cached_ontology

    data = json.loads(path.read_text(encoding="utf-8"))
    _cached_ontology = CondensedEmbaOntology.model_validate(data)
    _cached_mtime = mtime
    return _cached_ontology


def reload_condensed_emba_ontology() -> CondensedEmbaOntology:
    global _cached_mtime, _cached_ontology
    _cached_mtime = None
    _cached_ontology = None
    return get_condensed_emba_ontology()


def write_condensed_emba_ontology(data: dict[str, Any]) -> CondensedEmbaOntology:
    ontology = CondensedEmbaOntology.model_validate(data)
    path = _ontology_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(mode="w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8")
    try:
        json.dump(ontology.model_dump(mode="json"), fd, ensure_ascii=False, indent=2)
        fd.close()
        Path(fd.name).replace(path)
    except BaseException:
        fd.close()
        Path(fd.name).unlink(missing_ok=True)
        raise
    return reload_condensed_emba_ontology()


def search_condensed_emba_nodes(query: str, *, limit: int = 8) -> list[OntologyNode]:
    q = (query or "").strip().lower()
    ontology = get_condensed_emba_ontology()
    if not q:
        return ontology.nodes[: max(0, limit)]

    hits: list[OntologyNode] = []
    for node in ontology.nodes:
        hay = f"{node.id} {node.title} {node.description or ''}".lower()
        if q in hay:
            hits.append(node)
            if len(hits) >= limit:
                break
    return hits
