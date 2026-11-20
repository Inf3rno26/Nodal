import json, math, csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NETWORK_PATH = ROOT / "datasets" / "processed" / "network.json"
PROPOSED_PATH = ROOT / "datasets" / "raw" / "proposed.geojson"   # optional, verified data only
GTFS_PATH = ROOT / "datasets" / "raw" / "gtfs"
TRANSFER_MIN = 5.0        # ASSUMPTION (GTFS only gives a 60 s lower bound)
TRANSFER_PENALTY = 8.0    # ASSUMPTION (generalized cost)
TRANSFER_BIG = 10000.0    # lexicographic weight for the min-transfers objective

# Realistic interchange parameters
HEADWAY_MIN = 6.0         # typical peak headway (minutes) → expected wait = headway/2
WALK_SPEED_MPS = 1.2      # m/s walking speed for distance estimates


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_raw(path=NETWORK_PATH):
    return json.load(open(path, encoding="utf-8"))


def load_network(path=NETWORK_PATH):
    """stations dict id -> {...}, edges list. Edges only join consecutive stations on a line (never by proximity).
    km = distance along the alignment (GTFS shape_dist_traveled); km_straight = haversine; min = feed timetable
    arrival-to-arrival time (modeled by the feed author)."""
    raw = load_raw(path)
    stations = {s["id"]: s for s in raw["stations"]}
    edges = [{**e, "min": e["min"]} for e in raw["edges"]]
    return stations, edges, raw["line_colors"], raw["source"]


def load_interchange_costs(gtfs_root=None):
    """Parse real GTFS pathways.txt and transfers.txt to build per-station realistic transfer costs.

    Returns dict: station_id -> {
        'walking_min': float,        # platform-to-platform walk time from GTFS pathways (seconds->minutes)
        'min_transfer_min': float,   # GTFS minimum transfer time from transfers.txt (seconds->minutes)
        'wait_min': float,           # expected waiting time = headway / 2
        'total_transfer_min': float, # Dijkstra edge weight used for transfers
        'has_gtfs_data': bool        # True if real GTFS data was found, False = fallback
    }
    """
    root = Path(gtfs_root) if gtfs_root else GTFS_PATH
    pathways_file = root / "pathways.txt"
    transfers_file = root / "transfers.txt"

    wait_min = HEADWAY_MIN / 2.0  # 3.0 min expected wait at peak

    # --- Parse pathways.txt: traversal_time in seconds for escalator/elevator/walkway ---
    # pathway_mode=6 means generic walkway; group by parent station prefix (e.g. KGWA from KGWA_A)
    station_pathway_max_sec = {}  # station_id -> max traversal time seen
    if pathways_file.exists():
        with open(pathways_file, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    t_sec = float(row.get("traversal_time", 0) or 0)
                except (ValueError, TypeError):
                    continue
                # Extract parent station from stop_id like "KGWA_A" or "KGWA_PF1"
                from_id = row.get("from_stop_id", "")
                to_id = row.get("to_stop_id", "")
                for stop_id in (from_id, to_id):
                    # Parent station = part before first underscore
                    parent = stop_id.split("_")[0] if "_" in stop_id else stop_id
                    if parent:
                        cur = station_pathway_max_sec.get(parent, 0)
                        if t_sec > cur:
                            station_pathway_max_sec[parent] = t_sec

    # --- Parse transfers.txt: min_transfer_time in seconds ---
    # from_stop_id like "KGWA_PF1" -> parent = "KGWA"
    station_min_transfer_sec = {}  # station_id -> min transfer time (seconds)
    if transfers_file.exists():
        with open(transfers_file, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    t_sec = float(row.get("min_transfer_time", 0) or 0)
                except (ValueError, TypeError):
                    continue
                from_id = row.get("from_stop_id", "")
                parent = from_id.split("_")[0] if "_" in from_id else from_id
                if parent:
                    cur = station_min_transfer_sec.get(parent, 0)
                    if t_sec > cur:
                        station_min_transfer_sec[parent] = t_sec

    # Build result dict for all stations that appear in GTFS interchange data
    all_station_ids = set(station_pathway_max_sec) | set(station_min_transfer_sec)

    costs = {}
    for sid in all_station_ids:
        walk_sec = station_pathway_max_sec.get(sid, 0)
        min_xfer_sec = station_min_transfer_sec.get(sid, 0)

        walking_min = walk_sec / 60.0
        min_transfer_min = min_xfer_sec / 60.0

        # Total = max(walking, GTFS min transfer) + expected wait
        in_vehicle_transfer = max(walking_min, min_transfer_min)
        total = in_vehicle_transfer + wait_min

        # Clamp to at least TRANSFER_MIN for realism
        total = max(total, TRANSFER_MIN)

        costs[sid] = {
            "walking_min": round(walking_min, 2),
            "min_transfer_min": round(min_transfer_min, 2),
            "wait_min": round(wait_min, 2),
            "total_transfer_min": round(total, 2),
            "has_gtfs_data": True,
        }

    return costs


def load_proposed():
    if PROPOSED_PATH.exists():
        return {"available": True, "geojson": json.load(open(PROPOSED_PATH, encoding="utf-8"))}
    return {"available": False, "geojson": {"type": "FeatureCollection", "features": []},
            "note": "No verified proposed/under-construction data is bundled. Add a GeoJSON to datasets/raw/proposed.geojson "
                    "(from BMRCL or OpenStreetMap) and it will be drawn as a distinct layer."}
