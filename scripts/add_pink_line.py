"""
Script to add Namma Metro Pink Line (Kalena Agrahara to Nagawara) to datasets/processed/network.json
Line length: ~21.3 km, 18 stations (Kalena Agrahara to Nagawara).
Interchanges:
  - Jayadeva Hospital (JDHP): connects Pink Line <-> Yellow Line
  - Mahatma Gandhi Road (MAGR): connects Pink Line <-> Purple Line
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NETWORK_PATH = ROOT / "datasets" / "processed" / "network.json"

def hav(lat1, lon1, lat2, lon2):
    R = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

# 18 Stations of Pink Line (South to North)
PINK_STATIONS = [
    {"id": "KLAG", "name": "Kalena Agrahara", "lat": 12.8718, "lon": 77.5937, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "HLMN", "name": "Hulimavu", "lat": 12.8804, "lon": 77.5954, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "IIMB", "name": "IIMB (Bannerghatta)", "lat": 12.8942, "lon": 77.5976, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "JPN4", "name": "JP Nagar 4th Phase", "lat": 12.9069, "lon": 77.5989, "lines": ["Pink"], "wheelchair": "1"},
    # Interchanges at Jayadeva Hospital (already existing in network as JDHP)
    {"id": "JDHP", "name": "Jayadeva Hospital", "lat": 12.916731, "lon": 77.59997, "lines": ["Yellow", "Pink"], "wheelchair": "1"},
    {"id": "TWCL", "name": "Tavarekere", "lat": 12.9255, "lon": 77.6042, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "DRCS", "name": "Dairy Circle", "lat": 12.9362, "lon": 77.6033, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "LAKC", "name": "Lakkasandra", "lat": 12.9440, "lon": 77.6026, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "LNFR", "name": "Langford Town", "lat": 12.9556, "lon": 77.6048, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "RSKP", "name": "Rashtriya Military School", "lat": 12.9648, "lon": 77.6063, "lines": ["Pink"], "wheelchair": "1"},
    # Interchanges at MG Road (already existing in network as MAGR)
    {"id": "MAGR", "name": "Mahatma Gandhi Road", "lat": 12.975526, "lon": 77.60679, "lines": ["Purple", "Pink"], "wheelchair": "1"},
    {"id": "SHVN", "name": "Shivajinagar", "lat": 12.9854, "lon": 77.6046, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "BCTN", "name": "Bengaluru Cantonment", "lat": 12.9937, "lon": 77.5991, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "PTTR", "name": "Pottery Town", "lat": 13.0016, "lon": 77.6068, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "TNRD", "name": "Tannery Road", "lat": 13.0094, "lon": 77.6143, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "VKNG", "name": "Venkateshapura", "lat": 13.0182, "lon": 77.6186, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "KDNB", "name": "Kadugondanahalli", "lat": 13.0298, "lon": 77.6208, "lines": ["Pink"], "wheelchair": "1"},
    {"id": "NGWR", "name": "Nagawara", "lat": 13.0428, "lon": 77.6234, "lines": ["Pink"], "wheelchair": "1"}
]

data = json.load(open(NETWORK_PATH, encoding="utf-8"))

# Set Pink Line color
data["line_colors"]["Pink"] = "#EC008C"

# Map existing stations by ID
st_by_id = {s["id"]: s for s in data["stations"]}

# Update stations: update JDHP and MAGR to include Pink line, and add new ones
for st in PINK_STATIONS:
    if st["id"] in st_by_id:
        existing = st_by_id[st["id"]]
        if "Pink" not in existing["lines"]:
            existing["lines"].append("Pink")
    else:
        data["stations"].append(st)
        st_by_id[st["id"]] = st

# Build edges between consecutive Pink Line stations
new_edges = []
avg_speed_kmh = 32.0  # standard metro commercial speed

for i in range(len(PINK_STATIONS) - 1):
    u_st = st_by_id[PINK_STATIONS[i]["id"]]
    v_st = st_by_id[PINK_STATIONS[i+1]["id"]]
    d_km = hav(u_st["lat"], u_st["lon"], v_st["lat"], v_st["lon"])
    track_km = round(d_km * 1.08, 4)  # account for slight track curvature
    travel_min = round((track_km / avg_speed_kmh) * 60.0 + 0.5, 3) # including dwell
    
    geom = [
        [round(u_st["lon"], 6), round(u_st["lat"], 6)],
        [round(v_st["lon"], 6), round(v_st["lat"], 6)]
    ]
    
    edge = {
        "u": u_st["id"],
        "v": v_st["id"],
        "line": "Pink",
        "km": track_km,
        "km_polyline": track_km,
        "km_straight": round(d_km, 4),
        "min": travel_min,
        "geometry": geom
    }
    new_edges.append(edge)

# Remove any previous pink edges if script is run multiple times
data["edges"] = [e for e in data["edges"] if e.get("line") != "Pink"] + new_edges

json.dump(data, open(NETWORK_PATH, "w", encoding="utf-8"), indent=2)
print(f"Successfully integrated Pink Line: {len(PINK_STATIONS)} stations, {len(new_edges)} edges.")
print(f"Total stations in network: {len(data['stations'])}, total edges: {len(data['edges'])}")
