import copy, sys
from pathlib import Path
import networkx as nx, numpy as np, pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import algorithms as A
from app.main import app, PLAN
from app.services import NET, NodalError
from app.planning import PRESETS, ASSUME
from fastapi.testclient import TestClient

client = TestClient(app)
POOL = PLAN.pool()


def strip(c):
    return {k: c[k] for k in ("id", "name", "kind", "target", "stations", "seg_geoms")}


def test_closeness_matches_networkx():
    G = nx.Graph()
    for u, nb in NET.adj_km.items():
        for v, w in nb.items():
            G.add_edge(u, v, weight=w)
    ref = nx.closeness_centrality(G, distance="weight")
    mine = A.closeness(NET.adj_km)
    assert all(mine[v] == pytest.approx(ref[v], rel=1e-9) for v in ref)


def test_accessibility_matches_bruteforce():
    acc = PLAN.accessibility()
    from app.data import haversine
    for c in acc["cells"][::97]:
        d = min(haversine(c["lat"], c["lon"], s["lat"], s["lon"]) for s in NET.stations.values())
        assert abs(d - c["d"]) <= 0.01 * d + 0.02   # equirectangular approximation vs haversine (<1%)
        assert c["cls"] == (0 if c["d"] <= 1 else 1 if c["d"] <= 2.5 else 2) or abs(c["d"] - 1) < .05 or abs(c["d"] - 2.5) < .05
    s = acc["summary_km2"]; assert s["excellent"] + s["moderate"] + s["poor"] == len(acc["cells"])
    assert any(a["status"] == "poor" for a in acc["anchors"])


def test_original_graph_never_modified():
    snap_km, snap_min = copy.deepcopy(NET.adj_km), copy.deepcopy(NET.adj_min)
    PLAN.evaluate([strip(POOL[0])]); PLAN.evaluate([strip(POOL[1]), strip(POOL[-1])]); PLAN.generate_scenarios()
    assert NET.adj_km == snap_km and NET.adj_min == snap_min and len(NET.edges) == 82


def test_corridor_adds_exact_geometry_and_stations():
    c = POOL[0]; ev = PLAN.evaluate([strip(c)])
    n_new = sum(s["new"] for s in c["stations"])
    assert ev["after"]["stations"] == 83 + n_new and ev["new_stations"] == n_new
    assert ev["after"]["edges"] == 82 + len(c["stations"]) - 1
    assert ev["after"]["track_km"] - ev["before"]["track_km"] == pytest.approx(ev["length_km"])
    assert ev["length_km"] == pytest.approx(sum(sum(A_ for A_ in [0]) + PLAN._cum(g)[-1] for g in c["seg_geoms"]))
    assert ev["cost_cr"] == pytest.approx(ev["length_km"] * 300)


def test_extension_keeps_tree_loop_creates_cycle():
    ext = next(p for p in POOL if p["kind"] == "extension"); loop = next(p for p in POOL if p["kind"] == "loop")
    e1, e2 = PLAN.evaluate([strip(ext)]), PLAN.evaluate([strip(loop)])
    assert e1["after"]["is_tree"] and e1["after"]["components"] == 1
    assert not e2["after"]["is_tree"] and e2["after"]["components"] == 1                    # cycle -> redundancy
    assert e2["after"]["articulation_points"] < e2["after"]["stations"] - 2                  # fewer cut vertices than a tree


def test_travel_time_never_increases_and_edge_times():
    for p in POOL[:25]:
        ev = PLAN.evaluate([strip(p)], full=True)
        assert ev["after"]["mean_pair_min"] <= ev["before"]["mean_pair_min"] + 1e-9
        assert all(a["after_min"] <= a["before_min"] + 1e-9 for a in ev["anchor_times"])
        assert ev["cells_improved"] >= 0 and all(a["after_km"] < a["before_km"] for a in ev["anchors_benefiting"])


def test_new_edge_time_uses_network_average_speed():
    p = POOL[0]; g = PLAN.apply([PLAN._norm_corridor(strip(p))])
    new = [(u, v) for u in g["adj_km"] for v in g["adj_km"][u] if u.startswith("NEW") and v.startswith("NEW")]
    u, v = new[0]
    assert g["adj_min"][u][v] == pytest.approx(g["adj_km"][u][v] / PLAN.avg_kmh * 60)


