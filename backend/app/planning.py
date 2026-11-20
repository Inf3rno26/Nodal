"""Metro planning engine: accessibility analysis, corridor generation, multi-criteria scoring and before/after simulation.
Everything here is a HYPOTHETICAL planning model. No population, demand, terrain or land-use data is used (none is bundled).
Verified inputs: station coordinates and network (BMRCL GTFS feed). Hand-entered inputs: destinations.csv (approximate).
Assumptions are listed in ASSUME and echoed to the UI."""
import copy, csv, json, math, re, uuid
from pathlib import Path
import numpy as np
from . import algorithms as A
from .data import ROOT, haversine
from .services import NodalError, ekey

DEST_PATH = ROOT / "datasets" / "raw" / "destinations.csv"
SCEN_PATH = ROOT / "datasets" / "scenarios.json"
ASSUME = {"cell_km": 1.0, "excellent_km": 1.0, "moderate_km": 2.5, "study_radius_km": 6.0, "walk_kmh": 4.5, "walk_limit_km": 1.0,
          "feeder_kmh": 15.0, "road_kmh": 15.0, "min_spacing_km": 0.8, "default_cost_per_km": 300.0, "proximity_decay_km": 3.0}
CRITERIA = ["coverage", "destinations", "connectivity", "interchange", "cost", "integration", "feasibility", "environment"]
CRITERIA_INFO = {
    "coverage": "2011 Census residents (ward density × 1 km² cell) moving to a better access class (≤1 km / ≤2.5 km / farther). Cells outside the BBMP wards have no population data and count as 0",
    "destinations": "Gain in a 0–1 proximity score (linear decay to 0 at 3 km) summed over listed destinations",
    "connectivity": "Relative drop in mean destination-to-destination travel time (metro via Dijkstra, or direct road at 15 km/h, whichever is faster; access legs assumed)",
    "interchange": "Number of existing stations the corridor connects to",
    "cost": "Corridor km × assumed ₹ crore/km (lower is better)",
    "integration": "Ease of integration: 1.0 when attaching at a line terminal, 0.6 at a mid-line station (assumption)",
    "feasibility": "Geometry-only proxy: 1 / detour factor (alignment length ÷ straight-line distance). Terrain, land, water NOT evaluated",
    "environment": "Not evaluated: no environmental or land-use data available"}
PRESETS = {"A": {"name": "Scenario A — Low-cost expansion", "weights": {"cost": 5, "connectivity": 2, "integration": 2, "feasibility": 2, "coverage": 1, "destinations": 1, "interchange": 1}},
           "B": {"name": "Scenario B — Maximum accessibility", "weights": {"coverage": 5, "destinations": 4, "connectivity": 2, "interchange": 1, "feasibility": 1, "integration": 1, "cost": 0.5}},
           "C": {"name": "Scenario C — Balanced expansion", "weights": {"coverage": 2, "destinations": 2, "connectivity": 3, "interchange": 1, "cost": 3, "integration": 2, "feasibility": 2}},
           "IT": {"name": "Scenario D — IT corridor connectivity", "weights": {"destinations": 5, "connectivity": 3, "coverage": 1, "cost": 1, "integration": 1, "feasibility": 1, "interchange": 1}, "kinds": ["IT park"]}}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def seg_len(pl):
    return sum(haversine(pl[i][1], pl[i][0], pl[i + 1][1], pl[i + 1][0]) for i in range(len(pl) - 1))


