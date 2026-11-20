# Dataset notes (Namma Metro)
**Source:** unofficial BMRCL GTFS feed by Vonter, https://github.com/Vonter/bmrcl-gtfs (raw copy in `datasets/raw/gtfs/`).
It is generated from OpenStreetMap spatial data plus BMRCL's published timetables; feed valid 2026-08-17 → 2027-08-17.
It is NOT an official BMRCL release. OpenStreetMap data is ODbL; see the repository for attribution and licence.

| Item | Status |
|---|---|
| Station names, coordinates (parent stations), line membership, station order | From the feed (OSM-derived) |
| Track alignment geometry | From the feed `shapes.txt` (OSM-derived), sliced per segment |
| Segment distance `km` | From the feed `stop_times.shape_dist_traveled` (along the alignment). Totals: Purple 43.4, Green 33.1, Yellow 18.0 km |
| `km_straight` | Calculated (haversine between stations) |
| Segment time `min` | Feed timetable arrival-to-arrival (median across trips); the feed author MODELS these times |
| Transfer time (5 min), transfer penalty (8 min-eq.) | My ASSUMPTIONS (feed only states a 60 s minimum) |
| Operational status | All stations/lines in the feed are in the current timetable, i.e. operational |
| Proposed / under-construction lines | NOT in the feed and NOT drawn. To add verified data, put a GeoJSON at `datasets/raw/proposed.geojson` |

Scope: Purple, Green and Yellow lines (83 stations, 82 links, tree-shaped). Rebuild: `python scripts/build_from_gtfs.py`.
Stations are connected because they are consecutive on a line, never because they are close together.
Verify against BMRCL (bmrc.co.in) before quoting figures in a report.

## Context datasets added for planning (NODAL 2.0)
| Dataset | Source | Notes |
|---|---|---|
| Ward population, workers (2011) | suvajit/opendata (Census of India 2011 merged with 198 BBMP ward boundaries), CC BY-SA 3.0 | Total 8,443,675 = official 2011 BBMP population. 15 years old; BBMP wards only (no data for the airport/Hoskote side); `workers` = by place of **residence**, not jobs located in the ward. Boundaries are pre-2020 delimitation |
| BMTC bus stops, routes, headways | Vonter/bmtc-gtfs (unofficial, from the Namma BMTC 2.0 app) | Stops merged by name; source app has known timetable inaccuracies; headway = timetable span / trips |
| Metro token fares (peak) | BMRCL GTFS `fare_leg_rules` / `fare_products` | Real fares for every station pair |
| Destinations / growth centres | `datasets/raw/destinations.csv` (hand-entered) | Approximate coordinates, no importance data |

Rebuild everything: `python scripts/build_from_gtfs.py && python scripts/build_context.py` (downloads from GitHub if raw files are missing).

**Not available / not invented:** employment by location, passenger demand, hospital and school locations (only a few are in `destinations.csv`), terrain/land-use/environmental constraints, BMTC fares (a placeholder tariff is used and labelled), suburban rail and airport-bus services.