def test_ranking_follows_weights():
    cheapest = min(POOL, key=lambda p: p["cost_cr"])
    assert PLAN.rank(POOL, {"cost": 1})[0]["id"] == cheapest["id"]
    best_cov = max(POOL, key=lambda p: p["raw"]["coverage"])
    top = PLAN.rank(POOL, {"coverage": 1})[0]
    assert top["raw"]["coverage"] == best_cov["raw"]["coverage"]
    r = PLAN.rank(POOL, PRESETS["C"]["weights"])
    assert all(0 <= x["score"] <= 1 + 1e-9 for x in r) and r == sorted(r, key=lambda x: -x["score"])
    assert sum(r[0]["contrib"].values()) == pytest.approx(r[0]["score"])
    assert PLAN.rank(POOL, {"cost": 1}, budget_cr=-1) == []


def test_budget_respected_and_scenarios_differ():
    sc = PLAN.generate_scenarios(budget_cr=8000)
    for s in sc:
        assert s["eval"]["cost_cr"] <= 8000 + 1e-6
    sigs = {tuple(sorted(c["name"] for c in s["corridors"])) for s in sc}
    assert len(sigs) >= 2                       # objectives produce different results
    a = next(s for s in sc if s["key"] == "A")["eval"]; b = next(s for s in sc if s["key"] == "B")["eval"]
    assert a["cost_cr"] <= b["cost_cr"] + 1e-6


def test_invalid_corridors_rejected():
    with pytest.raises(NodalError):
        PLAN.evaluate([{"stations": [{"id": NET.ids[0]}, {"id": NET.ids[1]}]}])          # no proposed station
    with pytest.raises(NodalError):
        PLAN.evaluate([{"stations": [{"id": NET.ids[0]}, {"lat": 40.0, "lon": 77.5}]}])   # outside Bengaluru
    with pytest.raises(NodalError):
        PLAN.evaluate([{"stations": [{"lat": 13.0, "lon": 77.5}, {"lat": 13.01, "lon": 77.5}]}])  # no existing attach


def test_custom_corridor_api_and_scenarios_roundtrip():
    s0 = NET.stations[NET.find("Hebbal") if False else NET.ids[0]]
    body = {"corridors": [{"name": "mine", "stations": [{"id": NET.find("Yeshwantpur")}, {"lat": 13.0358, "lon": 77.5970, "name": "Hebbal test"}]}]}
    r = client.post("/api/planning/evaluate", json=body); assert r.status_code == 200, r.text
    assert r.json()["after"]["stations"] == 84
    sv = client.post("/api/planning/scenarios", json={"name": "t", **body}); assert sv.status_code == 200
    sid = sv.json()["scenario"]["id"]
    assert any(x["id"] == sid for x in client.get("/api/planning/scenarios").json())
    assert "lat" in client.get(f"/api/planning/scenarios/{sid}/export?format=csv").text
    assert client.get(f"/api/planning/scenarios/{sid}/export").json()["hypothetical"] is True
    assert client.delete(f"/api/planning/scenarios/{sid}").status_code == 200
    assert client.get("/api/planning/scenarios/zzz/export").status_code == 400
    assert client.post("/api/planning/evaluate", json={"corridors": [{"stations": [{"id": "x"}]}]}).status_code == 422


def test_candidates_api_weights_change_top_result():
    cost = client.post("/api/planning/candidates", json={"weights": {"cost": 1}}).json()["candidates"][0]
    cov = client.post("/api/planning/candidates", json={"weights": {"coverage": 1, "destinations": 1}}).json()["candidates"][0]
    assert cost["cost_cr"] <= cov["cost_cr"] and cost["id"] != cov["id"]
    assert "explain" in cov


