import csv, io
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .services import NET, NodalError, OBJECTIVES
from .data import load_proposed, ROOT
from .context import Context
from .multimodal import Multimodal, ASSUME as MM_ASSUME, OBJECTIVES as MM_OBJ
from .economics import economics, DEFAULTS as ECON_DEFAULTS
from .planning import Planner, PRESETS, CRITERIA, CRITERIA_INFO, ASSUME
CTX = Context()
PLAN = Planner(NET, CTX)
_MM = {}


def get_mm(**params):
    key = tuple(sorted((k, v) for k, v in params.items() if v is not None))
    if key not in _MM:
        _MM[key] = Multimodal(NET, CTX, PLAN.KX, PLAN.KY, dict(key))
    return _MM[key]

app = FastAPI(title="NODAL API", version="1.0",
              description="Network Optimization, Diagnostics and Analysis Lab: Namma Metro graph analytics")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(NodalError)
async def nodal_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=400, content={"detail": str(exc)})


class FailureRequest(BaseModel):
    removed: list[str] = Field(default_factory=list, description="station ids to fail")
    removed_edges: list[list[str]] = Field(default_factory=list, description="[[u, v], ...] connections to cut")
    removed_line: str | None = Field(None, description="disable every connection of a whole line")
    src: str | None = None
    dst: str | None = None


class HypEdge(BaseModel):
    u: str
    v: str
    min: float = Field(10.0, gt=0)
    km: float = Field(2.0, gt=0)
    line: str = "hypothetical"


class HypStation(BaseModel):
    id: str | None = None
    name: str
    lat: float
    lon: float
    lines: list[str] = Field(default_factory=list)


class RecoverRequest(BaseModel):
    removed: list[str] = Field(default_factory=list)
    new_edges: list[HypEdge] = Field(default_factory=list)
    new_stations: list[HypStation] = Field(default_factory=list)


class StationIn(BaseModel):
    id: str | None = None
    lat: float | None = None
    lon: float | None = None
    name: str | None = None


class CorridorIn(BaseModel):
    id: str | None = None
    name: str = "Hypothetical corridor"
    kind: str = "custom"
    target: str | None = None
    alignment: str | None = None
    stations: list[StationIn] = Field(min_length=2)
    seg_geoms: list[list[list[float]]] | None = None


class CandidateReq(BaseModel):
    targets: list[str] | None = None
    kinds: list[str] | None = None
    weights: dict[str, float] = Field(default_factory=lambda: dict(PRESETS["C"]["weights"]))
    budget_cr: float | None = Field(None, gt=0)
    max_spacing_km: float = Field(1.6, ge=0.8, le=5)
    n_stations: int = Field(0, ge=0, le=30)
    cost_per_km: float = Field(300.0, ge=0)
    top_n: int = Field(10, ge=1, le=50)
    min_distance_km: float = Field(1.2, ge=0)


class EvalReq(BaseModel):
    corridors: list[CorridorIn] = Field(min_length=1)
    cost_per_km: float = Field(300.0, ge=0)


