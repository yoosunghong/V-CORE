"""Export the PB ontology graph built from structured station/run data.

Example:
    python scripts/export_ontology_graph.py --out ../../../docs/benchmark/ontology_graph.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.ontology import OntologyGraphBuilder  # noqa: E402
from app.infrastructure.config import load_settings  # noqa: E402
from app.infrastructure.container import AppContainer  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the VCORE ontology graph projection.")
    parser.add_argument("--out", default="")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    container = AppContainer(load_settings())
    stations = await container.control_client.list_stations("ontology-export")
    runs = await container.repository.list_runs()
    graph = OntologyGraphBuilder().build(stations, runs)
    payload = {
        "nodes": [
            {
                "id": node.node_id,
                "kind": node.kind,
                "label": node.label,
                "properties": node.properties,
            }
            for node in graph.nodes.values()
        ],
        "edges": [
            {
                "source": edge.source_id,
                "relation": edge.relation,
                "target": edge.target_id,
                "properties": edge.properties,
            }
            for edge in graph.edges
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
