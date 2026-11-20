import copy, random, sys
from pathlib import Path
import networkx as nx
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import algorithms as A
from app.services import NET, NodalError
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)
MAJ, WF, SILK, LAL = NET.find("Majestic"), NET.find("Whitefield"), NET.find("Silk Institute"), NET.find("Lalbagh")


def rand_graph(n, p, seed):
    rnd = random.Random(seed)
    adj = {i: {} for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if rnd.random() < p:
                w = round(rnd.uniform(1, 20), 3); adj[i][j] = w; adj[j][i] = w
    return adj


def to_nx(adj):
    G = nx.Graph(); G.add_nodes_from(adj)
    for u in adj:
        for v, w in adj[u].items():
            G.add_edge(u, v, weight=w)
    return G


def test_dijkstra_manual():
    adj = {"A": {"B": 1, "C": 4}, "B": {"A": 1, "C": 2, "D": 5}, "C": {"A": 4, "B": 2, "D": 1}, "D": {"B": 5, "C": 1}, "E": {}}
    d, p, _ = A.dijkstra(adj, ["A"])
    assert d["D"] == 4 and A.path_to(p, "D") == ["A", "B", "C", "D"] and d["E"] == A.INF


def test_dijkstra_negative_weight_rejected():
    with pytest.raises(ValueError):
        A.dijkstra({"a": {"b": -1}, "b": {"a": -1}}, ["a"])


@pytest.mark.parametrize("seed", range(8))
def test_algorithms_match_networkx(seed):
    adj = rand_graph(25, 0.15, seed); G = to_nx(adj)
    d, _, _ = A.dijkstra(adj, [0])
    ref = nx.single_source_dijkstra_path_length(G, 0)
    for v in adj:
        assert (d[v] == A.INF) == (v not in ref)
        if v in ref:
            assert d[v] == pytest.approx(ref[v])
    edges = [(u, v, w) for u in adj for v, w in adj[u].items() if u < v]
    kr, pr = A.kruskal(list(adj), edges), A.prim(adj, 0)
    ref_w = sum(d_["weight"] for _, _, d_ in nx.minimum_spanning_edges(G, data=True))
    assert kr["weight"] == pytest.approx(ref_w) and pr["weight"] == pytest.approx(ref_w)
    comps = len(A.components(adj))
    assert len(kr["edges"]) == len(adj) - comps == len(pr["edges"])
    F = nx.Graph(); F.add_nodes_from(adj); F.add_weighted_edges_from(kr["edges"])
    assert nx.is_forest(F)
    bc = A.betweenness(adj)
    G2 = nx.Graph(); G2.add_nodes_from(adj); G2.add_edges_from((u, v) for u in adj for v in adj[u])
    ref_bc = nx.betweenness_centrality(G2)
    for v in adj:
        assert bc[v] == pytest.approx(ref_bc[v], abs=1e-9)
    assert A.articulation_points(adj) == set(nx.articulation_points(G2))


def test_dataset_valid():
    m = NET.metrics()
    assert m["stations"] == 83 and m["components"] == 1 and m["interchanges"] == 2
    assert all(e["km"] > 0 and e["min"] > 0 and len(e["geometry"]) >= 2 for e in NET.edges)
    assert all(e["km"] >= e["km_straight"] * 0.99 for e in NET.edges)   # track length can't be shorter than straight line
    assert 90 < NET.metrics()["total_km"] < 100
    assert m["is_tree"]  # real topology (3 lines, 2 interchanges) is a tree, so no redundancy


def test_route_objectives():
    r = {o: NET.route(WF, SILK, o) for o in ("distance", "time", "generalized", "transfers")}
    assert all(v["reachable"] for v in r.values())
    assert r["transfers"]["transfers"] <= min(v["transfers"] for v in r.values())
    assert r["time"]["time_min"] <= min(v["time_min"] for v in r.values()) + 1e-9
    assert r["distance"]["distance_km"] <= min(v["distance_km"] for v in r.values()) + 1e-9
    assert r["time"]["transfers"] == 1 and MAJ in r["time"]["transfer_stations"]
    assert len({tuple(v["stations"]) for v in r.values()}) == 1   # tree network: only one simple path exists


def test_failure_preserves_original_and_disconnects():
    snap = copy.deepcopy(NET.adj_km)
    f = NET.failure([MAJ])
    assert NET.adj_km == snap
    assert f["after"]["components"] > 1 and f["connectivity_loss"] > 0
    f2 = NET.failure([WF])
    assert f2["after"]["components"] == 1  # terminal station: not an articulation point
    rc = NET.failure([MAJ], WF, SILK)["route_check"]
    assert rc["before"]["reachable"] and not rc["after"]["reachable"]


def test_expansion_and_budget():
    e = NET.expansion(5.0, 0, "kruskal")
    assert e["kruskal_km"] == pytest.approx(e["prim_km"]) and e["components"] == 1
    assert e["mst_km"] <= e["baseline"]["existing_km"] + 1e-3
    b = NET.expansion(5.0, 0, "kruskal", budget_km=20)
    assert b["mst_km"] <= 20 and b["components"] > 1
    tiny = NET.expansion(0.5, 0, "prim")
    assert tiny["components"] > 1  # disconnected candidate graph -> spanning forest


def test_api_and_errors():
    assert client.get("/api/metrics").json()["stations"] == 83
    assert client.get("/api/route", params={"src": "nope", "dst": MAJ}).status_code == 400
    assert client.get("/api/route", params={"src": MAJ, "dst": LAL, "objective": "bad"}).status_code == 400
    assert client.post("/api/failure", json={"removed": []}).status_code == 400
    assert client.get("/api/trace", params={"name": "kruskal", "source": MAJ}).json()["weight"] > 0
    assert "betweenness" in client.get("/api/export/stations.csv").text
    assert len(client.get("/api/failure/ranking").json()) == 83