class Planner:
    def __init__(self, net, ctx=None):
        self.net = net
        self.ctx = ctx
        self.ids = net.ids
        lat0 = sum(s["lat"] for s in net.stations.values()) / len(net.stations)
        self.KX, self.KY = 111.32 * math.cos(math.radians(lat0)), 110.57
        self.anchors = self._load_anchors()
        self.sxy = np.array([self.xy(net.stations[i]["lat"], net.stations[i]["lon"]) for i in self.ids])
        self.axy = np.array([self.xy(a["lat"], a["lon"]) for a in self.anchors])
        self.avg_kmh = sum(e["km"] for e in net.edges) / sum(e["min"] for e in net.edges) * 60
        self._lattice()
        self.cache, self.scenarios = {}, {}
        self._load_scenarios()
        self.base = None

    # ---------- inputs ----------
    def xy(self, lat, lon):
        return (lon * self.KX, lat * self.KY)

    def _load_anchors(self):
        rows = list(csv.DictReader(open(DEST_PATH, encoding="utf-8")))
        return [{"id": slug(r["name"]), "name": r["name"], "lat": float(r["lat"]), "lon": float(r["lon"]), "kind": r["kind"],
                 "importance": float(r["importance"]), "verification": r["verification"]} for r in rows]

    def _lattice(self):
        R, step = ASSUME["study_radius_km"], ASSUME["cell_km"]
        pts = np.vstack([self.sxy, self.axy])
        x0, x1, y0, y1 = pts[:, 0].min() - R, pts[:, 0].max() + R, pts[:, 1].min() - R, pts[:, 1].max() + R
        gx, gy = x0 + np.arange(int((x1 - x0) / step) + 1) * step, y0 + np.arange(int((y1 - y0) / step) + 1) * step
        GX, GY = np.meshgrid(gx, gy)
        P = np.stack([GX.ravel(), GY.ravel()], 1)
        dmin = np.sqrt(((P[:, None, :] - pts[None, :, :]) ** 2).sum(-1)).min(1)
        keep = dmin <= R
        self.cxy = P[keep]; ny, nx = GX.shape
        self.x0, self.y0, self.nx, self.ny, self.step = float(x0), float(y0), nx, ny, step
        kept = np.where(keep)[0]; self.rc = (kept // nx, kept % nx)
        index = -np.ones(len(P), int); index[keep] = np.arange(keep.sum())
        self.clon, self.clat = self.cxy[:, 0] / self.KX, self.cxy[:, 1] / self.KY
        self.d0 = self._dist(self.cxy, self.sxy)
        self.cls0 = self._cls(self.d0)
        d_anc = self._dist(self.cxy, self.axy, weights=[a["importance"] for a in self.anchors])
        under = np.clip((self.d0 - 1.0) / 3.0, 0, 1)
        near = np.max(np.clip(1 - np.sqrt(((self.cxy[:, None, :] - self.axy[None, :, :]) ** 2).sum(-1)) / 1.5, 0, 1) * np.array([a["importance"] for a in self.anchors])[None, :], axis=1)
        self.val = np.where(self.d0 < 0.8, 0.0, np.clip(0.6 * under + 0.8 * near, 0, 1))
        self.val2d = np.zeros((ny, nx)); self.val2d[self.rc] = self.val
        if self.ctx is not None:
            dens = self.ctx.density(self.clat, self.clon)            # people/km² (Census 2011); NaN outside the BBMP wards
            self.pop_known = ~np.isnan(dens); self.pop = np.where(self.pop_known, dens * step * step, 0.0)
            wd = self.ctx.worker_density(self.clat, self.clon); self.workers = np.where(np.isnan(wd), 0.0, wd * step * step)
        else:
            self.pop_known = np.zeros(len(self.cxy), bool); self.pop = np.zeros(len(self.cxy)); self.workers = np.zeros(len(self.cxy))
        nbr = [[] for _ in range(len(self.cxy))]
        for r in range(ny):
            for c in range(nx):
                u = index[r * nx + c]
                if u < 0:
                    continue
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        rr, cc = r + dr, c + dc
                        if (dr or dc) and 0 <= rr < ny and 0 <= cc < nx and index[rr * nx + cc] >= 0:
                            nbr[u].append((int(index[rr * nx + cc]), math.hypot(dr, dc) * step))
        self.nbr, self._adj, self._radj = nbr, {}, {}

    def _dist(self, P, Q, weights=None):
        return np.sqrt(((P[:, None, :] - Q[None, :, :]) ** 2).sum(-1)).min(1)

    def _cls(self, d):
        return np.where(d <= ASSUME["excellent_km"], 0, np.where(d <= ASSUME["moderate_km"], 1, 2))

    # ---------- accessibility ----------
    def accessibility(self):
        names = ["excellent", "moderate", "poor"]
        cells = [{"lat": round(float(self.clat[i]), 5), "lon": round(float(self.clon[i]), 5), "d": round(float(self.d0[i]), 2), "cls": int(self.cls0[i]),
                  "pop": int(self.pop[i]) if self.pop_known[i] else None} for i in range(len(self.cxy))]
        summ = {n: int((self.cls0 == k).sum()) for k, n in enumerate(names)}
        people = {n: int(self.pop[self.cls0 == k].sum()) for k, n in enumerate(names)}
        return {"cells": cells, "cell_km": ASSUME["cell_km"], "summary_km2": summ, "people_by_class": people, "people_known_total": int(self.pop.sum()), "cells_without_population_data": int((~self.pop_known).sum()),
                "underserved_wards": self.underserved_wards(), "classes": names, "anchors": self.anchor_status(),
                "thresholds_km": {"excellent": ASSUME["excellent_km"], "moderate": ASSUME["moderate_km"]},
                "assumptions": ASSUME,
                "note": "Study area = cells within 6 km of a station or listed destination. Classes depend only on straight-line distance to the nearest station: no population, employment or demand data is used."}

    def underserved_wards(self, n=12):
        """Wards (Census 2011) whose centroid is more than 2.5 km from any operational station, by population."""
        out = []
        if self.ctx is None:
            return out
        for g, pr in zip(self.ctx.geoms, self.ctx.props):
            c = g.representative_point(); p = np.array(self.xy(c.y, c.x)); d = float(np.sqrt(((self.sxy - p) ** 2).sum(1)).min())
            out.append({"ward": pr["name"], "no": pr["no"], "constituency": pr["ac"], "pop_2011": pr["pop"], "density": pr["density"], "dist_km": round(d, 2), "lat": c.y, "lon": c.x})
        far = [w for w in out if w["dist_km"] > ASSUME["moderate_km"]]
        return sorted(far, key=lambda w: -w["pop_2011"])[:n]

    def anchor_status(self, extra_xy=None):
        out = []
        for a, p in zip(self.anchors, self.axy):
            d = np.sqrt(((self.sxy - p) ** 2).sum(1)); k = int(d.argmin())
            out.append({**a, "nearest_station": self.ids[k], "nearest_name": self.net.stations[self.ids[k]]["name"], "dist_km": round(float(d[k]), 3),
                        "status": "excellent" if d[k] <= 1 else "moderate" if d[k] <= 2.5 else "poor"})
        return out

    # ---------- graph metrics on a (possibly extended) network ----------
    def acc_time(self, d):
        return min(d, ASSUME["walk_limit_km"]) / ASSUME["walk_kmh"] * 60 + max(d - ASSUME["walk_limit_km"], 0) / ASSUME["feeder_kmh"] * 60

    def pair_times(self, adj_min, node_ids, node_xy):
        """Mean destination-to-destination door-to-door time: min(direct road, access + metro + access)."""
        near = []
        for p in self.axy:
            d = np.sqrt(((node_xy - p) ** 2).sum(1)); n0 = len(self.ids)
            idx = set(np.argsort(d)[:3].tolist()) | set(np.argsort(d[:n0])[:3].tolist())   # existing options always kept -> adding stations never slows a trip
            near.append([(node_ids[i], float(d[i])) for i in sorted(idx)])
        cache = {}
        def D(s):
            if s not in cache:
                cache[s] = A.dijkstra(adj_min, [s])[0]
            return cache[s]
        n = len(self.anchors); M = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                road = float(np.hypot(*(self.axy[i] - self.axy[j]))) / ASSUME["road_kmh"] * 60
                best = road
                for sa, da in near[i]:
                    Ds = D(sa)
                    for sb, db in near[j]:
                        t = Ds[sb]
                        if t < A.INF:
                            best = min(best, self.acc_time(da) + t + self.acc_time(db))
                M[i, j] = M[j, i] = best
        return M

    def graph_stats(self, adj_km):
        n = len(adj_km); m = sum(len(v) for v in adj_km.values()) // 2; comps = A.components(adj_km)
        return {"stations": n, "edges": m, "track_km": sum(w for u in adj_km for w in adj_km[u].values()) / 2, "components": len(comps),
                "articulation_points": len(A.articulation_points(adj_km)), "is_tree": m == n - len(comps), "avg_hops": A.avg_shortest_path_hops(adj_km)}

    def baseline(self):
        if self.base is None:
            n = self.net
            self.base = {"stats": self.graph_stats(n.adj_km), "pairs": self.pair_times(n.adj_min, self.ids, self.sxy),
                         "bc": A.betweenness(n.adj_km), "cc": A.closeness(n.adj_km)}
        return self.base

    # ---------- corridors ----------
    def _norm_corridor(self, c, idx=0):
        """Validate and fill a corridor dict: stations [{id|None, lat, lon, name}], seg_geoms."""
        sts = c.get("stations") or []
        if len(sts) < 2:
            raise NodalError("a corridor needs at least 2 stations")
        out = []
        for s in sts:
            if s.get("id"):
                if s["id"] not in self.net.stations:
                    raise NodalError(f"unknown existing station {s['id']!r}")
                e = self.net.stations[s["id"]]; out.append({"id": s["id"], "lat": e["lat"], "lon": e["lon"], "name": e["name"], "new": False})
            else:
                if s.get("lat") is None or s.get("lon") is None:
                    raise NodalError("proposed stations need lat and lon")
                if not (12.5 <= s["lat"] <= 13.5 and 77.2 <= s["lon"] <= 78.0):
                    raise NodalError("proposed station outside the Bengaluru study region")
                out.append({"id": None, "lat": float(s["lat"]), "lon": float(s["lon"]), "name": s.get("name") or f"Proposed station {len(out) + 1}", "new": True})
        if not any(not s["new"] for s in out) or not any(s["new"] for s in out):
            raise NodalError("a corridor must connect to at least one existing station and include at least one proposed station")
        for a, b in zip(out, out[1:]):
            if haversine(a["lat"], a["lon"], b["lat"], b["lon"]) < 0.1 and not (a["id"] and b["id"] == a["id"]):
                raise NodalError("consecutive stations are less than 100 m apart")
            if a["id"] and b["id"] and a["id"] == b["id"]:
                raise NodalError("consecutive stations are identical")
        sg = c.get("seg_geoms")
        if not sg or len(sg) != len(out) - 1:
            sg = [[[a["lon"], a["lat"]], [b["lon"], b["lat"]]] for a, b in zip(out, out[1:])]
        return {"id": c.get("id") or f"C{idx + 1}", "name": c.get("name") or "Hypothetical corridor", "stations": out, "seg_geoms": sg,
                "kind": c.get("kind", "custom"), "target": c.get("target"), "alignment": c.get("alignment") or "User-drawn straight segments between stations"}

    def apply(self, corridors):
        """Clone the network and add corridors. The original graph is never touched."""
        n = self.net
        adj_km, adj_min = copy.deepcopy(n.adj_km), copy.deepcopy(n.adj_min)
        ids, xy, names, new_ids, length = list(self.ids), [tuple(r) for r in self.sxy], {i: s["name"] for i, s in n.stations.items()}, [], 0.0
        for ci, c in enumerate(corridors):
            nodes = []
            for k, s in enumerate(c["stations"]):
                if s["id"]:
                    nodes.append(s["id"]); continue
                nid = f"NEW-{ci + 1}-{k + 1}"; adj_km[nid] = {}; adj_min[nid] = {}; ids.append(nid); xy.append(self.xy(s["lat"], s["lon"])); names[nid] = s["name"]; new_ids.append(nid); nodes.append(nid)
            for k in range(len(nodes) - 1):
                u, v = nodes[k], nodes[k + 1]
                if v in adj_km[u]:
                    raise NodalError("stations are already directly connected")
                km = seg_len(c["seg_geoms"][k]); length += km
                adj_km[u][v] = adj_km[v][u] = km; adj_min[u][v] = adj_min[v][u] = km / self.avg_kmh * 60
        return {"adj_km": adj_km, "adj_min": adj_min, "ids": ids, "xy": np.array(xy), "names": names, "new_ids": new_ids, "length_km": length}

    def evaluate(self, corridors, cost_per_km=ASSUME["default_cost_per_km"], full=True):
        cs = [self._norm_corridor(c, i) for i, c in enumerate(corridors)]
        g = self.apply(cs); b = self.baseline()
        new_xy = np.array([self.xy(s["lat"], s["lon"]) for c in cs for s in c["stations"] if s["new"]])
        d1 = np.minimum(self.d0, self._dist(self.cxy, new_xy)); cls1 = self._cls(d1)
        steps = np.maximum(self.cls0 - cls1, 0)
        gain = float((steps * self.pop).sum()) if self.pop_known.any() else float(steps.sum())
        pplb = {k: int(self.pop[self.cls0 == i].sum()) for i, k in enumerate(['excellent', 'moderate', 'poor'])}; ppla = {k: int(self.pop[cls1 == i].sum()) for i, k in enumerate(['excellent', 'moderate', 'poor'])}
        people_improved = int(self.pop[cls1 < self.cls0].sum())
        # anchors
        a0 = np.array([np.sqrt(((self.sxy - p) ** 2).sum(1)).min() for p in self.axy])
        a1 = np.array([min(a0[i], np.sqrt(((new_xy - p) ** 2).sum(1)).min()) for i, p in enumerate(self.axy)])
        prox = lambda d: np.clip(1 - d / ASSUME["proximity_decay_km"], 0, 1)
        imp = np.array([a["importance"] for a in self.anchors])
        dest_gain = float((imp * (prox(a1) - prox(a0))).sum())
        M1 = self.pair_times(g["adj_min"], g["ids"], g["xy"]); M0 = b["pairs"]; iu = np.triu_indices(len(self.anchors), 1)
        t0, t1 = float(M0[iu].mean()), float(M1[iu].mean())
        st1 = self.graph_stats(g["adj_km"])
        attach = [s["id"] for c in cs for s in c["stations"] if s["id"]]
        integ = float(np.mean([1.0 if len(self.net.adj_km[i]) == 1 else 0.6 for i in attach]))
        detours = []
        for c in cs:
            pl_len = sum(seg_len(x) for x in c["seg_geoms"]); st = c["stations"]
            ex = [k for k, s in enumerate(st) if not s["new"]]
            if len(ex) >= 2 and ex[0] != ex[-1]:   # loop: via-point
                mid = next((k for k, s in enumerate(st) if s["new"]), 1); chord = haversine(st[ex[0]]["lat"], st[ex[0]]["lon"], st[-1]["lat"], st[-1]["lon"])
                far = max(st, key=lambda s: haversine(st[0]["lat"], st[0]["lon"], s["lat"], s["lon"]))
                chord = haversine(st[0]["lat"], st[0]["lon"], far["lat"], far["lon"]) + haversine(far["lat"], far["lon"], st[-1]["lat"], st[-1]["lon"])
            else:
                chord = haversine(st[0]["lat"], st[0]["lon"], st[-1]["lat"], st[-1]["lon"])
            detours.append(pl_len / max(chord, 1e-6))
        raw = {"coverage": gain, "destinations": dest_gain, "connectivity": (t0 - t1) / t0 if t0 else 0.0, "interchange": len(set(attach)),
               "cost": g["length_km"] * cost_per_km, "integration": integ, "feasibility": 1 / float(np.mean(detours)), "environment": None}
        res = {"corridors": [{"id": c["id"], "name": c["name"], "kind": c["kind"], "target": c["target"], "alignment": c["alignment"], "stations": c["stations"], "seg_geoms": c["seg_geoms"]} for c in cs],
               "length_km": g["length_km"], "cost_cr": g["length_km"] * cost_per_km, "cost_per_km": cost_per_km, "new_stations": len(g["new_ids"]),
               "attach": [{"id": i, "name": self.net.stations[i]["name"], "degree": len(self.net.adj_km[i]), "lines": self.net.stations[i]["lines"]} for i in dict.fromkeys(attach)],
               "criteria_raw": raw, "detour": float(np.mean(detours)),
               "before": {**b["stats"], "mean_pair_min": t0, "cells": {k: int((self.cls0 == i).sum()) for i, k in enumerate(["excellent", "moderate", "poor"])}, "people": pplb},
               "after": {**st1, "mean_pair_min": t1, "cells": {k: int((cls1 == i).sum()) for i, k in enumerate(["excellent", "moderate", "poor"])}, "people": ppla},
               "cells_improved": int((cls1 < self.cls0).sum()), "people_improved": people_improved,
               "anchors_newly_served": [self.anchors[i]["name"] for i in range(len(a0)) if a0[i] > 1.0 >= a1[i]],
               "anchors_benefiting": [{"name": self.anchors[i]["name"], "before_km": round(float(a0[i]), 2), "after_km": round(float(a1[i]), 2)} for i in range(len(a0)) if a1[i] < a0[i] - 1e-9],
               "assumptions": ASSUME}
        if full:
            res["anchor_times"] = [{"name": a["name"], "before_min": round(float(M0[i][np.arange(len(M0)) != i].mean()), 2), "after_min": round(float(M1[i][np.arange(len(M1)) != i].mean()), 2)} for i, a in enumerate(self.anchors)]
            bc1, cc1 = A.betweenness(g["adj_km"]), A.closeness(g["adj_km"])
            rows = [{"id": i, "name": g["names"][i], "bc_before": b["bc"].get(i), "bc_after": bc1[i], "cc_before": b["cc"].get(i), "cc_after": cc1[i], "new": i in g["new_ids"]} for i in g["adj_km"]]
            res["centrality"] = sorted(rows, key=lambda r: -abs((r["bc_after"] or 0) - (r["bc_before"] or 0)))[:12]
            res["new_station_ids"] = g["new_ids"]
            imp_cells = np.where(cls1 < self.cls0)[0]
            res["improved_cells"] = [{"lat": round(float(self.clat[i]), 5), "lon": round(float(self.clon[i]), 5), "from": int(self.cls0[i]), "to": int(cls1[i])} for i in imp_cells]
        return res

    # ---------- generation ----------
    def _adjacency(self, kappa):
        if kappa not in self._adj:
            self._adj[kappa] = {u: {v: l * max(0.25, 1 - kappa * (self.val[u] + self.val[v]) / 2) for v, l in nb} for u, nb in enumerate(self.nbr)}
        return self._adj[kappa]

    def _node(self, lat, lon):
        p = np.array(self.xy(lat, lon)); return int(np.sqrt(((self.cxy - p) ** 2).sum(1)).argmin())

    def _simplify(self, pts, tol=0.35):
        if len(pts) < 3:
            return pts
        a, b = np.array(pts[0]), np.array(pts[-1]); ab = b - a; L = np.hypot(*ab) or 1e-9
        d = [abs(ab[0] * (p[1] - a[1]) - ab[1] * (p[0] - a[0])) / L for p in pts[1:-1]]
        k = int(np.argmax(d))
        if d[k] > tol:
            return self._simplify(pts[:k + 2], tol)[:-1] + self._simplify(pts[k + 1:], tol)
        return [pts[0], pts[-1]]

    def _val_at(self, x, y):
        r, c = int(round((y - self.y0) / self.step)), int(round((x - self.x0) / self.step))
        return float(self.val2d[r, c]) if 0 <= r < self.ny and 0 <= c < self.nx else 0.0

    def _road_adj(self, kappa):
        """Graph of existing BMTC bus corridors (consecutive stops of real routes) used as a proxy for the road network."""
        if kappa not in self._radj:
            C = self.ctx; self.rxy = np.stack([C.slon * self.KX, C.slat * self.KY], 1)
            adj = {i: {} for i in range(len(C.stops))}
            for (a, b), val in C.bus_edges().items():
                km = val[0]
                v = self._val_at((self.rxy[a, 0] + self.rxy[b, 0]) / 2, (self.rxy[a, 1] + self.rxy[b, 1]) / 2)
                w = km * max(0.25, 1 - kappa * v); adj[a][b] = w; adj[b][a] = w
            self._radj[kappa] = adj
        return self._radj[kappa]

    def _road_leg(self, a_ll, b_ll, kappa):
        if self.ctx is None:
            return None
        adj = self._road_adj(kappa)
        def near(ll):
            p = np.array(self.xy(*ll)); d = np.sqrt(((self.rxy - p) ** 2).sum(1)); idx = np.argsort(d)[:4]
            return [(int(i), float(d[i])) for i in idx if d[i] <= 1.2]
        sa, sb = near(a_ll), near(b_ll)
        if not sa or not sb:
            return None
        adj["S"] = {i: d for i, d in sa}; adj["T"] = {i: d for i, d in sb}
        for i, d in sa:
            adj[i]["S"] = d
        for i, d in sb:
            adj[i]["T"] = d
        try:
            dist, prev, _ = A.dijkstra(adj, ["S"], target="T")
        finally:
            for i, _ in sa:
                adj[i].pop("S", None)
            for i, _ in sb:
                adj[i].pop("T", None)
            adj.pop("S", None); adj.pop("T", None)
        if dist["T"] == A.INF:
            return None
        stops = A.path_to(prev, "T")[1:-1]
        xy = [self.xy(*a_ll)] + [tuple(self.rxy[i]) for i in stops] + [self.xy(*b_ll)]
        L = sum(math.hypot(xy[i + 1][0] - xy[i][0], xy[i + 1][1] - xy[i][1]) for i in range(len(xy) - 1)); chord = math.hypot(xy[-1][0] - xy[0][0], xy[-1][1] - xy[0][1])
        if L > 1.6 * chord + 0.6:
            return None                                          # the bus corridors make too big a detour: fall back
        return [[x / self.KX, y / self.KY] for x, y in self._simplify(xy, 0.12)]

    def _leg(self, a_ll, b_ll, kappa):
        """Alignment between two (lat, lon) points: along existing bus corridors when possible, else a least-cost lattice path.
        Returns (polyline [[lon, lat], ...], kind)."""
        road = self._road_leg(a_ll, b_ll, kappa)
        if road:
            return road, "road"
        return self._lattice_leg(a_ll, b_ll, kappa), "schematic"

    def _lattice_leg(self, a_ll, b_ll, kappa):
        """Least-cost lattice path between two (lat, lon) points; cost = length × (1 − κ·value)."""
        s, t = self._node(*a_ll), self._node(*b_ll)
        if s == t:
            return [[a_ll[1], a_ll[0]], [b_ll[1], b_ll[0]]]
        dist, prev, _ = A.dijkstra(self._adjacency(kappa), [s], target=t)
        if dist[t] == A.INF:
            return [[a_ll[1], a_ll[0]], [b_ll[1], b_ll[0]]]
        path = A.path_to(prev, t)
        xy = [self.xy(a_ll[0], a_ll[1])] + [tuple(self.cxy[i]) for i in path[1:-1]] + [self.xy(b_ll[0], b_ll[1])]
        return [[x / self.KX, y / self.KY] for x, y in self._simplify(xy)]

    @staticmethod
    def _cum(pl):
        c = [0.0]
        for i in range(1, len(pl)):
            c.append(c[-1] + haversine(pl[i - 1][1], pl[i - 1][0], pl[i][1], pl[i][0]))
        return c

    def _project(self, pl, cum, ll):
        p = np.array(self.xy(ll[0], ll[1])); best = (1e9, 0.0)
        for i in range(len(pl) - 1):
            a, b = np.array(self.xy(pl[i][1], pl[i][0])), np.array(self.xy(pl[i + 1][1], pl[i + 1][0])); ab = b - a; L2 = float(ab @ ab) or 1e-12
            t = min(1, max(0, float((p - a) @ ab) / L2)); d = float(np.hypot(*(p - (a + t * ab))))
            if d < best[0]:
                best = (d, cum[i] + t * (cum[i + 1] - cum[i]))
        return best

    def _cut(self, pl, cum, dists):
        """Insert vertices at the given distances; returns (new polyline, index of each distance)."""
        ev = [(cum[i], pl[i], False) for i in range(len(pl))] + [(d, None, True) for d in dists]
        ev.sort(key=lambda e: (e[0], e[2])); out, idx, li = [], {}, 0
        def point(d):
            j = max(0, min(len(pl) - 2, int(np.searchsorted(cum, d, side="right")) - 1)); t = (d - cum[j]) / ((cum[j + 1] - cum[j]) or 1)
            return [pl[j][0] + t * (pl[j + 1][0] - pl[j][0]), pl[j][1] + t * (pl[j + 1][1] - pl[j][1])]
        res, where = [], {}
        for d, p, ins in ev:
            if ins:
                pt = point(d)
                if res and haversine(res[-1][1], res[-1][0], pt[1], pt[0]) < 1e-4:
                    where[d] = len(res) - 1
                else:
                    res.append(pt); where[d] = len(res) - 1
            else:
                if res and haversine(res[-1][1], res[-1][0], p[1], p[0]) < 1e-4:
                    continue
                res.append(p)
        return res, where

    def _place(self, pl, n_new, max_spacing, include_end):
        """Return station distances along pl: n evenly spaced stations (+ end), nudged onto nearby destinations."""
        cum = self._cum(pl); L = cum[-1]
        n = n_new if n_new else max(1, math.ceil(L / max_spacing))
        ds = [L * (i + 1) / n for i in range(n)]
        if not include_end:
            ds = ds[:-1]
        used = {}
        for a in self.anchors:
            dd, along = self._project(pl, cum, (a["lat"], a["lon"]))
            if dd <= 0.5 and 0.3 < along < L - 0.3:
                k = min(range(len(ds)), key=lambda i: abs(ds[i] - along)) if ds else None
                if k is not None and k not in used and abs(ds[k] - along) < max_spacing / 2:
                    lo = ds[k - 1] if k > 0 else 0; hi = ds[k + 1] if k + 1 < len(ds) else L
                    if along - lo >= 0.5 and hi - along >= 0.5:
                        ds[k] = along; used[k] = a["name"]
        return ds, used, cum

    def build_corridor(self, attach_ids, target, kappa, max_spacing, n_stations, kind="extension"):
        T = target; t_ll = (T["lat"], T["lon"]); legs = []
        s1 = self.net.stations[attach_ids[0]]
        legs.append(self._leg((s1["lat"], s1["lon"]), t_ll, kappa))
        if len(attach_ids) == 2:
            s2 = self.net.stations[attach_ids[1]]; legs.append(self._leg(t_ll, (s2["lat"], s2["lon"]), kappa))
        kinds = {k for _, k in legs}; legs = [pl for pl, _ in legs]
        stations = [{"id": attach_ids[0], "lat": s1["lat"], "lon": s1["lon"], "name": s1["name"], "new": False}]
        geoms, k = [], 0
        per = max(1, round(n_stations / len(legs))) if n_stations else 0
        for li, pl in enumerate(legs):
            last = li == len(legs) - 1
            ds, used, cum = self._place(pl, per, max_spacing, include_end=True)
            if last and kind == "loop":
                ds = ds[:-1]
            full, where = self._cut(pl, cum, ds)
            prev = 0; pos = sorted(where.items())
            for d, vi in pos:
                k += 1; p = full[vi]
                nm = used.get(ds.index(d)) if d in ds and ds.index(d) in used else (T["name"] if (not last or kind == "extension") and d == ds[-1] and li == 0 and kind == "extension" else None)
                if li == 0 and kind == "loop" and d == ds[-1]:
                    nm = T["name"]
                st = {"id": None, "lat": p[1], "lon": p[0], "name": f"Proposed: {nm}" if nm else f"Proposed station {k}", "new": True}
                stations.append(st); geoms.append(full[prev:vi + 1]); prev = vi
            if last and kind == "loop":
                s2 = self.net.stations[attach_ids[1]]; geoms.append(full[prev:]); stations.append({"id": attach_ids[1], "lat": s2["lat"], "lon": s2["lon"], "name": s2["name"], "new": False})
        if kind == "loop" and stations[-1]["id"] is None:
            return None
        name = f"{('Loop' if kind == 'loop' else 'Extension')}: {short(s1['name'])} → {T['name']}" + (f" → {short(self.net.stations[attach_ids[1]]['name'])}" if kind == "loop" else "")
        return {"id": f"G{uuid.uuid4().hex[:6]}", "name": name, "kind": kind, "target": T["name"], "kappa": kappa, "stations": stations, "seg_geoms": geoms,
                "alignment": "Follows existing BMTC bus corridors (stop chain as a road proxy)" if kinds == {"road"} else "Schematic least-cost path (no suitable road corridor found)" if kinds == {"schematic"} else "Partly along bus corridors, partly schematic"}

    def pool(self, targets=None, kinds=None, max_spacing=1.6, n_stations=0, cost_per_km=300.0, min_distance=1.2):
        key = (tuple(sorted(targets or [])), tuple(sorted(kinds or [])), round(max_spacing, 2), n_stations, round(cost_per_km, 1), min_distance)
        if key in self.cache:
            return self.cache[key]
        stat = {a["id"]: a for a in self.anchor_status()}
        T = [stat[a] for a in stat if (not targets or a in targets or stat[a]["name"] in targets) and (not kinds or stat[a]["kind"] in kinds) and stat[a]["dist_km"] >= min_distance]
        out = []
        for t in T:
            tp = np.array(self.xy(t["lat"], t["lon"])); d = np.sqrt(((self.sxy - tp) ** 2).sum(1)); order = list(np.argsort(d))
            cand = [self.ids[i] for i in order[:2]]
            terminals = [self.ids[i] for i in order if len(self.net.adj_km[self.ids[i]]) == 1 and d[i] <= 2.2 * d[order[0]] + 2]
            hubs = [self.ids[i] for i in order if len(self.net.stations[self.ids[i]]["lines"]) > 1 and d[i] <= 2.2 * d[order[0]] + 2]
            for x in terminals[:1] + hubs[:1]:
                if x not in cand:
                    cand.append(x)
            for att in cand:
                for kappa in (0.0, 0.35, 0.65):
                    c = self.build_corridor([att], t, kappa, max_spacing, n_stations)
                    if c:
                        out.append(c)
            far = [self.ids[i] for i in order[2:] if self.net.adj_km[self.ids[i]] and self.net.stations[self.ids[i]]["lines"] != self.net.stations[cand[0]]["lines"]]
            for att2 in far[:1]:
                c = self.build_corridor([cand[0], att2], t, 0.35, max_spacing, n_stations, kind="loop")
                if c:
                    out.append(c)
        seen, pool = set(), []
        for c in out:
            sig = (c["stations"][0]["id"], c["target"], c["kind"], tuple((round(s["lat"], 3), round(s["lon"], 3)) for s in c["stations"]))
            if sig in seen:
                continue
            seen.add(sig)
            try:
                ev = self.evaluate([c], cost_per_km, full=False)
            except NodalError:
                continue
            pool.append({**{k: c[k] for k in ("id", "name", "kind", "target", "kappa", "alignment")}, "stations": ev["corridors"][0]["stations"], "seg_geoms": c["seg_geoms"],
                         "length_km": ev["length_km"], "cost_cr": ev["cost_cr"], "new_stations": ev["new_stations"], "raw": ev["criteria_raw"], "detour": ev["detour"],
                         "cells_improved": ev["cells_improved"], "people_improved": ev["people_improved"], "anchors_newly_served": ev["anchors_newly_served"], "anchors_benefiting": ev["anchors_benefiting"],
                         "attach": ev["attach"], "before": ev["before"], "after": ev["after"]})
        self.cache[key] = pool
        return pool

    def rank(self, pool, weights, budget_cr=None):
        w = {c: float(weights.get(c, 0)) for c in CRITERIA}; w["environment"] = 0.0
        feas = [p for p in pool if budget_cr is None or p["cost_cr"] <= budget_cr]
        if not feas:
            return []
        norm = {}
        for c in CRITERIA:
            if c == "environment":
                continue
            vals = [p["raw"][c] for p in feas]; lo, hi = min(vals), max(vals)
            norm[c] = [((v - lo) / (hi - lo) if hi > lo else 0.0) for v in vals]
            if c == "cost":
                norm[c] = [1 - x for x in norm[c]] if hi > lo else [0.0] * len(vals)
        tw = sum(w.values()) or 1.0; out = []
        for i, p in enumerate(feas):
            contrib = {c: w[c] / tw * norm[c][i] for c in norm}
            out.append({**p, "score": sum(contrib.values()), "contrib": contrib, "norm": {c: norm[c][i] for c in norm}})
        out.sort(key=lambda r: -r["score"])
        return out

    def explain(self, p, weights):
        top = sorted(p["contrib"].items(), key=lambda kv: -kv[1])[:3]
        lab = {"coverage": "area coverage gain", "destinations": "destination proximity", "connectivity": "travel-time reduction", "interchange": "interchange links", "cost": "low cost", "integration": "ease of integration", "feasibility": "alignment directness"}
        return (f"Highest weighted contributions: " + ", ".join(f"{lab[c]} ({v:.2f})" for c, v in top) +
                f". Weighted-sum score {p['score']:.3f} over criteria with weight > 0 (min-max normalised across {len(self.cache) and 'the candidate pool'}). "
                "Environmental constraints and terrain were not evaluated (no data).")

    def compose(self, pool, weights, budget_cr, max_corridors=3):
        ranked, chosen, used, spent = self.rank(pool, weights, budget_cr), [], set(), 0.0
        for p in ranked:
            if len(chosen) >= max_corridors:
                break
            if p["target"] in used or spent + p["cost_cr"] > budget_cr:
                continue
            chosen.append(p); used.add(p["target"]); spent += p["cost_cr"]
        return chosen

    # ---------- scenarios ----------
    def generate_scenarios(self, budget_cr=8000.0, max_spacing=1.6, n_stations=0, cost_per_km=300.0, presets=("A", "B", "C", "IT")):
        out = []
        for k in presets:
            P = PRESETS[k]; pl = self.pool(kinds=P.get("kinds"), max_spacing=max_spacing, n_stations=n_stations, cost_per_km=cost_per_km)
            ch = self.compose(pl, P["weights"], budget_cr)
            if not ch:
                out.append({"key": k, "name": P["name"], "weights": P["weights"], "corridors": [], "note": "No candidate fits the budget"}); continue
            ev = self.evaluate([{k2: c[k2] for k2 in ("id", "name", "kind", "target", "stations", "seg_geoms", "alignment")} for c in ch], cost_per_km)
            out.append({"key": k, "name": P["name"], "weights": P["weights"], "budget_cr": budget_cr, "corridors": [{"name": c["name"], "score": c["score"], "explain": self.explain(c, P["weights"])} for c in ch], "eval": ev})
        return out

    def _load_scenarios(self):
        try:
            self.scenarios = json.load(open(SCEN_PATH))
        except Exception:
            self.scenarios = {}

    def save_scenario(self, name, kind, corridors, cost_per_km, notes=""):
        ev = self.evaluate(corridors, cost_per_km)
        sid = uuid.uuid4().hex[:8]
        self.scenarios[sid] = {"id": sid, "name": name, "kind": kind, "notes": notes, "hypothetical": True, "cost_per_km": cost_per_km,
                               "corridors": ev["corridors"], "summary": {k: ev[k] for k in ("length_km", "cost_cr", "new_stations")} | {"before": ev["before"], "after": ev["after"]}}
        try:
            json.dump(self.scenarios, open(SCEN_PATH, "w"), indent=1)
        except OSError:
            pass
        return self.scenarios[sid], ev

    def delete_scenario(self, sid):
        if sid not in self.scenarios:
            raise NodalError("unknown scenario")
        del self.scenarios[sid]
        try:
            json.dump(self.scenarios, open(SCEN_PATH, "w"), indent=1)
        except OSError:
            pass


def short(n):
    p = n.split(", "); return p[-1] if len(p) > 1 else n
