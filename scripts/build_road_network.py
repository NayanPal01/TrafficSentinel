"""
Builds data/road_network.json with realistic camera nodes, edges,
real distances in meters, and OSM road polylines for the Park Street corridor.
"""
import json
import math
import os
import requests

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def fetch_osrm_route(lat1, lon1, lat2, lon2):
    try:
        url = f"https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
        res = requests.get(url, timeout=6)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == "Ok" and data.get("routes"):
                route = data["routes"][0]
                coords = route["geometry"]["coordinates"]
                # Convert [lon, lat] -> [lat, lon]
                polyline = [[c[1], c[0]] for c in coords]
                dist_m = route.get("distance", haversine_m(lat1, lon1, lat2, lon2))
                return polyline, round(dist_m, 1)
    except Exception as e:
        print(f"OSRM fallback for ({lat1},{lon1}) -> ({lat2},{lon2}): {e}")

    # Fallback to straight line / 5 intermediate points
    steps = 5
    polyline = []
    for i in range(steps + 1):
        t = i / steps
        polyline.append([round(lat1 + (lat2 - lat1) * t, 6), round(lon1 + (lon2 - lon1) * t, 6)])
    dist_m = haversine_m(lat1, lon1, lat2, lon2)
    return polyline, round(dist_m, 1)

def main():
    nodes = [
        {
            "camera_id": "CAM-01",
            "name": "JLN Road & Park St Entrance",
            "kind": "junction",
            "latitude": 22.5532,
            "longitude": 88.3510,
            "is_fork": False
        },
        {
            "camera_id": "CAM-06",
            "name": "Park St & Russell St",
            "kind": "junction",
            "latitude": 22.5526,
            "longitude": 88.3529,
            "is_fork": False
        },
        {
            "camera_id": "CAM-11",
            "name": "Park St Midway (West)",
            "kind": "midway",
            "latitude": 22.5530,
            "longitude": 88.3545,
            "is_fork": False
        },
        {
            "camera_id": "CAM-03",
            "name": "Park St & Camac St Crossing (Fork J1)",
            "kind": "junction",
            "latitude": 22.5525,
            "longitude": 88.3561,
            "is_fork": True  # Forks East into Park St or South into Camac St
        },
        {
            "camera_id": "CAM-09",
            "name": "Park St Midway (East)",
            "kind": "midway",
            "latitude": 22.5512,
            "longitude": 88.3586,
            "is_fork": False
        },
        {
            "camera_id": "CAM-10",
            "name": "Park St & AJC Bose Rd / Mullick Bazar",
            "kind": "junction",
            "latitude": 22.5505,
            "longitude": 88.3627,
            "is_fork": False
        },
        {
            "camera_id": "CAM-08",
            "name": "Camac St Midway",
            "kind": "midway",
            "latitude": 22.5514,
            "longitude": 88.3556,
            "is_fork": False
        },
        {
            "camera_id": "CAM-07",
            "name": "Shakespeare Sarani & Camac St (Fork J2)",
            "kind": "junction",
            "latitude": 22.5502,
            "longitude": 88.3550,
            "is_fork": True  # Forks West or East on Shakespeare Sarani
        },
        {
            "camera_id": "CAM-04",
            "name": "Shakespeare Sarani & JLN Road",
            "kind": "junction",
            "latitude": 22.5500,
            "longitude": 88.3515,
            "is_fork": False
        },
        {
            "camera_id": "CAM-05",
            "name": "Shakespeare Sarani East (Hungerford St)",
            "kind": "junction",
            "latitude": 22.5495,
            "longitude": 88.3600,
            "is_fork": False
        }
    ]

    node_dict = {n["camera_id"]: n for n in nodes}

    edge_definitions = [
        ("CAM-01", "CAM-06", "Park Street Entrance Corridor", 40.0),
        ("CAM-06", "CAM-11", "Park Street West Corridor", 40.0),
        ("CAM-11", "CAM-03", "Park Street Approach to Camac St", 40.0),
        # Fork at CAM-03: Branch A continues East on Park St; Branch B turns South on Camac St
        ("CAM-03", "CAM-09", "Park Street East Branch (towards Mullick Bazar)", 40.0),
        ("CAM-09", "CAM-10", "Park Street to AJC Bose Rd Junction", 45.0),
        ("CAM-03", "CAM-08", "Camac Street South Branch", 35.0),
        ("CAM-08", "CAM-07", "Camac Street to Shakespeare Sarani", 35.0),
        # Fork at CAM-07: Branch B1 West; Branch B2 East
        ("CAM-07", "CAM-04", "Shakespeare Sarani West Branch (towards Maidan)", 40.0),
        ("CAM-07", "CAM-05", "Shakespeare Sarani East Branch", 40.0),
    ]

    edges = []
    print(f"Building network with {len(nodes)} nodes and {len(edge_definitions)} edges...")

    for u, v, road_name, speed_limit in edge_definitions:
        n_u = node_dict[u]
        n_v = node_dict[v]
        polyline, dist_m = fetch_osrm_route(n_u["latitude"], n_u["longitude"], n_v["latitude"], n_v["longitude"])
        edges.append({
            "edge_id": f"{u}->{v}",
            "from_node": u,
            "to_node": v,
            "name": road_name,
            "distance_m": dist_m,
            "speed_limit_kmh": speed_limit,
            "polyline": polyline
        })
        print(f"  Edge {u} -> {v} ({road_name}): {dist_m}m, {len(polyline)} points")

    data = {
        "metadata": {
            "city": "Kolkata",
            "zone": "Park Street & Shakespeare Sarani Corridor",
            "version": "1.0",
            "node_count": len(nodes),
            "edge_count": len(edges)
        },
        "nodes": nodes,
        "edges": edges
    }

    os.makedirs("data", exist_ok=True)
    out_path = os.path.join("data", "road_network.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"\nSaved road network graph to {out_path} ({os.path.getsize(out_path)} bytes)")

if __name__ == "__main__":
    main()
