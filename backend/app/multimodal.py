"""Multimodal (walk + BMTC bus + Namma Metro) journey planner on real stop/station data.
REAL: station and bus-stop coordinates, bus stop sequences, timetable-derived headways, metro run times and metro token fares (BMRCL feed).
ASSUMED (all listed in ASSUME and returned with every result): walking speed/circuity, bus running speed, bus tariff, metro waiting time.
Walking connections are straight-line assumptions (not surveyed footpaths)."""
import json
import numpy as np
from scipy.spatial import cKDTree
from . import algorithms as A
from .context import PROC
from .data import TRANSFER_MIN
from .services import NodalError, ekey

ASSUME = {"walk_kmh": 4.5, "walk_circuity": 1.25, "bus_kmh": 15.0, "bus_board_fare_inr": 10.0, "bus_fare_per_km_inr": 1.0, "metro_wait_min": 3.0,
          "max_bus_wait_min": 25.0, "transfer_penalty_min": 30.0, "station_exit_min": 5.0, "value_of_time_inr_per_min": 0.5, "stop_to_stop_walk_km": 0.25, "stop_to_station_walk_km": 0.7, "access_radius_km": 1.5, "access_candidates": 8}
OBJECTIVES = ("time", "cost", "transfers", "distance")
NOTES = {"objectives": "time = minutes; cost = fare + time valued at ₹0.5/min (assumption); transfers = each boarding costs a 30 min-equivalent penalty, then time; distance = total km", "bus_fare": "PLACEHOLDER bus tariff (not the BMTC fare table): flat boarding fare + per-km rate, editable in code/UI",
         "walk": "straight-line walking links are assumptions, not surveyed footpaths", "bus_time": "bus running time = km / assumed speed; waits come from timetable headways (source app has known inaccuracies)",
         "metro": "metro run times from the BMRCL feed (modeled timetable) + 5 min per line change + assumed platform wait; metro fares are the feed's token fares (peak)"}


def bmrcl_fare_by_km(km: float) -> float:
    """Official BMRCL distance-based fare chart in INR (token fare)."""
    if km <= 2.0: return 10.0
    elif km <= 4.0: return 15.0
    elif km <= 6.0: return 20.0
    elif km <= 8.0: return 25.0
    elif km <= 10.0: return 30.0
    elif km <= 12.0: return 35.0
    elif km <= 15.0: return 40.0
    elif km <= 18.0: return 45.0
    elif km <= 21.0: return 50.0
    elif km <= 24.0: return 55.0
    elif km <= 27.0: return 60.0
    elif km <= 30.0: return 65.0
    elif km <= 35.0: return 70.0
    elif km <= 40.0: return 80.0
    else: return 90.0


