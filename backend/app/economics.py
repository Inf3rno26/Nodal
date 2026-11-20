"""Transportation economics for a (hypothetical) corridor evaluation. Every input is an explicit, editable assumption;
nothing here is an official cost estimate."""
import math

DEFAULTS = {"cost_per_km_cr": 300.0, "cost_per_station_cr": 0.0, "cost_per_train_cr": 0.0, "headway_min": 6.0, "avg_speed_kmh": 33.0, "turnaround_min": 5.0,
            "discount_rate": 0.08, "life_years": 30, "om_pct_per_year": 0.0, "daily_trips": 0.0, "saving_per_trip_min": None, "value_of_time_inr_per_hour": 0.0, "budget_cr": None}


def crf(r, n):
    return 1 / n if r == 0 else r * (1 + r) ** n / ((1 + r) ** n - 1)


def economics(ev, **kw):
    p = {**DEFAULTS, **{k: v for k, v in kw.items() if v is not None or k in ("budget_cr", "saving_per_trip_min")}}
    km, stn = ev["length_km"], ev["new_stations"]
    rt = 2 * km / p["avg_speed_kmh"] * 60 + 2 * p["turnaround_min"]; trains = max(1, math.ceil(rt / p["headway_min"])) if km > 0 else 0
    cap = km * p["cost_per_km_cr"] + stn * p["cost_per_station_cr"] + trains * p["cost_per_train_cr"]
    ann = cap * crf(p["discount_rate"], p["life_years"]) + cap * p["om_pct_per_year"] / 100
    mean_saving = ev["before"]["mean_pair_min"] - ev["after"]["mean_pair_min"]
    s_trip = p["saving_per_trip_min"] if p["saving_per_trip_min"] is not None else mean_saving
    pm_year = p["daily_trips"] * 365 * s_trip; ph_year = pm_year / 60
    out = {"inputs": p, "length_km": km, "new_stations": stn, "round_trip_min": rt, "trains_needed": trains,
           "capital_cr": cap, "capital_breakdown": {"track_and_civil": km * p["cost_per_km_cr"], "stations": stn * p["cost_per_station_cr"], "rolling_stock": trains * p["cost_per_train_cr"]},
           "cost_per_km_cr": cap / km if km else None, "cost_per_station_cr": cap / stn if stn else None, "annualised_cost_cr": ann, "capital_recovery_factor": crf(p["discount_rate"], p["life_years"]),
           "mean_destination_pair_saving_min": mean_saving, "people_gaining_better_access_2011": ev.get("people_improved"), "cells_improved_km2": ev.get("cells_improved"),
           "cost_per_person_gaining_access_inr": cap * 1e7 / ev["people_improved"] if ev.get("people_improved") else None,
           "within_budget": None if p["budget_cr"] is None else cap <= p["budget_cr"], "budget_cr": p["budget_cr"],
           "demand_dependent": None,
           "formulae": {"capital": "km × ₹cr/km + stations × ₹cr/station + trains × ₹cr/train", "trains": "ceil((2·km/speed·60 + 2·turnaround) / headway)",
                        "annualised": "capital × CRF + capital × O&M%, CRF = r(1+r)^n / ((1+r)^n − 1)", "person_hours": "daily trips × 365 × saving per trip / 60"}}
    if p["daily_trips"] > 0 and s_trip > 0:
        d = {"person_hours_saved_per_year": ph_year, "cost_per_person_hour_saved_inr": ann * 1e7 / ph_year if ph_year else None}
        if p["value_of_time_inr_per_hour"] > 0:
            ben = ph_year * p["value_of_time_inr_per_hour"] / 1e7; d.update({"annual_time_benefit_cr": ben, "benefit_cost_ratio": ben / ann if ann else None})
        out["demand_dependent"] = d
    return out
