"""
Seeds spatial_graph.json from the existing knowledge base: every venue gets
a node, grouped into "zone" nodes (floor + tower where known) so venues in
the same zone are connected. Deliberately does NOT invent connections
between towers or floors — those get added later via learn_location() once
someone actually confirms them, or looked up from an official source.

Run once: python seed_graph.py
"""
import json
import re
from pathlib import Path

import spatial_graph as sg

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

TOWER_RE = re.compile(r"(South Tower|North Tower)")
FLOOR_RE = re.compile(r"^([BL]\d+)")


def main():
    graph = sg._empty()

    for path in KNOWLEDGE_DIR.glob("*.json"):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry.get("canary"):
            continue  # keep test-only data out of the real spatial model

        floor_field = entry.get("floor", "")
        floor_match = FLOOR_RE.match(floor_field)
        tower_match = TOWER_RE.search(floor_field)
        floor = floor_match.group(1) if floor_match else None
        tower = tower_match.group(1) if tower_match else None

        sg.upsert_node(
            graph,
            entry["id"],
            type="venue",
            name_en=entry["name_en"],
            name_zh=entry["name_zh"],
            floor=floor,
            tower=tower,
        )

        # Deliberately no "floor" node shared across towers: two zones that
        # merely share a floor number are NOT necessarily walkable to each
        # other (that was the bug — a shared floor node let pathfinding
        # treat "same floor number" as "physically connected"). A zone is
        # the most specific grouping we're actually confident is one
        # walkable area (a given floor + tower, or a given floor if there's
        # no tower). Cross-zone connections only get added once someone
        # actually confirms them via learn_location.
        if floor:
            zone_key = f"{floor}_{tower.replace(' ', '_')}" if tower else floor
            zone_id = f"zone_{zone_key}"
            zone_label = f"{floor} {tower}" if tower else floor
            sg.upsert_node(graph, zone_id, type="zone", name_en=zone_label, name_zh=zone_label)
            sg.add_edge(graph, entry["id"], zone_id, "located_in")

    sg.save(graph)
    print(f"Seeded {len(graph['nodes'])} nodes, {len(graph['edges'])} edges -> {sg.GRAPH_PATH}")


if __name__ == "__main__":
    main()