class Multimodal:
    def __init__(self, net, ctx, kx, ky, params=None):
        self.net, self.ctx, self.kx, self.ky = net, ctx, kx, ky
        self.A = {**ASSUME, **(params or {})}
        self.fares = json.load(open(PROC / "metro_fares.json"))["fares"]
        self._metro_pairs(); self._build()

    def _metro_pairs(self):
        n = self.net; self.mp = {}
        for s in n.ids:
            dist, prev, _ = A.dijkstra(n.adj_min, [s])
            for t in n.ids:
                if t == s:
                    continue
                path = A.path_to(prev, t); km, xf, last = 0.0, 0, None
                for a, b in zip(path, path[1:]):
                    km += n.adj_km[a][b]; ln = n.edge_by_pair[ekey(a, b)]["line"]
                    if last and ln != last:
                        xf += 1
                    last = ln
                fare = self.fares.get(f"{s}|{t}")
                if fare is None or fare <= 0:
                    fare = bmrcl_fare_by_km(km)
                self.mp[(s, t)] = (dist[t] + xf * TRANSFER_MIN, km, xf, fare)

    def xy(self, lat, lon):
        return (lon * self.kx, lat * self.ky)

    def _build(self):
        C, a = self.ctx, self.A
        wait = C.stop_wait(); self.served = np.where(~np.isnan(wait))[0]; self.wait = wait
        self.nodes, pos = [], []
        for i in self.served:
            self.nodes.append(f"f:B{i}"); pos.append(self.xy(C.slat[i], C.slon[i]))
        for sid in self.net.ids:
            st = self.net.stations[sid]; self.nodes.append(f"f:M{sid}"); pos.append(self.xy(st["lat"], st["lon"]))
        self.pos = np.array(pos); self.tree = cKDTree(self.pos); E = []
        wk = lambda d: (d * a["walk_circuity"], d * a["walk_circuity"] / a["walk_kmh"] * 60)
        nb = len(self.served)
        for i, j in self.tree.query_pairs(a["stop_to_station_walk_km"]):
            bi, bj = i < nb, j < nb; d = float(np.hypot(*(self.pos[i] - self.pos[j])))
            if bi and bj and d > a["stop_to_stop_walk_km"]:
                continue
            if not bi and not bj:
                continue                                    # no station-to-station walking
            dd, t = wk(d)
            for u, v in ((i, j), (j, i)):                    # stops <-> stations; stations are entered via f:M and left via x:M
                un, vn = self.nodes[u], self.nodes[v]
                if u >= nb:
                    un = un.replace("f:M", "x:M")
                E.append((un, vn, "walk", t + (a["station_exit_min"] if un.startswith("x:") else 0.0), 0.0, dd, 0, None))
        for i in self.served:
            w = min(a["max_bus_wait_min"], float(wait[i]))
            E.append((f"f:B{i}", f"b:{i}", "board", w, a["bus_board_fare_inr"], 0.0, 1, None)); E.append((f"b:{i}", f"f:B{i}", "alight", 0.0, 0.0, 0.0, 0, None))
        sv = set(self.served.tolist())
        for (p, q), edata in C.bus_edges().items():
            km, hw, nr = edata[:3]
            r_names = edata[3] if len(edata) > 3 else []
            if p in sv and q in sv:
                t = km / a["bus_kmh"] * 60; c = km * a["bus_fare_per_km_inr"]
                E.append((f"b:{p}", f"b:{q}", "ride", t, c, km, 0, r_names))
                E.append((f"b:{q}", f"b:{p}", "ride", t, c, km, 0, r_names))
        for (s, t_), (tm, km, xf, fare) in self.mp.items():
            f_val = fare if (fare is not None and fare > 0) else bmrcl_fare_by_km(km)
            E.append((f"f:M{s}", f"x:M{t_}", "metro", a["metro_wait_min"] + tm, f_val, km, 1, (s, t_)))
        self.edges = E; self.emap = {(e[0], e[1]): e for e in E}

    def _scalar(self, objective):
        return {"time": lambda e: e[3], "cost": lambda e: e[4] + self.A["value_of_time_inr_per_min"] * e[3], "transfers": lambda e: self.A["transfer_penalty_min"] * e[6] + e[3], "distance": lambda e: e[5] + 0.001 * e[3]}[objective]

    def _near(self, lat, lon):
        p = np.array(self.xy(lat, lon)); d, idx = self.tree.query(p, k=min(self.A["access_candidates"], len(self.pos)))
        return [(int(i), float(x)) for x, i in zip(np.atleast_1d(d), np.atleast_1d(idx)) if x <= self.A["access_radius_km"]], p

    def route(self, o, d, objective="time", bus=True, metro=True):
        if objective not in OBJECTIVES:
            raise NodalError(f"objective must be one of {OBJECTIVES}")
        a = self.A; sc = self._scalar(objective); adj = {}
        def add(u, v, w):
            adj.setdefault(u, {})[v] = w; adj.setdefault(v, {})
        for e in self.edges:
            if (not bus and e[2] in ("board", "ride", "alight")) or (not metro and e[2] == "metro"):
                continue
            add(e[0], e[1], sc(e))
        no, po = self._near(*o); nd, pd = self._near(*d)
        if not no or not nd:
            raise NodalError("origin or destination is more than 1.5 km from any bus stop or metro station")
        extra = {}
        def link(u, v, dist):
            dd = dist * a["walk_circuity"]; t = dd / a["walk_kmh"] * 60 + (a["station_exit_min"] if u.startswith("x:") else 0.0); e = (u, v, "walk", t, 0.0, dd, 0, None); extra[(u, v)] = e; add(u, v, sc(e))
        for i, dist in no:
            link("S", self.nodes[i], dist)
        for i, dist in nd:
            link(self.nodes[i].replace("f:M", "x:M"), "T", dist)
        link("S", "T", float(np.hypot(*(po - pd))))
        dist, prev, _ = A.dijkstra(adj, ["S"], target="T")
        if dist["T"] == A.INF:
            raise NodalError("no route found")
        path = A.path_to(prev, "T")
        edges = [extra.get((u, v)) or self.emap[(u, v)] for u, v in zip(path, path[1:])]
        return self._legs(o, d, edges, objective)

    def _name(self, node):
        if node == "S" or node == "T":
            return None
        k, rest = node.split(":", 1)
        if rest[0] == "M":
            return self.net.stations[rest[1:]]["name"]
        i = int(rest[1:]) if rest[0] == "B" else int(rest)
        return self.ctx.stops[i][0]

    def _ll(self, node, o, d):
        if node == "S":
            return {"lat": o[0], "lon": o[1]}
        if node == "T":
            return {"lat": d[0], "lon": d[1]}
        k, rest = node.split(":", 1)
        if rest[0] == "M":
            s = self.net.stations[rest[1:]]; return {"lat": s["lat"], "lon": s["lon"]}
        i = int(rest[1:]) if rest[0] == "B" else int(rest)
        return {"lat": float(self.ctx.slat[i]), "lon": float(self.ctx.slon[i])}

    def _legs(self, o, d, edges, objective):
        legs, cur = [], None
        for e in edges:
            m = "bus" if e[2] in ("board", "ride", "alight") else e[2]
            if cur is None or cur["mode"] != m or m == "metro":
                cur = {"mode": m, "minutes": 0.0, "km": 0.0, "cost_inr": 0.0, "boardings": 0, "nodes": [e[0]]}; legs.append(cur)
            cur["minutes"] += e[3]; cur["km"] += e[5]; cur["cost_inr"] += e[4]; cur["boardings"] += e[6]; cur["nodes"].append(e[1]); cur["meta"] = e[7] if m == "metro" else cur.get("meta")
        out = []
        for l in legs:
            nodes = l["nodes"]; first, last = nodes[0], nodes[-1]
            leg = {"mode": l["mode"], "minutes": round(l["minutes"], 2), "km": round(l["km"], 3), "cost_inr": round(l["cost_inr"], 2), "from": {"name": self._name(first), **self._ll(first, o, d)}, "to": {"name": self._name(last), **self._ll(last, o, d)}}
            if l["mode"] == "bus":
                stops = [n for n in nodes if n.startswith("b:")]; leg["stops"] = [{"name": self._name(n), **self._ll(n, o, d)} for n in stops]
                leg["note"] = "Stop-to-stop chain from BMTC timetables; time and fare use assumptions"
                route_counts = {}
                for u, v in zip(nodes, nodes[1:]):
                    ed = self.emap.get((u, v))
                    if ed and ed[2] == "ride" and ed[7]:
                        for r_no in ed[7]:
                            route_counts[r_no] = route_counts.get(r_no, 0) + 1
                best_routes = sorted(route_counts.keys(), key=lambda r: -route_counts[r])
                leg["bus_routes"] = best_routes[:3] if best_routes else ["BMTC"]
                if leg["cost_inr"] <= 0:
                    leg["cost_inr"] = round(max(10.0, 10.0 + (leg["km"] - 2.0) * 1.5), 2)
            elif l["mode"] == "metro":
                s, t = l["meta"]; r = self.net.route(s, t, "time"); leg["stations"] = r["stations"]; leg["lines"] = r["lines_used"]; leg["line_changes"] = r["transfers"]
                leg["fare_source"] = "BMRCL GTFS token fare (peak)"
                if leg["cost_inr"] <= 0:
                    leg["cost_inr"] = round(bmrcl_fare_by_km(leg["km"]), 2)
            else:
                leg["note"] = "Assumed straight-line walking connection (hypothetical path, not a surveyed footpath)"
            out.append(leg)
        tot = {"minutes": round(sum(l["minutes"] for l in out), 2), "km": round(sum(l["km"] for l in out), 3), "cost_inr": round(sum(l["cost_inr"] for l in out), 2),
               "boardings": sum(l["boardings"] for l in legs), "transfers": max(0, sum(l["boardings"] for l in legs) - 1), "modes": [l["mode"] for l in out]}
        return {"objective": objective, "legs": out, "totals": tot}

    def alternatives(self, o, d):
        res, seen = [], set()
        for name, kw in [("time", {}), ("cost", {}), ("transfers", {}), ("distance", {}), ("metro + walk only", {"bus": False}), ("bus + walk only", {"metro": False})]:
            try:
                r = self.route(o, d, kw and "time" or name, **kw) if kw else self.route(o, d, name)
            except NodalError:
                continue
            need = {"metro + walk only": "metro", "bus + walk only": "bus"}.get(name)
            if need and need not in r["totals"]["modes"]:
                continue
            r["label"] = name; sig = tuple((l["mode"], l["from"]["name"], l["to"]["name"]) for l in r["legs"])
            if sig not in seen:
                seen.add(sig); res.append(r)
        return {"alternatives": res, "assumptions": self.A, "notes": NOTES}
