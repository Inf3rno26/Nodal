import itertools, time, random
from functools import cached_property
from . import algorithms as A
from .data import (load_network, haversine, TRANSFER_MIN, TRANSFER_PENALTY, TRANSFER_BIG,
                   load_interchange_costs, HEADWAY_MIN)

OBJECTIVES = ("distance", "time", "generalized", "transfers")


class NodalError(ValueError):
    pass


def ekey(a, b):
    return (a, b) if a < b else (b, a)


class Network:
    def __init__(self):
        self.stations, self.edges, self.line_colors, self.source = load_network()
        self.ids = list(self.stations)
        self.adj_km = {i: {} for i in self.ids}
        self.adj_min = {i: {} for i in self.ids}
        self.edge_by_pair = {}
        for e in self.edges:
            for a, b in ((e["u"], e["v"]), (e["v"], e["u"])):
                self.adj_km[a][b] = e["km"]; self.adj_min[a][b] = e["min"]
            self.edge_by_pair[ekey(e["u"], e["v"])] = e
        self._dist = {}
        # Load realistic interchange costs from GTFS
        self.transfer_costs = load_interchange_costs()

    # ---------- helpers ----------
    def find(self, text):
        t = text.lower()
        hits = [i for i, st in self.stations.items() if t in st["name"].lower()]
        if len(hits) != 1:
            raise NodalError(f"{text!r} matches {len(hits)} stations")
        return hits[0]

    def check(self, *ids):
        for i in ids:
            if i not in self.stations:
                raise NodalError(f"unknown station id: {i!r}")

    def dkm(self, a, b):
        k = ekey(a, b)
        if k not in self._dist:
            A_, B_ = self.stations[a], self.stations[b]
            self._dist[k] = haversine(A_["lat"], A_["lon"], B_["lat"], B_["lon"])
        return self._dist[k]

    def sub(self, adj, removed):
        return {u: {v: w for v, w in nb.items() if v not in removed}
                for u, nb in adj.items() if u not in removed}

    def _transfer_cost(self, sid, objective):
        """Return the realistic transfer edge weight for a given station and objective."""
        tc = self.transfer_costs.get(sid)
        if objective == "distance":
            return 0.0
        if objective == "transfers":
            return TRANSFER_BIG + (tc["total_transfer_min"] if tc else TRANSFER_MIN)
        if tc:
            base = tc["total_transfer_min"]
        else:
            base = TRANSFER_MIN
        if objective == "generalized":
            return base + TRANSFER_PENALTY
        return base  # "time"

    # ---------- network & metrics ----------
    def network_json(self):
        # Enrich interchange stations with real transfer costs
        interchange_costs = {}
        for sid, st in self.stations.items():
            if len(st["lines"]) > 1:
                tc = self.transfer_costs.get(sid, {})
                interchange_costs[sid] = {
                    "station_name": st["name"],
                    "lines": st["lines"],
                    "walking_min": tc.get("walking_min", 0),
                    "min_transfer_min": tc.get("min_transfer_min", TRANSFER_MIN),
                    "wait_min": tc.get("wait_min", HEADWAY_MIN / 2),
                    "total_transfer_min": tc.get("total_transfer_min", TRANSFER_MIN),
                    "has_gtfs_data": tc.get("has_gtfs_data", False),
                }
        return {"stations": list(self.stations.values()),
                "edges": self.edges, "line_colors": self.line_colors, "source": self.source,
                "assumptions": {"transfer_min": TRANSFER_MIN, "transfer_penalty": TRANSFER_PENALTY,
                                "headway_min": HEADWAY_MIN,
                                "distance_note": "km = distance along the track alignment (GTFS shape_dist_traveled)",
                                "time_note": "min = timetable arrival-to-arrival time, modeled by the feed author from BMRCL timetables",
                                "transfer_note": "Transfer cost = walking time (from GTFS pathways) + wait time (headway/2). Real data at Majestic and Baiyappanahalli.",
                                "scope_note": "Operational Purple, Green and Yellow lines only; proposed lines are not in the feed"},
                "interchange_costs": interchange_costs}

    @cached_property
    def intel_cache(self):
        adj = self.adj_km
        dc, bc, ap, cc = A.degree_centrality(adj), A.betweenness(adj), A.articulation_points(adj), A.closeness(adj)
        return {i: {"id": i, "name": self.stations[i]["name"], "lines": self.stations[i]["lines"],
                    "degree": len(adj[i]), "degree_centrality": dc[i], "betweenness": bc[i], "closeness": cc[i],
                    "articulation": i in ap} for i in self.ids}

    def metrics(self, adj=None):
        adj = adj or self.adj_km
        n = len(adj); m = sum(len(v) for v in adj.values()) // 2
        comps = A.components(adj)
        deg = {}
        for u in adj:
            deg[len(adj[u])] = deg.get(len(adj[u]), 0) + 1
        return {"stations": n, "connections": m, "lines": len(self.line_colors), "components": len(comps),
                "component_sizes": sorted((len(c) for c in comps), reverse=True),
                "density": 2 * m / (n * (n - 1)) if n > 1 else 0.0,
                "avg_degree": 2 * m / n if n else 0.0,
                "interchanges": sum(1 for s in self.stations.values() if len(s["lines"]) > 1),
                "articulation_points": len(A.articulation_points(adj)),
                "total_km": sum(e["km"] for e in self.edges) if adj is self.adj_km else
                            sum(w for u in adj for w in adj[u].values()) / 2,
                "avg_path_hops": A.avg_shortest_path_hops(adj),
                "degree_distribution": dict(sorted(deg.items())),
                "stations_per_line": {l: sum(1 for s in self.stations.values() if l in s["lines"]) for l in self.line_colors},
                "is_tree": m == n - len(comps)}

    # ---------- routing ----------
    def _state_adj(self, objective, removed, ban=frozenset()):
        adj = {}

        def add(a, b, w):
            adj.setdefault(a, {})[b] = w; adj.setdefault(b, {})[a] = w
        for e in self.edges:
            if e["u"] in removed or e["v"] in removed or ekey(e["u"], e["v"]) in ban:
                continue
            w = e["km"] if objective == "distance" else e["min"]
            add(f"{e['u']}|{e['line']}", f"{e['v']}|{e['line']}", w)
        for sid, st in self.stations.items():
            if sid in removed:
                continue
            tw = self._transfer_cost(sid, objective)
            for l1, l2 in itertools.combinations(st["lines"], 2):
                add(f"{sid}|{l1}", f"{sid}|{l2}", tw)
            for l in st["lines"]:
                adj.setdefault(f"{sid}|{l}", {})
        return adj

    def route(self, src, dst, objective="time", removed=frozenset(), ban=frozenset()):
        self.check(src, dst)
        if objective not in OBJECTIVES:
            raise NodalError(f"objective must be one of {OBJECTIVES}")
        if src in removed or dst in removed:
            raise NodalError("origin or destination is among the failed stations")
        adj = self._state_adj(objective, removed, ban)
        adj["__S"] = {f"{src}|{l}": 0.0 for l in self.stations[src]["lines"]}
        for s in adj["__S"]:
            adj[s]["__S"] = 0.0
        dist, prev, _ = A.dijkstra(adj, ["__S"])
        cands = [(dist[f"{dst}|{l}"], f"{dst}|{l}") for l in self.stations[dst]["lines"]]
        best_d, best = min(cands)
        if best_d == A.INF:
            return {"reachable": False, "objective": objective, "src": src, "dst": dst}
        states = A.path_to(prev, best)[1:]
        stations_seq, km, mins, transfers, segs = [], 0.0, 0.0, [], []
        transfer_detail = []  # Detailed per-transfer breakdown
        for i, s in enumerate(states):
            sid, line = s.split("|")
            if not stations_seq or stations_seq[-1] != sid:
                stations_seq.append(sid)
            if i == 0:
                segs.append({"line": line, "from": sid, "to": sid})
                continue
            psid, pline = states[i - 1].split("|")
            if psid == sid:
                transfers.append(sid)
                tc = self.transfer_costs.get(sid, {})
                cost = tc.get("total_transfer_min", TRANSFER_MIN)
                mins += cost
                segs.append({"line": line, "from": sid, "to": sid})
                transfer_detail.append({
                    "station": sid,
                    "station_name": self.stations[sid]["name"],
                    "from_line": pline,
                    "to_line": line,
                    "walking_min": tc.get("walking_min", 0),
                    "wait_min": tc.get("wait_min", HEADWAY_MIN / 2),
                    "total_min": round(cost, 2),
                    "has_gtfs_data": tc.get("has_gtfs_data", False),
                })
            else:
                e = self.edge_by_pair[ekey(psid, sid)]
                km += e["km"]; mins += e["min"]; segs[-1]["to"] = sid
        return {"reachable": True, "objective": objective, "src": src, "dst": dst,
                "stations": stations_seq, "distance_km": km, "time_min": mins,
                "transfers": len(transfers), "transfer_stations": transfers,
                "transfer_detail": transfer_detail,
                "lines_used": [s["line"] for s in segs], "segments": segs,
                "objective_value": best_d if objective != "transfers" else best_d,
                "weight_explanation": {
                    "distance": "sum of haversine edge lengths (km)",
                    "time": "sum of timetable segment times + realistic per-station transfer cost (walking + waiting)",
                    "generalized": "time + 8 min-equivalent penalty per transfer",
                    "transfers": "lexicographic: 10000 per transfer, then time (value = 10000*transfers + time)"}[objective]}

    # ---------- algorithm traces ----------
    def candidate_edges(self, max_km, k=0):
        pairs = {}
        for a, b in itertools.combinations(self.ids, 2):
            d = self.dkm(a, b)
            if d <= max_km:
                pairs[(a, b)] = d
        if k and k > 0:
            keep = set()
            for a in self.ids:
                near = sorted(((d, p) for p, d in pairs.items() if a in p))[:k]
                keep.update(p for _, p in near)
            pairs = {p: d for p, d in pairs.items() if p in keep}
        return [(a, b, d) for (a, b), d in pairs.items()]

    def graph_for(self, scope, max_km=3.0, k=0):
        if scope == "existing":
            edges = [(e["u"], e["v"], e["km"]) for e in self.edges]
        elif scope == "candidate":
            edges = self.candidate_edges(max_km, k)
        else:
            raise NodalError("scope must be 'existing' or 'candidate'")
        adj = {i: {} for i in self.ids}
        for u, v, w in edges:
            adj[u][v] = w; adj[v][u] = w
        return adj, edges

    def override(self, adj, text):
        """Apply 'A~B:3.2;C~D:x' edits (value = new weight, or x to remove the connection). Returns a copy."""
        out = {u: dict(nb) for u, nb in adj.items()}
        for part in [p for p in (text or "").split(";") if p.strip()]:
            try:
                pair, val = part.split(":"); a, b = pair.split("~")
            except ValueError:
                raise NodalError(f"bad override {part!r}; use A~B:weight or A~B:x")
            self.check(a, b)
            if val.strip().lower() == "x":
                out[a].pop(b, None); out[b].pop(a, None)
            else:
                w = float(val)
                if w <= 0:
                    raise NodalError("edited weights must be positive")
                out[a][b] = w; out[b][a] = w
        return out

    def trace(self, name, source, target=None, scope="existing", max_km=3.0, k=0, weight="km", overrides=None):
        self.check(source)
        if target:
            self.check(target)
        if name == "dijkstra":
            adj = self.override(self.adj_km if weight == "km" else self.adj_min, overrides)
            dist, prev, steps = A.dijkstra(adj, [source], target=target, trace=True)
            path = A.path_to(prev, target) if target and dist[target] < A.INF else []
            return {"algo": name, "source": source, "target": target, "weight": weight, "steps": steps,
                    "path": path, "final_dist": None if not target else (dist[target] if dist[target] < A.INF else None),
                    "complexity": "O((V+E) log V)", "n": len(adj)}
        adj, edges = self.graph_for(scope, max_km, k)
        if overrides:
            adj = self.override(adj, overrides); edges = [(u, v, w) for u in adj for v, w in adj[u].items() if u < v]
        if name == "kruskal":
            r = A.kruskal(self.ids, edges, trace=True)
        elif name == "prim":
            r = A.prim(adj, start=source, trace=True)
        else:
            raise NodalError("algorithm must be dijkstra, kruskal or prim")
        return {"algo": name, "scope": scope, "source": source, "steps": r["steps"], "edges": r["edges"],
                "weight": r["weight"], "examined": r["examined"], "components": r["components"],
                "candidate_edges": len(edges), "n": len(adj),
                "complexity": "O(E log E)" if name == "kruskal" else "O(E log V)"}

    def compare(self, max_km=3.0, k=0, repeats=30):
        out = []
        for scope in ("existing", "candidate"):
            adj, edges = self.graph_for(scope, max_km, k)
            row = {"scope": scope, "V": len(adj), "E": len(edges)}
            for name, fn in (("kruskal", lambda: A.kruskal(self.ids, edges)), ("prim", lambda: A.prim(adj, self.ids[0]))):
                ts = []
                for _ in range(repeats):
                    t0 = time.perf_counter(); r = fn(); ts.append(time.perf_counter() - t0)
                ts.sort()
                row[name] = {"time_ms": ts[len(ts) // 2] * 1000, "examined": r["examined"], "weight": r["weight"],
                             "selected": len(r["edges"]), "components": r["components"]}
            row["weights_equal"] = abs(row["kruskal"]["weight"] - row["prim"]["weight"]) < 1e-9
            out.append(row)
        return {"results": out, "complexity": {"kruskal": "O(E log E)", "prim": "O(E log V) with binary heap"}}

    # ---------- expansion ----------
    def expansion(self, max_km=3.0, k=0, algorithm="kruskal", budget_km=None, cost_per_km=300.0):
        adj, edges = self.graph_for("candidate", max_km, k)
        kr = A.kruskal(self.ids, edges, budget=budget_km)
        pr = A.prim(adj, start=self.ids[0], budget=budget_km)
        if algorithm not in ("kruskal", "prim"):
            raise NodalError("algorithm must be kruskal or prim")
        chosen = kr if algorithm == "kruskal" else pr
        sel = {ekey(u, v) for u, v, _ in chosen["edges"]}
        existing = {ekey(e["u"], e["v"]) for e in self.edges}
        base_km = sum(e["km_straight"] for e in self.edges)
        rejected = sorted(((w, u, v) for u, v, w in edges if ekey(u, v) not in sel))
        return {"algorithm": algorithm, "max_km": max_km, "k": k, "budget_km": budget_km, "cost_per_km": cost_per_km,
                "candidate_edges": len(edges),
                "selected": [{"u": u, "v": v, "km": w, "existing": ekey(u, v) in existing} for u, v, w in chosen["edges"]],
                "rejected": [{"u": u, "v": v, "km": w} for w, u, v in rejected[:300]],
                "rejected_count": len(rejected),
                "mst_km": chosen["weight"], "components": chosen["components"], "budget_stopped": chosen["stopped"],
                "overlap_with_existing": sum(1 for p in sel if p in existing),
                "estimated_cost": chosen["weight"] * cost_per_km,
                "baseline": {"existing_km": base_km, "existing_track_km": sum(e["km"] for e in self.edges), "basis": "existing links measured as straight lines, like the candidate links", "existing_edges": len(self.edges),
                             "existing_cost_same_model": base_km * cost_per_km},
                "difference_km": chosen["weight"] - base_km,
                "kruskal_km": kr["weight"], "prim_km": pr["weight"],
                "limitations": "Straight-line, from-scratch MST over station pairs: ignores real alignments, terrain, land acquisition, "
                               "demand, line operability and cost variation (elevated vs underground). Cost = km x assumed Rs crore/km. "
                               "Not a construction plan and not evidence of savings."}

    # ---------- failure ----------
    def _pairs(self, adj):
        return sum(len(c) * (len(c) - 1) // 2 for c in A.components(adj))

    def _avg_travel_time(self, adj_min, sample_n=20):
        """Compute average pairwise shortest-path time (minutes) over a sample of stations."""
        ids = [i for i in self.ids if i in adj_min]
        if len(ids) < 2:
            return None
        sample = ids if len(ids) <= sample_n else random.sample(ids, sample_n)
        total, count = 0.0, 0
        for s in sample:
            dist, _, _ = A.dijkstra(adj_min, [s])
            for v, d in dist.items():
                if v != s and d < A.INF and v in adj_min:
                    total += d
                    count += 1
        return round(total / count, 2) if count else None

    def failure(self, removed, src=None, dst=None, removed_edges=(), removed_line=None):
        removed = set(removed)
        self.check(*removed)
        ban = set()
        for u, v in removed_edges:
            self.check(u, v)
            if v not in self.adj_km[u]:
                raise NodalError(f"no direct connection between {u} and {v}")
            ban.add(ekey(u, v))
        if removed_line:
            if removed_line not in self.line_colors:
                raise NodalError(f"unknown line {removed_line!r}")
            ban |= {ekey(e["u"], e["v"]) for e in self.edges if e["line"] == removed_line}
        if not removed and not ban:
            raise NodalError("select at least one station, connection or line to fail")

        after = self.sub(self.adj_km, removed)
        after_min = self.sub(self.adj_min, removed)
        for a, b in ban:
            if a in after and b in after:
                after[a].pop(b, None); after[b].pop(a, None)
            if a in after_min and b in after_min:
                after_min[a].pop(b, None); after_min[b].pop(a, None)

        comps = sorted(A.components(after), key=len, reverse=True)
        n_after = len(after); total_pairs = n_after * (n_after - 1) // 2; reach = self._pairs(after)
        main = set(comps[0]) if comps else set()
        bc0, bc1 = A.betweenness(self.adj_km), A.betweenness(after) if n_after > 2 else {}
        chg = sorted(({
            "id": i, "name": self.stations[i]["name"],
            "before": bc0[i], "after": bc1.get(i, 0.0)
        } for i in after), key=lambda r: -abs(r["after"] - r["before"]))[:6]

        # --- Directly affected edges ---
        affected_edges = []
        for e in self.edges:
            u, v = e["u"], e["v"]
            # Edge is cut if one endpoint is removed, or it's in ban, or its line is removed
            if u in removed or v in removed or ekey(u, v) in ban:
                affected_edges.append({"u": u, "v": v, "u_name": self.stations[u]["name"],
                                       "v_name": self.stations[v]["name"],
                                       "line": e["line"], "km": e["km"], "min": e["min"]})

        # --- Passenger load redistribution (betweenness ratio on surviving edges) ---
        passenger_load = []
        if n_after > 2 and bc1:
            bc0_norm = {i: bc0.get(i, 0.0) for i in after}
            # For edges in the surviving graph, estimate load increase via node betweenness proxy
            edge_load = []
            for e in self.edges:
                u, v = e["u"], e["v"]
                if u not in after or v not in after:
                    continue
                if u not in after.get(u, {}) and v not in after.get(v, {}):
                    continue
                # Edge load ~ avg betweenness of its endpoints
                b_before = (bc0.get(u, 0) + bc0.get(v, 0)) / 2
                b_after = (bc1.get(u, 0) + bc1.get(v, 0)) / 2
                if b_before > 1e-9:
                    inc = round(100 * (b_after - b_before) / b_before, 1)
                    edge_load.append({"u": u, "v": v,
                                      "u_name": self.stations[u]["name"],
                                      "v_name": self.stations[v]["name"],
                                      "line": e["line"],
                                      "load_increase_pct": inc})
            passenger_load = sorted(edge_load, key=lambda x: -x["load_increase_pct"])[:5]

        # --- Average travel time before/after ---
        avg_before = self._avg_travel_time(self.adj_min)
        avg_after = self._avg_travel_time(after_min)
        travel_time_increase_pct = None
        if avg_before and avg_after:
            travel_time_increase_pct = round(100 * (avg_after - avg_before) / avg_before, 1)

        out = {"removed": sorted(removed), "removed_edges": [list(e) for e in sorted(ban)], "removed_line": removed_line,
               "before": {"components": len(A.components(self.adj_km)), "stations": len(self.adj_km),
                          "reachable_pair_fraction": 1.0,
                          "avg_path_hops": A.avg_shortest_path_hops(self.adj_km),
                          "avg_travel_time_min": avg_before},
               "after": {"components": len(comps), "stations": n_after, "component_sizes": [len(c) for c in comps],
                         "reachable_pair_fraction": reach / total_pairs if total_pairs else 1.0,
                         "avg_path_hops": A.avg_shortest_path_hops(after),
                         "avg_travel_time_min": avg_after},
               "components": [{"id": i, "stations": c} for i, c in enumerate(comps)],
               "affected": sorted(s for s in after if s not in main),
               "affected_edges": affected_edges,
               "passenger_load": passenger_load,
               "avg_travel_time_before": avg_before,
               "avg_travel_time_after": avg_after,
               "travel_time_increase_pct": travel_time_increase_pct,
               "connectivity_loss": 1 - (reach / total_pairs if total_pairs else 1.0),
               "centrality_change": chg}
        if src and dst:
            self.check(src, dst)
            b = self.route(src, dst, "time")
            try:
                a = self.route(src, dst, "time", frozenset(removed), frozenset(ban))
            except NodalError as ex:
                a = {"reachable": False, "error": str(ex)}
            out["route_check"] = {"before": b, "after": a}
        return out

    def failure_ranking(self):
        rows = []
        for s in self.ids:
            f = self.failure([s])
            rows.append({"id": s, "name": self.stations[s]["name"], "connectivity_loss": f["connectivity_loss"],
                         "components_after": f["after"]["components"], "largest_component": f["after"]["component_sizes"][0]})
        rows.sort(key=lambda r: -r["connectivity_loss"])
        return rows

    def failure_recover(self, removed, new_edges=None, new_stations=None):
        """Simulate failure + recovery via hypothetical new connections.

        new_edges: list of {u, v, min, km, line}
        new_stations: list of {id, name, lat, lon, lines}
        Returns combined before/after failure and recovery analysis.
        """
        # Base failure analysis
        base = self.failure(removed)

        # Build augmented adjacency for recovery
        removed_set = frozenset(removed)
        aug_min = self.sub(self.adj_min, removed_set)
        aug_km = self.sub(self.adj_km, removed_set)

        # Add hypothetical stations
        hyp_stations = {}
        for s in (new_stations or []):
            sid = s.get("id") or f"HYP_{s['name'].replace(' ', '_')}"
            hyp_stations[sid] = s
            if sid not in aug_min:
                aug_min[sid] = {}
                aug_km[sid] = {}

        # Add hypothetical edges
        for e in (new_edges or []):
            u, v = e["u"], e["v"]
            # Allow connecting to existing stations (if not removed) or new hypothetical ones
            u_ok = (u in self.stations and u not in removed_set) or u in hyp_stations
            v_ok = (v in self.stations and v not in removed_set) or v in hyp_stations
            if not u_ok or not v_ok:
                continue
            # Ensure nodes exist in aug graphs
            aug_min.setdefault(u, {}); aug_km.setdefault(u, {})
            aug_min.setdefault(v, {}); aug_km.setdefault(v, {})
            t = float(e.get("min", 10.0))
            k = float(e.get("km", 2.0))
            aug_min[u][v] = t; aug_min[v][u] = t
            aug_km[u][v] = k; aug_km[v][u] = k

        # Recovery metrics
        comps_after = A.components(aug_km)
        n_after = len(aug_km)
        total_pairs = n_after * (n_after - 1) // 2
        reachable = self._pairs(aug_km)
        avg_before = base["avg_travel_time_before"]
        avg_recover = self._avg_travel_time(aug_min)
        improvement_pct = None
        if avg_before and avg_recover:
            # improvement = how much of the increase is recovered
            improvement_pct = round(100 * (base["avg_travel_time_after"] - avg_recover) /
                                    max(base["avg_travel_time_after"] - avg_before, 0.01), 1)

        still_isolated = []
        if comps_after:
            main = set(max(comps_after, key=len))
            still_isolated = [{"id": s, "name": self.stations[s]["name"] if s in self.stations else s}
                              for c in comps_after if c is not max(comps_after, key=len)
                              for s in c]

        return {
            "failure": base,
            "recovery": {
                "hypothetical_edges": len(new_edges or []),
                "hypothetical_stations": len(new_stations or []),
                "components": len(comps_after),
                "reachable_pair_fraction": reachable / total_pairs if total_pairs else 1.0,
                "avg_travel_time_min": avg_recover,
                "avg_travel_time_before_failure": avg_before,
                "avg_travel_time_after_failure": base["avg_travel_time_after"],
                "travel_time_recovered_pct": improvement_pct,
                "still_isolated": still_isolated,
                "fully_restored": len(comps_after) == 1,
            }
        }

    def interchange_costs_detail(self):
        """Return interchange costs enriched with station names and line info."""
        result = []
        for sid, st in self.stations.items():
            tc = self.transfer_costs.get(sid, {})
            result.append({
                "id": sid,
                "name": st["name"],
                "lines": st["lines"],
                "is_interchange": len(st["lines"]) > 1,
                "walking_min": tc.get("walking_min", 0.0),
                "min_transfer_min": tc.get("min_transfer_min", 0.0),
                "wait_min": tc.get("wait_min", HEADWAY_MIN / 2),
                "total_transfer_min": tc.get("total_transfer_min", TRANSFER_MIN),
                "has_gtfs_data": tc.get("has_gtfs_data", False),
            })
        return sorted(result, key=lambda x: (-x["total_transfer_min"], x["name"]))


NET = Network()
