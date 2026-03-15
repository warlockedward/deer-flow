from langchain.tools import tool

from src.config.ontology_config import search_condensed_emba_nodes


@tool("lookup_emba_ontology")
def lookup_emba_ontology(query: str, limit: int = 8) -> dict:
    """Lookup Condensed EMBA ontology nodes by free-text query."""
    nodes = search_condensed_emba_nodes(query, limit=limit)
    return {"nodes": [n.model_dump(mode="json") for n in nodes]}
