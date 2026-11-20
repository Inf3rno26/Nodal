"""Builds datasets/processed/network.json from the unofficial BMRCL GTFS feed (Vonter/bmrcl-gtfs, derived from
OpenStreetMap + BMRCL timetables). Run:  python scripts/build_from_gtfs.py
Real from the feed: station names/coordinates (parent stations), line membership, station order, track shapes,
distance along the alignment (stop_times.shape_dist_traveled, km). MODELED in the feed: timetable times.
"""
import json, math, pathlib
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
G = ROOT / "datasets/raw/gtfs"
OUT = ROOT / "datasets/processed/network.json"


def hav(a, b):
    R = 6371.0088
    p1, p2 = math.radians(a[0]), math.radians(b[0]); dl = math.radians(b[1] - a[1])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def hms(s):
    h, m, x = map(int, s.split(":")); return h * 60 + m + x / 60


stops = pd.read_csv(G / "stops.txt", dtype=str)
routes = pd.read_csv(G / "routes.txt", dtype=str)
trips = pd.read_csv(G / "trips.txt", dtype=str)
st = pd.read_csv(G / "stop_times.txt", dtype={"trip_id": str, "stop_id": str})
shapes = pd.read_csv(G / "shapes.txt", dtype={"shape_id": str}).sort_values(["shape_id", "shape_pt_sequence"])
parents = stops[stops.location_type == "1"].set_index("stop_id")
plat = stops[stops.location_type != "1"].set_index("stop_id")
plat_parent = plat["parent_station"].to_dict()
st["parent"] = st.stop_id.map(plat_parent)
colors = {r.route_id.title(): "#" + r.route_color for r in routes.itertuples()}
cnt = st.groupby("trip_id").size()
st["arr"] = st.arrival_time.map(hms); st["dep"] = st.departure_time.map(hms)

stations = {sid: {"id": sid, "name": r.stop_name, "lat": float(r.stop_lat), "lon": float(r.stop_lon), "lines": [],
                  "wheelchair": r.wheelchair_boarding} for sid, r in parents.iterrows()}
edges = []
for rid in routes.route_id:
    t = trips[(trips.route_id == rid) & (trips.direction_id == "0")].copy()
    t["n"] = t.trip_id.map(cnt)
    rep = t.sort_values("n", ascending=False).iloc[0]            # representative full-length trip
    seq = st[st.trip_id == rep.trip_id].sort_values("stop_sequence")
    sh = shapes[shapes.shape_id == rep.shape_id]
    pts = list(zip(sh.shape_pt_lat, sh.shape_pt_lon))
    order = list(seq.parent)
    for p in order:
        if rid.title() not in stations[p]["lines"]:
            stations[p]["lines"].append(rid.title())
    # median arrival->arrival time per consecutive pair over all same-direction trips of this route
    same = st[st.trip_id.isin(t.trip_id)].sort_values(["trip_id", "stop_sequence"]).copy()
    same["next_parent"] = same.groupby("trip_id").parent.shift(-1); same["next_arr"] = same.groupby("trip_id").arr.shift(-1)
    same["dt"] = same.next_arr - same.arr
    med = same.dropna(subset=["next_parent"]).groupby(["parent", "next_parent"]).dt.median().to_dict()
    last = 0
    rows = list(seq.itertuples())
    idx = []
    for r in rows:                                            # monotone nearest shape vertex for each platform
        c = (float(plat.loc[r.stop_id, "stop_lat"]), float(plat.loc[r.stop_id, "stop_lon"]))
        j = min(range(last, len(pts)), key=lambda k: hav(pts[k], c)); idx.append(j); last = j
    for a, b, ia, ib in zip(rows, rows[1:], idx, idx[1:]):
        geom = [[pts[k][1], pts[k][0]] for k in range(ia, ib + 1)]
        ua, ub = stations[a.parent], stations[b.parent]
        if len(geom) < 2:
            geom = [[ua["lon"], ua["lat"]], [ub["lon"], ub["lat"]]]
        track = float(b.shape_dist_traveled) - float(a.shape_dist_traveled)
        poly = sum(hav((geom[i][1], geom[i][0]), (geom[i + 1][1], geom[i + 1][0])) for i in range(len(geom) - 1))
        edges.append({"u": a.parent, "v": b.parent, "line": rid.title(), "km": round(track, 4),
                      "km_polyline": round(poly, 4),
                      "km_straight": round(hav((ua["lat"], ua["lon"]), (ub["lat"], ub["lon"])), 4),
                      "min": round(float(med[(a.parent, b.parent)]), 3), "geometry": geom})
net = {"source": {"name": "Unofficial BMRCL GTFS (Vonter/bmrcl-gtfs)", "url": "https://github.com/Vonter/bmrcl-gtfs",
                  "feed_valid": "2026-08-17 to 2027-08-17", "operator": "BMRCL",
                  "basis": "OpenStreetMap spatial data + BMRCL published timetables; times are modeled by the feed author",
                  "license_note": "OpenStreetMap data is ODbL; see repository for details"},
       "line_colors": colors, "stations": list(stations.values()), "edges": edges}
OUT.parent.mkdir(parents=True, exist_ok=True)
json.dump(net, open(OUT, "w"), separators=(",", ":"))
print("stations", len(stations), "edges", len(edges))
for ln in colors:
    L = [e for e in edges if e["line"] == ln.title()]
    print(ln.title(), "edges", len(L), "track km", round(sum(e["km"] for e in L), 2),
          "polyline km", round(sum(e["km_polyline"] for e in L), 2), "straight km", round(sum(e["km_straight"] for e in L), 2),
          "ride min", round(sum(e["min"] for e in L), 1))
print("interchanges", [s["name"] for s in stations.values() if len(s["lines"]) > 1])
print("max track-vs-polyline gap km", round(max(abs(e["km"] - e["km_polyline"]) for e in edges), 3))
