"""
Road Network Graph Module for Multi-Camera ANPR Vehicle Tracking.
Represents intersections and cameras as graph nodes, and road segments with
real-world distances (meters) and OSM polylines as directed edges.
"""

from __future__ import annotations
import json
import logging
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

import networkx as nx

logger = logging.getLogger("trafficsentinel.road_network")


@dataclass
class CameraNode:
    camera_id: str
    name: str
    kind: str  # 'junction' | 'midway'
    latitude: float
    longitude: float
    is_fork: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "name": self.name,
            "kind": self.kind,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "is_fork": self.is_fork
        }


@dataclass
class RoadEdge:
    edge_id: str
    from_node: str
    to_node: str
    name: str
    distance_m: float
    speed_limit_kmh: float
    polyline: List[List[float]]  # list of [lat, lon]
    # Pre-calculated cumulative segment distances along polyline
    cum_distances: List[float] = field(default_factory=list)

    def __post_init__(self):
        if not self.cum_distances and len(self.polyline) > 1:
            self.cum_distances = self._compute_cumulative_distances()

    def _compute_cumulative_distances(self) -> List[float]:
        cum = [0.0]
        total = 0.0
        for i in range(1, len(self.polyline)):
            p1 = self.polyline[i - 1]
            p2 = self.polyline[i]
            d = RoadNetwork.haversine_distance(p1[0], p1[1], p2[0], p2[1])
            total += d
            cum.append(total)
        # If total differs from distance_m, scale to match specified distance
        if total > 0 and abs(total - self.distance_m) > 1.0:
            scale = self.distance_m / total
            cum = [c * scale for c in cum]
        return cum

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "name": self.name,
            "distance_m": self.distance_m,
            "speed_limit_kmh": self.speed_limit_kmh,
            "polyline": self.polyline
        }


class RoadNetwork:
    """Directed graph of camera nodes and connecting road polylines."""

    def __init__(self, json_path: Optional[str] = None):
        self.graph = nx.DiGraph()
        self.nodes: Dict[str, CameraNode] = {}
        self.edges: Dict[Tuple[str, str], RoadEdge] = {}
        self.edges_by_id: Dict[str, RoadEdge] = {}

        if json_path and os.path.exists(json_path):
            self.load_from_json(json_path)
        else:
            default_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "road_network.json")
            if os.path.exists(default_path):
                self.load_from_json(default_path)

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculates surface distance in meters between two lat/lon pairs."""
        R = 6371000.0  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0)**2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return R * c

    def load_from_json(self, filepath: str) -> None:
        """Loads nodes and edges from a road network JSON definition."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.nodes.clear()
        self.edges.clear()
        self.edges_by_id.clear()
        self.graph.clear()

        for nd in data.get("nodes", []):
            node = CameraNode(
                camera_id=nd["camera_id"],
                name=nd.get("name", nd["camera_id"]),
                kind=nd.get("kind", "junction"),
                latitude=float(nd["latitude"]),
                longitude=float(nd["longitude"]),
                is_fork=nd.get("is_fork", False)
            )
            self.nodes[node.camera_id] = node
            self.graph.add_node(node.camera_id, **node.to_dict())

        for ed in data.get("edges", []):
            edge = RoadEdge(
                edge_id=ed.get("edge_id", f"{ed['from_node']}->{ed['to_node']}"),
                from_node=ed["from_node"],
                to_node=ed["to_node"],
                name=ed.get("name", "Corridor"),
                distance_m=float(ed["distance_m"]),
                speed_limit_kmh=float(ed.get("speed_limit_kmh", 40.0)),
                polyline=ed["polyline"]
            )
            self.edges[(edge.from_node, edge.to_node)] = edge
            self.edges_by_id[edge.edge_id] = edge
            self.graph.add_edge(
                edge.from_node,
                edge.to_node,
                edge_id=edge.edge_id,
                weight=edge.distance_m,
                edge_data=edge
            )

        # Update node.is_fork dynamically if outgoing edges > 1
        for node_id, node in self.nodes.items():
            outgoing = list(self.graph.successors(node_id))
            if len(outgoing) > 1:
                node.is_fork = True
                self.graph.nodes[node_id]["is_fork"] = True

        logger.info(f"Loaded road network: {len(self.nodes)} nodes, {len(self.edges)} edges.")

    def get_node(self, camera_id: str) -> Optional[CameraNode]:
        return self.nodes.get(camera_id)

    def get_edge(self, from_node: str, to_node: str) -> Optional[RoadEdge]:
        return self.edges.get((from_node, to_node))

    def get_outgoing_edges(self, camera_id: str) -> List[RoadEdge]:
        """Returns all road edges leaving this camera node."""
        if camera_id not in self.graph:
            return []
        edges = []
        for succ in self.graph.successors(camera_id):
            edge = self.edges.get((camera_id, succ))
            if edge:
                edges.append(edge)
        return edges

    def is_fork(self, camera_id: str) -> bool:
        """Returns True if this camera node has 2 or more outgoing paths."""
        return len(self.get_outgoing_edges(camera_id)) > 1

    def get_nearest_node(self, lat: float, lon: float, max_dist_m: float = 1000.0) -> Optional[str]:
        """Finds closest node within threshold distance."""
        best_id = None
        best_dist = float("inf")
        for node_id, node in self.nodes.items():
            d = self.haversine_distance(lat, lon, node.latitude, node.longitude)
            if d < best_dist and d <= max_dist_m:
                best_dist = d
                best_id = node_id
        return best_id

    def to_dict(self) -> Dict[str, Any]:
        """Serializes network for REST API / Frontend Map consumption."""
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges.values()]
        }
