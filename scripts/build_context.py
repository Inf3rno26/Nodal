"""Builds datasets/processed/{wards,bus,metro_fares}.json from public sources (downloads if missing).
Sources and caveats are recorded in datasets/metadata/README.md."""
import ast, csv, json, math, pathlib, statistics, subprocess, sys
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "datasets/raw", ROOT / "datasets/processed"
OUT.mkdir(parents=True, exist_ok=True)


def fetch(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.stat().st_size < 1000:
        subprocess.run(["curl", "-sL", "-m", "300", "-o", str(dest), url], check=True)
    return dest


# ---- census wards (2011) ----
B = "https://raw.githubusercontent.com/suvajit/opendata/master/BBMP/data"
gj = json.load(open(fetch(B + "/JSON/BBMPwards.geojson", RAW / "census/wards.geojson")))
meta = pd.read_csv(fetch(B + "/CSV/BBMPwards.csv", RAW / "census/wards_meta.csv")).set_index("WARD_NO")
feats, tot = [], 0
def rnd(c):
    return [round(c[0], 4), round(c[1], 4)] if isinstance(c[0], (int, float)) else [rnd(x) for x in c]
for f in gj["features"]:
    p = f["properties"]; no = int(p["WARD_NO"]); m = meta.loc[no]
    area = float(m["AREA_SQ_KM"]); pop = int(m["POP_TOTAL"]); wk = int(m["POP_WORK"]); tot += pop
    feats.append({"type": "Feature", "geometry": {"type": f["geometry"]["type"], "coordinates": rnd(f["geometry"]["coordinates"])},
                  "properties": {"no": no, "name": str(m["WARD_NAME"]), "ac": str(m["ASS_CONST1"]), "pop": pop, "workers": wk, "households": int(m["TOT_HH"]),
                                 "area_km2": area, "density": round(pop / area, 1), "worker_density": round(wk / area, 1)}})
json.dump({"type": "FeatureCollection", "features": feats, "meta": {"year": 2011, "total_pop": tot, "wards": len(feats),
          "source": "Census of India 2011 merged with BBMP 198-ward boundaries by suvajit/opendata (CC BY-SA 3.0)",
          "workers_note": "POP_WORK = workers by place of residence, NOT jobs located in the ward"}}, open(OUT / "wards.json", "w"), separators=(",", ":"))
print("wards", len(feats), "total population", tot)

# ---- BMTC bus network ----
BM = "https://raw.githubusercontent.com/Vonter/bmtc-gtfs/main"
agg = json.load(open(fetch(BM + "/geojson/aggregated.geojson", RAW / "bmtc/aggregated.geojson")))
stops, idx = [], {}
for f in agg["features"]:
    n = f["properties"]["name"]; g = f["geometry"]
    if g["type"] != "Point" or n in idx:
        continue
    lon, lat = g["coordinates"][:2]
    if not (12.6 < lat < 13.5 and 77.3 < lon < 78.0):
        continue
    idx[n] = len(stops); stops.append([n, round(lat, 5), round(lon, 5), int(f["properties"].get("trip_count", 0))])
rt = pd.read_csv(fetch(BM + "/csv/routes.csv", RAW / "bmtc/routes.csv"))
routes, seen = [], set()
def mins(t):
    h, m, s = map(int, t.split(":")); return h * 60 + m + s / 60
for r in rt.itertuples():
    try:
        sl = ast.literal_eval(r.stop_list); tl = ast.literal_eval(r.trip_list)
    except Exception:
        continue
    seq = [idx[s] for s in sl if s in idx]
    seq = [a for i, a in enumerate(seq) if i == 0 or a != seq[i - 1]]
    if len(seq) < 2:
        continue
    key = (str(r.name), tuple(seq))
    if key in seen:
        continue
    seen.add(key)
    ts = sorted(mins(t) for t in tl)
    n = len(ts); span = (ts[-1] - ts[0]) if n > 1 else 0
    headway = max(3.0, span / (n - 1)) if n > 1 else 120.0
    routes.append([str(r.name), round(headway, 1), n, seq])
json.dump({"stops": stops, "routes": routes, "meta": {"source": "Unofficial BMTC GTFS (Vonter/bmtc-gtfs), from the Namma BMTC 2.0 app",
          "caveat": "Source app has known timetable inaccuracies; stops are merged by name; coordinates are as published"}}, open(OUT / "bus.json", "w"), separators=(",", ":"))
print("bus stops", len(stops), "route patterns", len(routes))

# ---- metro fares (from the BMRCL GTFS fare tables) ----
G = RAW / "gtfs"
prod = pd.read_csv(G / "fare_products.txt").set_index("fare_product_id")["amount"].to_dict()
fl = pd.read_csv(G / "fare_leg_rules.txt", dtype=str)
fl = fl[fl.fare_product_id.str.contains("token") & (fl.from_timeframe_group_id == "peak")]
fares = {f"{r.from_area_id}|{r.to_area_id}": float(prod[r.fare_product_id]) for r in fl.itertuples()}
json.dump({"fares": fares, "meta": {"basis": "token fare, peak timeframe, from the BMRCL GTFS fare tables"}}, open(OUT / "metro_fares.json", "w"), separators=(",", ":"))
print("metro fare pairs", len(fares), "sample", list(fares.items())[:2])
