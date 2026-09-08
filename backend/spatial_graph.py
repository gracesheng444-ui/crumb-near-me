"""
A small, honest spatial graph the agent builds up incrementally.

Design principle: never assert a physical connection we don't actually have
evidence for. Nodes/edges only get added via seeding from known knowledge-base
data, or via learn_location() extracting a real fact from a description/photo.
Pathfinding either finds a real path through known edges, or says so.
"""
import json
from pathlib import Path

GRAPH_PATH = Path(__file__).parent / "spatial_graph.json"


def _empty():
    return {"nodes": {}, "edges": []}


def load() -> dict:
    if not GRAPH_PATH.exists():
        return _empty()
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def save(graph: dict) -> None:
    GRAPH_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_node(graph: dict, node_id: str, **attrs) -> None:
    node = graph["nodes"].setdefault(node_id, {})
    node.update({k: v for k, v in attrs.items() if v is not None})


def add_edge(graph: dict, a: str, b: str, relation: str, note: str = "") -> None:
    # avoid exact duplicate edges
    for e in graph["edges"]:
        if {e["from"], e["to"]} == {a, b} and e["relation"] == relation:
            return
    graph["edges"].append({"from": a, "to": b, "relation": relation, "note": note})


def neighbors(graph: dict, node_id: str):
    for e in graph["edges"]:
        if e["from"] == node_id:
            yield e["to"], e["relation"], e.get("note", "")
        elif e["to"] == node_id:
            yield e["from"], e["relation"], e.get("note", "")


def find_path(graph: dict, start_id: str, end_id: str):
    """Plain BFS over undirected relation edges. Returns a list of
    (node_id, relation_used_to_get_here, note) steps, or None if no known
    path connects them yet."""
    if start_id not in graph["nodes"] or end_id not in graph["nodes"]:
        return None
    if start_id == end_id:
        return [(start_id, None, "")]

    frontier = [start_id]
    came_from = {start_id: None}
    edge_used = {}

    while frontier:
        current = frontier.pop(0)
        if current == end_id:
            break
        for neighbor_id, relation, note in neighbors(graph, current):
            if neighbor_id not in came_from:
                came_from[neighbor_id] = current
                edge_used[neighbor_id] = (relation, note)
                frontier.append(neighbor_id)

    if end_id not in came_from:
        return None

    path = []
    node = end_id
    while node is not None:
        relation, note = edge_used.get(node, (None, ""))
        path.append((node, relation, note))
        node = came_from[node]
    path.reverse()
    return path