def test_failure_edges_lines_and_overrides():
    maj = NET.find("Majestic"); nb = list(NET.adj_km[maj])[0]
    f = client.post("/api/failure", json={"removed_edges": [[maj, nb]]}).json()
    assert f["after"]["components"] == 2 and sum(f["after"]["component_sizes"]) == 83
    y = client.post("/api/failure", json={"removed_line": "Yellow"}).json(); assert y["after"]["components"] == 16
    assert client.post("/api/failure", json={}).status_code == 400
    assert client.post("/api/failure", json={"removed_line": "Pink"}).status_code == 400
    snap = copy.deepcopy(NET.adj_km)
    t = client.get("/api/trace", params={"name": "dijkstra", "source": maj, "target": nb, "overrides": f"{maj}~{nb}:99"}).json()
    assert t["final_dist"] == 99 or t["final_dist"] < 99     # direct edge edited; a longer weight can't beat path in a tree
    assert NET.adj_km == snap                                 # overrides act on copies
    k0 = client.get("/api/trace", params={"name": "kruskal", "source": maj, "scope": "candidate", "max_km": 3}).json()
    k1 = client.get("/api/trace", params={"name": "kruskal", "source": maj, "scope": "candidate", "max_km": 3, "overrides": f"{maj}~{nb}:x"}).json()
    assert k1["weight"] != k0["weight"] or k1["edges"] != k0["edges"]


# ====== context data, multimodal, economics, road alignments ======
import json, math
from app.main import CTX, get_mm
from app.economics import economics, crf
from app.data import haversine


def test_census_totals_and_known_wards():
    assert sum(p["pop"] for p in CTX.props) == 8443675                       # official 2011 BBMP total (84,43,675)
    horamavu = next(p for p in CTX.props if p["name"] == "Horamavu"); assert horamavu["pop"] == 95368
    assert all(abs(p["density"] - p["pop"] / p["area_km2"]) < 0.2 for p in CTX.props)
    assert len(CTX.props) == 198 and all(g.is_valid for g in CTX.geoms)


def test_cell_population_reconstructs_city_total():
    tot = PLAN.accessibility()["people_known_total"]
    assert abs(tot - 8443675) / 8443675 < 0.02                               # 1 km² cells reproduce the total within 2%
    assert not np.isnan(CTX.density(np.array([12.9757]), np.array([77.5724]))[0])
    assert np.isnan(CTX.density(np.array([13.1986]), np.array([77.7066]))[0])  # airport lies outside the BBMP wards


def test_population_weighted_coverage():
    ev = PLAN.evaluate([strip(POOL[0])])
    assert ev["people_improved"] >= 0 and ev["after"]["people"]["excellent"] >= ev["before"]["people"]["excellent"]
    assert abs(sum(ev["before"]["people"].values()) - sum(ev["after"]["people"].values())) <= 3   # people are reclassified, never created (int truncation only)
    assert ev["criteria_raw"]["coverage"] >= ev["people_improved"] or ev["people_improved"] == 0


def test_road_following_alignment_is_near_bus_corridors():
    road = [p for p in POOL if p["alignment"].startswith("Follows")]
    assert len(road) > len(POOL) / 2
    c = road[0]; pts = [pt for g in c["seg_geoms"] for pt in g]
    stops = np.stack([CTX.slon, CTX.slat], 1)
    far = [min(haversine(pt[1], pt[0], s[1], s[0]) for s in stops[np.argsort(np.hypot(*(stops - np.array(pt)).T))[:5]]) for pt in pts[1:-1]]
    assert max(far) < 1.5                                                     # vertices lie on bus stops (within connector tolerance)
    assert c["detour"] < 1.9


def test_multimodal_metro_fare_and_times_come_from_feed():
    mm = get_mm(); a, b = NET.find("Majestic"), NET.find("Lalbagh")
    t, km, xf, fare = mm.mp[(a, b)]
    assert fare == json.load(open(str(Path(__file__).resolve().parents[2] / "datasets/processed/metro_fares.json")))["fares"][f"{a}|{b}"]
    r = NET.route(a, b, "time"); assert t == pytest.approx(r["time_min"]) and km == pytest.approx(r["distance_km"])
    assert mm.mp[(a, b)][3] == mm.mp[(b, a)][3]


