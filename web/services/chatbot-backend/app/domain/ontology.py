from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import RetrievedChunk, SimulationRun, Station


@dataclass(frozen=True)
class OntologyNode:
    node_id: str
    kind: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OntologyEdge:
    source_id: str
    relation: str
    target_id: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class OntologyGraph:
    nodes: dict[str, OntologyNode] = field(default_factory=dict)
    edges: list[OntologyEdge] = field(default_factory=list)
    outgoing: dict[str, list[OntologyEdge]] = field(default_factory=lambda: defaultdict(list))
    incoming: dict[str, list[OntologyEdge]] = field(default_factory=lambda: defaultdict(list))

    def add_node(self, node: OntologyNode) -> None:
        self.nodes[node.node_id] = node

    def add_edge(self, source_id: str, relation: str, target_id: str, **properties: Any) -> None:
        edge = OntologyEdge(source_id=source_id, relation=relation, target_id=target_id, properties=properties)
        self.edges.append(edge)
        self.outgoing[source_id].append(edge)
        self.incoming[target_id].append(edge)


STATION_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "loading": ("load", "pickup", "station_task"),
    "pickup": ("load", "pickup", "station_task"),
    "work": ("process", "work", "station_task"),
    "inspection": ("inspect", "inspection", "qa"),
    "unloading": ("unload", "dropoff", "station_task"),
    "dropoff": ("unload", "dropoff", "station_task"),
    "charger": ("charge", "battery"),
}

ZONE_ALIASES = {
    "1": "A",
    "zone1": "A",
    "zone 1": "A",
    "a": "A",
    "2": "B",
    "zone2": "B",
    "zone 2": "B",
    "b": "B",
    "3": "C",
    "zone3": "C",
    "zone 3": "C",
    "c": "C",
}


class OntologyGraphBuilder:
    """Build the PB ontology from station registry data plus saved run/KPI history."""

    def build(self, stations: list[Station], runs: list[SimulationRun]) -> OntologyGraph:
        graph = OntologyGraph()
        cell_id = stations[0].cell_id if stations else "cell_demo"
        cell_node_id = f"cell:{cell_id}"
        graph.add_node(OntologyNode(cell_node_id, "Cell", cell_id))

        for station in stations:
            zone_id = _normalize_zone(station.zone) or station.zone
            zone_node_id = f"zone:{zone_id}"
            if zone_node_id not in graph.nodes:
                graph.add_node(OntologyNode(zone_node_id, "Zone", f"Zone {zone_id}", {"zone": zone_id}))
                graph.add_edge(cell_node_id, "CONTAINS", zone_node_id)

            station_node_id = f"station:{station.station_id}"
            graph.add_node(
                OntologyNode(
                    station_node_id,
                    "Station",
                    f"Station {station.station_id}",
                    station.model_dump(mode="json"),
                )
            )
            graph.add_edge(zone_node_id, "CONTAINS", station_node_id)

            for capability in capabilities_for_station_type(station.station_type):
                capability_node_id = f"capability:{capability}"
                if capability_node_id not in graph.nodes:
                    graph.add_node(
                        OntologyNode(
                            capability_node_id,
                            "Capability",
                            capability,
                            {"capability": capability},
                        )
                    )
                graph.add_edge(station_node_id, "HAS_CAPABILITY", capability_node_id)

        for run in runs:
            run_node_id = f"run:{run.run_id}"
            graph.add_node(
                OntologyNode(
                    run_node_id,
                    "Run",
                    run.run_id,
                    {
                        "run_id": run.run_id,
                        "status": run.status.value,
                        "created_at": run.created_at.isoformat(),
                        "started_at": run.started_at.isoformat() if run.started_at else None,
                        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                    },
                )
            )
            graph.add_edge(cell_node_id, "HAS_RUN", run_node_id)
            kpis = run.kpis_json or {}
            for metric, value in kpis.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    kpi_node_id = f"kpi:{run.run_id}:{metric}"
                    graph.add_node(
                        OntologyNode(
                            kpi_node_id,
                            "Kpi",
                            metric,
                            {"metric": metric, "value": float(value), "run_id": run.run_id},
                        )
                    )
                    graph.add_edge(run_node_id, "MEASURED", kpi_node_id)
            for zone_id in zones_from_kpis(kpis):
                zone_node_id = f"zone:{zone_id}"
                if zone_node_id in graph.nodes:
                    graph.add_edge(run_node_id, "AFFECTS_ZONE", zone_node_id)
        return graph