class ScenarioReq(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = "user-designed"
    corridors: list[CorridorIn] = Field(min_length=1)
    cost_per_km: float = Field(300.0, ge=0)
    notes: str = ""


class GenReq(BaseModel):
    budget_cr: float = Field(8000.0, gt=0)
    max_spacing_km: float = Field(1.6, ge=0.8, le=5)
    n_stations: int = Field(0, ge=0, le=30)
    cost_per_km: float = Field(300.0, ge=0)


@app.get("/api/network")
def network():
    return NET.network_json()


@app.get("/api/proposed")
def proposed():
    return load_proposed()


@app.get("/api/metrics")
def metrics():
    return NET.metrics()


@app.get("/api/intel")
def intel():
    rows = list(NET.intel_cache.values())
    return {"stations": rows,
            "top_degree": sorted(rows, key=lambda r: (-r["degree_centrality"], r["name"]))[:10],
            "top_betweenness": sorted(rows, key=lambda r: -r["betweenness"])[:10],
            "articulation_points": [r for r in rows if r["articulation"]],
            "note": "In a tree-shaped network every non-terminal station is an articulation point; betweenness still separates their importance."}


@app.get("/api/route")
def route(src: str, dst: str, objective: str = Query("time")):
    return NET.route(src, dst, objective)


@app.get("/api/route/compare")
def route_compare(src: str, dst: str):
    return {o: NET.route(src, dst, o) for o in OBJECTIVES}


@app.get("/api/trace")
def trace(name: str, source: str, target: str | None = None, scope: str = "existing",
          max_km: float = Query(3.0, gt=0, le=30), k: int = Query(0, ge=0, le=20), weight: str = "km", overrides: str | None = None):
    return NET.trace(name, source, target, scope, max_km, k, weight, overrides)


@app.get("/api/algorithms/compare")
def compare(max_km: float = Query(3.0, gt=0, le=30), k: int = Query(0, ge=0, le=20)):
    return NET.compare(max_km, k)


@app.get("/api/expansion")
def expansion(max_km: float = Query(3.0, gt=0, le=30), k: int = Query(0, ge=0, le=20),
              algorithm: str = "kruskal", budget_km: float | None = Query(None, gt=0),
              cost_per_km: float = Query(300.0, ge=0)):
    return NET.expansion(max_km, k, algorithm, budget_km, cost_per_km)


@app.post("/api/failure")
def failure(req: FailureRequest):
    return NET.failure(req.removed, req.src, req.dst, [tuple(e) for e in req.removed_edges if len(e) == 2], req.removed_line)


@app.get("/api/failure/ranking")
def failure_ranking():
    return NET.failure_ranking()


@app.post("/api/failure/recover")
def failure_recover(req: RecoverRequest):
    NET.check(*req.removed)
    new_edges = [e.model_dump() for e in req.new_edges]
    new_stations = [s.model_dump() for s in req.new_stations]
    return NET.failure_recover(req.removed, new_edges, new_stations)


@app.get("/api/interchange/costs")
def interchange_costs():
    return {
        "label": "Per-station interchange costs derived from GTFS pathways.txt and transfers.txt",
        "headway_min": 6.0,
        "wait_assumption": "Expected wait = headway / 2 (peak service)",
        "stations": NET.interchange_costs_detail(),
    }


@app.get("/api/export/stations.csv", response_class=PlainTextResponse)
def export_csv():
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["id", "name", "lines", "degree", "degree_centrality", "betweenness", "closeness", "articulation_point"])
    for r in NET.intel_cache.values():
        w.writerow([r["id"], r["name"], "/".join(r["lines"]), r["degree"], f"{r['degree_centrality']:.6f}",
                    f"{r['betweenness']:.6f}", f"{r['closeness']:.6f}", r["articulation"]])
    return buf.getvalue()


def _c(c):
    return c.model_dump()


@app.get("/api/planning/accessibility")
def plan_access():
    return PLAN.accessibility()


@app.get("/api/planning/criteria")
def plan_criteria():
    return {"criteria": CRITERIA, "info": CRITERIA_INFO, "presets": PRESETS, "assumptions": ASSUME, "avg_network_kmh": PLAN.avg_kmh,
            "label": "HYPOTHETICAL planning model: not an official BMRCL proposal; no population, demand, terrain or land-use data is used"}


@app.post("/api/planning/candidates")
def plan_candidates(req: CandidateReq):
    pool = PLAN.pool(req.targets, req.kinds, req.max_spacing_km, req.n_stations, req.cost_per_km, req.min_distance_km)
    ranked = PLAN.rank(pool, req.weights, req.budget_cr)
    out = []
    for p in ranked[:req.top_n]:
        out.append({**p, "explain": PLAN.explain(p, req.weights)})
    return {"label": "Hypothetical planning scenarios, not official proposals", "pool_size": len(pool), "within_budget": len(ranked), "candidates": out}


@app.post("/api/planning/evaluate")
def plan_evaluate(req: EvalReq):
    return PLAN.evaluate([_c(c) for c in req.corridors], req.cost_per_km)


@app.post("/api/planning/scenarios/generate")
def plan_generate(req: GenReq):
    return {"label": "Hypothetical planning scenarios, not official proposals", "scenarios": PLAN.generate_scenarios(req.budget_cr, req.max_spacing_km, req.n_stations, req.cost_per_km)}


@app.post("/api/planning/scenarios")
def plan_save(req: ScenarioReq):
    sc, ev = PLAN.save_scenario(req.name, req.kind, [_c(c) for c in req.corridors], req.cost_per_km, req.notes)
    return {"scenario": sc, "eval": ev}


@app.get("/api/planning/scenarios")
def plan_list():
    return list(PLAN.scenarios.values())


@app.delete("/api/planning/scenarios/{sid}")
def plan_delete(sid: str):
    PLAN.delete_scenario(sid)
    return {"deleted": sid}


@app.get("/api/planning/scenarios/{sid}/export")
def plan_export(sid: str, format: str = "json"):
    if sid not in PLAN.scenarios:
        raise NodalError("unknown scenario")
    sc = PLAN.scenarios[sid]
    if format == "csv":
        from fastapi.responses import PlainTextResponse as P
        buf = io.StringIO(); w = csv.writer(buf); w.writerow(["corridor", "seq", "station", "new", "lat", "lon"])
        for c in sc["corridors"]:
            for i, s in enumerate(c["stations"], 1):
                w.writerow([c["name"], i, s["name"], s["new"], f"{s['lat']:.6f}", f"{s['lon']:.6f}"])
        return P(buf.getvalue(), media_type="text/csv")
    return {**sc, "label": "HYPOTHETICAL planning scenario exported from NODAL; not an official proposal"}


