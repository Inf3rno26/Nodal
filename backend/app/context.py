"""Real-world context data: Census 2011 ward population (BBMP, 198 wards) and the BMTC bus stop network."""
import json
import numpy as np
from shapely import STRtree, points
from shapely.geometry import shape
from shapely.validation import make_valid
from .data import ROOT

PROC = ROOT / "datasets" / "processed"


def hav_arr(lat1, lon1, lat2, lon2):
    R, r = 6371.0088, np.pi / 180
    dp, dl = (lat2 - lat1) * r, (lon2 - lon1) * r
    h = np.sin(dp / 2) ** 2 + np.cos(lat1 * r) * np.cos(lat2 * r) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(h))


class Context:
    def __init__(self):
        w = json.load(open(PROC / "wards.json"))
        self.wards_geojson, self.ward_meta = w, w["meta"]
        self.props = [f["properties"] for f in w["features"]]
        self.geoms = [self._fix(shape(f["geometry"])) for f in w["features"]]
        self.tree = STRtree(self.geoms)
        b = json.load(open(PROC / "bus.json"))
        self.bus_meta, self.stops, self.routes = b["meta"], b["stops"], b["routes"]
        self.slat = np.array([s[1] for s in self.stops]); self.slon = np.array([s[2] for s in self.stops])
        self._edges = None

    @staticmethod
    def _fix(g):
        if g.is_valid:
            return g
        try:
            return make_valid(g)
        except Exception:
            return g.buffer(0)

    # ---- census ----
    def ward_index(self, lat, lon):
        lat, lon = np.atleast_1d(lat), np.atleast_1d(lon)
        out = -np.ones(len(lat), int)
        pr = self.tree.query(points(lon, lat), predicate="within")
        for pi, gi in zip(pr[0], pr[1]):
            if out[pi] < 0:
                out[pi] = gi
        return out

    def density(self, lat, lon):
        """People per km² (Census 2011) for each point; NaN outside the BBMP ward boundaries."""
        idx = self.ward_index(lat, lon)
        d = np.array([p["density"] for p in self.props] + [np.nan])
        return d[idx]

    def worker_density(self, lat, lon):
        idx = self.ward_index(lat, lon)
        d = np.array([p["worker_density"] for p in self.props] + [np.nan])
        return d[idx]

    # ---- bus network ----
    def bus_edges(self):
        """{(a, b): (km, best_headway_min, n_routes, [route_names])} between consecutive stops of route patterns (a < b)."""
        if self._edges is None:
            agg = {}
            for rname, hw, _, seq in self.routes:
                clean_r = rname.split()[0].replace('_', '-').strip() if rname else "BMTC"
                for a, b in zip(seq, seq[1:]):
                    k = (a, b) if a < b else (b, a)
                    if k not in agg:
                        agg[k] = [hw, 1, [clean_r]]
                    else:
                        entry = agg[k]
                        if hw < entry[0]:
                            entry[0] = hw
                        entry[1] += 1
                        if clean_r not in entry[2] and len(entry[2]) < 5:
                            entry[2].append(clean_r)
            ks = list(agg); A = np.array([k[0] for k in ks]); B = np.array([k[1] for k in ks])
            km = hav_arr(self.slat[A], self.slon[A], self.slat[B], self.slon[B])
            self._edges = {k: (float(d), agg[k][0], agg[k][1], agg[k][2]) for k, d in zip(ks, km) if d <= 3.0}
        return self._edges

    def stop_wait(self):
        """Expected wait (min) at each stop = half the best route headway there (timetable-derived; capped)."""
        w = np.full(len(self.stops), np.nan)
        for _, hw, _, seq in self.routes:
            for s in seq:
                w[s] = hw / 2 if np.isnan(w[s]) else min(w[s], hw / 2)
        return w