class GraphRagRetriever:
    def __init__(self, builder: OntologyGraphBuilder | None = None) -> None:
        self._builder = builder or OntologyGraphBuilder()

    def is_relational_query(self, query: str) -> bool:
        normalized = query.casefold()
        relation_terms = (
            "which station",
            "which stations",
            "station in",
            "stations in",
            "capability",
            "can handle",
            "zone",
            "bottleneck rate",
            "last bottleneck",
            "multi-hop",
        )
        return any(term in normalized for term in relation_terms) and (
            "station" in normalized or "zone" in normalized or "capability" in normalized
        )

    def retrieve(
        self,
        query: str,
        stations: list[Station],
        runs: list[SimulationRun],
        *,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        if not self.is_relational_query(query):
            return []
        graph = self._builder.build(stations, runs)
        zone = parse_zone(query)
        capability = parse_capability(query)
        station_nodes = self._stations_for_query(graph, zone, capability)
        if not station_nodes:
            return []

        latest_bottleneck = latest_metric(runs, "bottleneck_rate")
        title_parts = ["Ontology"]
        if zone:
            title_parts.append(f"Zone {zone}")
        title_parts.append("stations")
        if capability:
            title_parts.append(f"for capability {capability}")
        title = ": " + " ".join(title_parts)
        title = title.removeprefix(": ")

        lines = [
            "Graph path: "
            + " -> ".join(
                part
                for part in (
                    f"Zone({zone})" if zone else "Cell(cell_demo)",
                    "CONTAINS",
                    "Station",
                    "HAS_CAPABILITY" if capability else "",
                    f"Capability({capability})" if capability else "",
                    "HAS_RUN",
                    "MEASURED",
                    "Kpi(bottleneck_rate)",
                )
                if part
            )
        ]
        for node in station_nodes:
            props = node.properties
            caps = ", ".join(capabilities_for_station_type(str(props.get("station_type", ""))))
            lines.append(
                "Station {station_id}: type={station_type}, zone={zone}, capabilities={caps}, "
                "task_ready={task_ready}, accessible={accessible}, state={state}.".format(
                    station_id=props.get("station_id"),
                    station_type=props.get("station_type"),
                    zone=_normalize_zone(str(props.get("zone", ""))) or props.get("zone"),
                    caps=caps,
                    task_ready=props.get("task_ready"),
                    accessible=props.get("accessible"),
                    state=props.get("state"),
                )
            )
        if latest_bottleneck is not None:
            run_id, value = latest_bottleneck
            lines.append(f"Latest bottleneck_rate: {value:g} from run {run_id}.")
        else:
            lines.append("Latest bottleneck_rate: not available in saved run history.")

        score = 1.0 if capability or zone else 0.85
        return [
            RetrievedChunk(
                document_id=self._document_id(zone, capability),
                title=title,
                text="\n".join(lines),
                score=score,
                source="ontology_graph",
                category="graph_ontology",
                rerank_score=score,
            )
        ][:top_k]

    def _stations_for_query(
        self,
        graph: OntologyGraph,
        zone: str | None,
        capability: str | None,
    ) -> list[OntologyNode]:
        candidates: list[OntologyNode] = [
            node for node in graph.nodes.values() if node.kind == "Station"
        ]
        if zone:
            candidates = [
                node
                for node in candidates
                if (_normalize_zone(str(node.properties.get("zone", ""))) or node.properties.get("zone")) == zone
            ]
        if capability:
            candidates = [
                node
                for node in candidates
                if capability in capabilities_for_station_type(str(node.properties.get("station_type", "")))
            ]
        return sorted(candidates, key=lambda node: int(node.properties.get("station_id", 0)))

    def _document_id(self, zone: str | None, capability: str | None) -> str:
        zone_part = (zone or "all").lower()
        capability_part = capability or "any"
        return f"ontology_station_{zone_part}_{capability_part}"


def capabilities_for_station_type(station_type: str) -> tuple[str, ...]:
    return STATION_CAPABILITIES.get(station_type.casefold(), ("station_task",))


def parse_zone(query: str) -> str | None:
    normalized = query.casefold()
    for alias, zone in sorted(ZONE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized):
            return zone
    return None


def parse_capability(query: str) -> str | None:
    normalized = query.casefold()
    capability_aliases = {
        "inspection": "inspect",
        "inspect": "inspect",
        "qa": "inspect",
        "loading": "load",
        "load": "load",
        "pickup": "pickup",
        "unloading": "unload",
        "unload": "unload",
        "dropoff": "dropoff",
        "work": "process",
        "process": "process",
        "station task": "station_task",
        "charge": "charge",
        "charger": "charge",
        "battery": "battery",
    }
    for alias, capability in sorted(capability_aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])", normalized):
            return capability
    return None


def latest_metric(runs: list[SimulationRun], metric: str) -> tuple[str, float] | None:
    for run in sorted(runs, key=lambda item: item.created_at, reverse=True):
        value = (run.kpis_json or {}).get(metric)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return run.run_id, float(value)
    return None


def zones_from_kpis(kpis: dict[str, Any]) -> set[str]:
    zones: set[str] = set()
    for key in ("zone_id", "zone", "bottleneck_zone"):
        value = kpis.get(key)
        if isinstance(value, str):
            zone = _normalize_zone(value)
            if zone:
                zones.add(zone)
    heatmap = kpis.get("zone_heatmap")
    if isinstance(heatmap, dict):
        for key in heatmap:
            zone = _normalize_zone(str(key))
            if zone:
                zones.add(zone)
    return zones


def _normalize_zone(value: str) -> str | None:
    normalized = value.casefold().strip().replace("-", " ")
    return ZONE_ALIASES.get(normalized)