def test_multimodal_routes_valid():
    mm = get_mm(); o, d = (12.9857, 77.7380), (12.8456, 77.6603)
    res = mm.alternatives(o, d)["alternatives"]; assert res
    straight = haversine(*o, *d)
    for r in res:
        t = r["totals"]
        assert t["km"] >= straight * 0.95                                      # no route shorter than the straight line
        assert t["minutes"] >= straight / 60 * 60 * 0.9                       # nothing faster than 60 km/h
        assert abs(t["minutes"] - sum(l["minutes"] for l in r["legs"])) < 0.01
        assert r["legs"][0]["mode"] in ("walk",) and r["legs"][-1]["mode"] == "walk"
    best = min(res, key=lambda r: r["totals"]["minutes"]); assert best["label"] in ("time", "distance")
    # mixed journey exists somewhere in the city
    mixed = mm.alternatives((13.1007, 77.5963), (12.9208, 77.5801))["alternatives"]
    assert any({"bus", "metro"} <= set(r["totals"]["modes"]) for r in mixed)


def test_multimodal_objectives_behave():
    mm = get_mm(); o, d = (12.9857, 77.7380), (12.9396, 77.5948)
    t = mm.route(o, d, "time"); c = mm.route(o, d, "cost"); x = mm.route(o, d, "transfers"); dist = mm.route(o, d, "distance")
    gc = lambda r: r["totals"]["cost_inr"] + 0.5 * r["totals"]["minutes"]
    assert t["totals"]["minutes"] <= min(c["totals"]["minutes"], x["totals"]["minutes"], dist["totals"]["minutes"]) + 1e-6
    assert gc(c) <= gc(t) + 1e-6 and dist["totals"]["km"] <= t["totals"]["km"] + 1e-6
    only_bus = mm.route(o, d, "time", metro=False); assert "metro" not in only_bus["totals"]["modes"]
    with pytest.raises(NodalError):
        mm.route((12.99, 77.74), (13.4, 77.9), "time")                         # destination far from any stop


def test_multimodal_api():
    r = client.get("/api/multimodal/route", params={"olat": 12.9352, "olon": 77.6245, "dlat": 13.0476, "dlon": 77.6220}).json()
    assert r["alternatives"] and r["notes"]["walk"]
    assert client.get("/api/multimodal/route", params={"olat": 40, "olon": 77.6, "dlat": 13, "dlon": 77.6}).status_code == 422
    assert client.get("/api/layers/wards").json()["meta"]["total_pop"] == 8443675
    assert len(client.get("/api/layers/bus").json()["stops"]) > 5000
    assert all(p["limitations"] for p in client.get("/api/provenance").json())


def test_economics_math():
    ev = PLAN.evaluate([strip(POOL[0])])
    e = economics(ev, cost_per_km_cr=200, cost_per_station_cr=50, cost_per_train_cr=20, headway_min=5, avg_speed_kmh=30, turnaround_min=4, discount_rate=0.08, life_years=30)
    assert e["capital_cr"] == pytest.approx(ev["length_km"] * 200 + ev["new_stations"] * 50 + e["trains_needed"] * 20)
    assert e["trains_needed"] == math.ceil((2 * ev["length_km"] / 30 * 60 + 8) / 5)
    assert e["cost_per_km_cr"] == pytest.approx(e["capital_cr"] / ev["length_km"]) and e["cost_per_station_cr"] == pytest.approx(e["capital_cr"] / ev["new_stations"])
    assert crf(0.08, 30) == pytest.approx(0.08883, rel=1e-3) and e["annualised_cost_cr"] == pytest.approx(e["capital_cr"] * crf(0.08, 30))
    assert e["demand_dependent"] is None                                       # no demand assumed -> nothing invented
    e2 = economics(ev, daily_trips=100000, value_of_time_inr_per_hour=150)
    s = ev["before"]["mean_pair_min"] - ev["after"]["mean_pair_min"]
    assert e2["demand_dependent"]["person_hours_saved_per_year"] == pytest.approx(100000 * 365 * s / 60)
    assert e2["demand_dependent"]["benefit_cost_ratio"] == pytest.approx(e2["demand_dependent"]["annual_time_benefit_cr"] / e2["annualised_cost_cr"])
    assert economics(ev, budget_cr=1.0)["within_budget"] is False


def test_economics_api():
    c = strip(POOL[0]); r = client.post("/api/economics", json={"corridors": [c], "cost_per_km_cr": 250, "daily_trips": 50000}).json()
    assert r["label"].startswith("HYPOTHETICAL") and r["capital_cr"] > 0 and r["demand_dependent"]["person_hours_saved_per_year"] >= 0
    assert client.post("/api/economics", json={"corridors": [c], "avg_speed_kmh": 1}).status_code == 422