class EconReq(BaseModel):
    corridors: list[CorridorIn] = Field(min_length=1)
    cost_per_km_cr: float = Field(300.0, ge=0)
    cost_per_station_cr: float = Field(0.0, ge=0)
    cost_per_train_cr: float = Field(0.0, ge=0)
    headway_min: float = Field(6.0, gt=0)
    avg_speed_kmh: float = Field(33.0, gt=5, le=120)
    turnaround_min: float = Field(5.0, ge=0)
    discount_rate: float = Field(0.08, ge=0, le=0.5)
    life_years: int = Field(30, ge=1, le=100)
    om_pct_per_year: float = Field(0.0, ge=0, le=50)
    daily_trips: float = Field(0.0, ge=0)
    saving_per_trip_min: float | None = Field(None, ge=0)
    value_of_time_inr_per_hour: float = Field(0.0, ge=0)
    budget_cr: float | None = Field(None, gt=0)


@app.post("/api/economics")
def econ(req: EconReq):
    d = req.model_dump(); cors = d.pop("corridors")
    ev = PLAN.evaluate(cors, d["cost_per_km_cr"], full=False)
    return {"label": "HYPOTHETICAL economic estimate from user-set assumptions; not an official project cost", **economics(ev, **d), "evaluation": {k: ev[k] for k in ("length_km", "new_stations", "people_improved", "cells_improved", "before", "after", "anchors_newly_served")}}


@app.get("/api/economics/defaults")
def econ_defaults():
    return ECON_DEFAULTS


@app.get("/api/multimodal/route")
def mm_route(olat: float = Query(ge=12.5, le=13.5), olon: float = Query(ge=77.2, le=78.0), dlat: float = Query(ge=12.5, le=13.5), dlon: float = Query(ge=77.2, le=78.0),
             walk_kmh: float | None = Query(None, gt=1, le=8), bus_kmh: float | None = Query(None, gt=3, le=60), bus_board_fare_inr: float | None = Query(None, ge=0),
             bus_fare_per_km_inr: float | None = Query(None, ge=0), metro_wait_min: float | None = Query(None, ge=0)):
    mm = get_mm(walk_kmh=walk_kmh, bus_kmh=bus_kmh, bus_board_fare_inr=bus_board_fare_inr, bus_fare_per_km_inr=bus_fare_per_km_inr, metro_wait_min=metro_wait_min)
    return {"label": "Multimodal planning estimate: walking links and bus times/fares are assumptions", **mm.alternatives((olat, olon), (dlat, dlon))}


@app.get("/api/layers/wards")
def layer_wards():
    return CTX.wards_geojson


@app.get("/api/layers/bus")
def layer_bus():
    w = CTX.stop_wait()
    return {"meta": CTX.bus_meta, "stops": [[s[2], s[1], s[0], s[3], None if w[i] != w[i] else round(float(w[i]), 1)] for i, s in enumerate(CTX.stops)]}


@app.get("/api/provenance")
def provenance():
    return [
        {"layer": "Metro network, stations, alignments, times, fares", "source": NET.source["name"], "url": NET.source["url"], "date": NET.source["feed_valid"], "licence": NET.source["license_note"], "limitations": "Unofficial; times modeled by feed author; operational lines only"},
        {"layer": "Population density / workers by residence", "source": CTX.ward_meta["source"], "url": "https://github.com/suvajit/opendata/tree/master/BBMP/data", "date": "Census of India 2011 (15 years old)", "licence": "CC BY-SA 3.0", "limitations": "198 BBMP wards only (outside this area there is no data); workers = by place of residence, not jobs located there; boundaries pre-2020 delimitation"},
        {"layer": "Bus stops and routes", "source": CTX.bus_meta["source"], "url": "https://github.com/Vonter/bmtc-gtfs", "date": "feed snapshot at build time", "licence": "see repository", "limitations": CTX.bus_meta["caveat"]},
        {"layer": "Destinations & growth centres", "source": "Hand-entered list (datasets/raw/destinations.csv)", "url": "", "date": "n/a", "licence": "n/a", "limitations": "Approximate coordinates; importance not based on data"},
        {"layer": "Basemap", "source": "OpenFreeMap (OpenStreetMap data), Esri World Imagery, CARTO labels, AWS terrain tiles", "url": "", "date": "live", "licence": "ODbL / provider terms", "limitations": "Third-party tile services; requires internet"}]


FRONT = ROOT / "frontend"
if FRONT.exists():
    app.mount("/", StaticFiles(directory=FRONT, html=True), name="frontend")
