"""Phase 03.5 (plan file calls itself "07") — route-aware corridors.

Run: uv run python backend/build_routes.py

Replaces straight-line corridor geometry with route-aware estimates per the
03.5 START-GATE answers (Q1=c snap+buffer, Q2=10 km, Q3=b legacy+new golden,
Q4=direct feed, no confidence multiplier):

  osm_snapped        corridor snapped to the nearest OSM `power=line` way that
                     lies within SNAP_M of BOTH endpoints (routing proxy;
                     geometry = substring of that way between the projections)
  buffered_estimate  no OSM line within SNAP_M — straight corridor kept,
                     10 km uncertainty buffer declared (`buffer_m` prop)
  straight_fallback  single-point project with no OSM line within SNAP_M

Outputs:
  gridlock_projects.geojson — geometry replaced; gains `geometry_source`,
    `snap_m`/`buffer_m`, and legacy `center_lat`/`center_lon` (the phase-02
    straight-line centers, so the guide/golden center metric stays stable)
  pairs_metrics.csv — `distance_m` (route-aware, EPSG:5070 polyline-to-
    polyline) replaces the scored distance; old closest-point column renamed
    `distance_m_legacy_straightline` (meters) for traceability; `distance_center_mi`
    unchanged (guide method)

The original straight geojson is cached once at
`_cache/gridlock_projects_straight.geojson` so legacy distances stay
reproducible on reruns.
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import date

import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, substring

from .build_data import BBOX, CACHE, PROC, http_json, hav_mi

OVERPASS_CACHE = CACHE / "overpass_power.json"
STRAIGHT_CACHE = CACHE / "gridlock_projects_straight.geojson"
GEOJSON = PROC / "gridlock_projects.geojson"

SNAP_M = 10_000.0    # START-GATE Q2: snap threshold AND buffer size (tunable)
BUFFER_M = 10_000.0  # declared uncertainty around unsnapped straight corridors
KM40_MI = 40 / 1.609344
R_M = 1609.344

# heuristic snap guards — reject pathologies, not to be tuned per-pair:
# too short = both endpoints projected onto the same crossing point (corridor
# perpendicular to the way); too long = detour along an unrelated stretch.
# Ceiling: a legitimately winding corridor beyond 2x straight + buffer falls
# back to buffered_estimate; raise the factor if a real route ever hits it.
MIN_SNAP_RATIO = 0.5
MAX_SNAP_LEN = lambda straight: 2 * straight + BUFFER_M  # noqa: E731

to5070 = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
to4326 = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True)


def line5070(coords: list) -> LineString:
    xs, ys = to5070.transform([c[0] for c in coords], [c[1] for c in coords])
    return LineString(list(zip(xs, ys)))


def point5070(lon: float, lat: float) -> Point:
    x, y = to5070.transform(lon, lat)
    return Point(x, y)


def back4326(geom) -> list:
    xs, ys = to4326.transform(*zip(*geom.coords))
    return [[x, y] for x, y in zip(xs, ys)]


def fetch_power() -> list[dict]:
    """One Overpass pull: power=line (ways, geometry), power=tower (nodes),
    power=substation (nwr) for the SC/GA territory bbox. Cached."""
    if OVERPASS_CACHE.exists():
        return json.loads(OVERPASS_CACHE.read_text())
    b = f"{BBOX['ymin']},{BBOX['xmin']},{BBOX['ymax']},{BBOX['xmax']}"
    query = (
        '[out:json][timeout:240];('
        f'way["power"="line"]({b});'
        f'node["power"="tower"]({b});'
        f'nwr["power"="substation"]({b});'
        ");out geom;"
    )
    j = http_json("https://overpass-api.de/api/interpreter",
                  data=urllib.parse.urlencode({"data": query}).encode(),
                  timeout=300)
    els = j.get("elements", [])
    OVERPASS_CACHE.write_text(json.dumps(els))
    return els


def way_label(el: dict) -> str:
    tags = el.get("tags") or {}
    nm = tags.get("name") or tags.get("ref")
    kv = tags.get("voltage")
    bits = [f"OSM way {el['id']}"]
    if nm:
        bits.append(str(nm))
    if kv:
        bits.append(f"{kv} V")
    return " · ".join(bits)


def load_ways(els: list[dict]) -> list[tuple[LineString, str]]:
    ways = []
    for el in els:
        if (el.get("tags") or {}).get("power") != "line":
            continue
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        ways.append((line5070([[g["lon"], g["lat"]] for g in geom]), way_label(el)))
    return ways


def snap_line(a5070: Point, b5070: Point, straight_len: float, ways, tree):
    """Nearest way within SNAP_M of both endpoints -> (substring geom, label,
    snap_dist) or None. ponytail: single-way proxy — no multi-way routing."""
    ca = set(tree.query(a5070, predicate="dwithin", distance=SNAP_M))
    cb = set(tree.query(b5070, predicate="dwithin", distance=SNAP_M))
    both = ca & cb
    if not both:
        return None
    i = min(both, key=lambda k: ways[k][0].distance(a5070) + ways[k][0].distance(b5070))
    way, label = ways[i]
    snapped = substring(way, way.project(a5070), way.project(b5070))
    if snapped.is_empty or snapped.length < MIN_SNAP_RATIO * straight_len:
        return None
    if snapped.length > MAX_SNAP_LEN(straight_len):
        return None
    d = max(way.distance(a5070), way.distance(b5070))
    return snapped, label, d


def snap_point(p5070: Point, ways, tree):
    idx = tree.query(p5070, predicate="dwithin", distance=SNAP_M)
    if not len(idx):
        return None
    i = min(idx, key=lambda k: ways[k][0].distance(p5070))
    way, label = ways[i]
    snapped = nearest_points(way, p5070)[0]
    return snapped, label, way.distance(p5070)


def main() -> None:
    # Capture the straight (phase-02-style) geojson for legacy distances: recapture
    # whenever the current geojson is straight (no geometry_source — i.e. build_data
    # just reran under the guide-only policy); never overwrite with route-aware output.
    cur = json.loads(GEOJSON.read_text(encoding="utf-8"))
    if not any("geometry_source" in f["properties"] for f in cur["features"]):
        STRAIGHT_CACHE.write_text(GEOJSON.read_text(encoding="utf-8"))
    legacy_feats = json.loads(STRAIGHT_CACHE.read_text(encoding="utf-8"))["features"]
    assert len(legacy_feats) == len(cur["features"]), (
        f"legacy features = {len(legacy_feats)}, current = {len(cur['features'])} — "
        "stale cache; delete _cache/gridlock_projects_straight.geojson and rerun build_data")

    els = fetch_power()
    n_line = sum(1 for e in els if (e.get("tags") or {}).get("power") == "line")
    n_tower = sum(1 for e in els if (e.get("tags") or {}).get("power") == "tower")
    n_sub = sum(1 for e in els if (e.get("tags") or {}).get("power") == "substation")
    ways = load_ways(els)
    print(f"Overpass: {len(els)} elements (line ways={n_line}, towers={n_tower}, "
          f"substations={n_sub}); usable line geometries={len(ways)}")
    assert ways, "no OSM power=line ways — Overpass pull failed or cache stale"
    tree = shapely.STRtree([w for w, _ in ways])

    counts = {"osm_snapped": 0, "buffered_estimate": 0, "straight_fallback": 0}
    new_feats = []
    for f in legacy_feats:
        p = dict(f["properties"])
        geom = f["geometry"]
        legacy = (line5070(geom["coordinates"]) if geom["type"] == "LineString"
                  else point5070(*geom["coordinates"]))
        # legacy center in 4326 = phase-02/engine midpoint rule (golden metric)
        if geom["type"] == "LineString":
            c = geom["coordinates"]
            center = Point((c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2)
        else:
            center = Point(geom["coordinates"])

        snap = None
        if geom["type"] == "LineString":
            a = point5070(*geom["coordinates"][0])
            b = point5070(*geom["coordinates"][1])
            snap = snap_line(a, b, legacy.length, ways, tree)
        else:
            snap = snap_point(legacy, ways, tree)

        if snap:
            g5070, label, d = snap
            p["geometry_source"] = "osm_snapped"
            p["snap_m"] = round(d, 1)
            p["geometry_basis"] = (
                f"route-aware: {'corridor snapped to' if geom['type'] == 'LineString' else 'point snapped to'} "
                f"power=line {label}"
            )
            p["geometry_note"] = "OSM route proxy, not surveyed clearance"
        elif geom["type"] == "LineString":
            g5070 = legacy
            p["geometry_source"] = "buffered_estimate"
            p["buffer_m"] = BUFFER_M
            p["geometry_basis"] = (
                f"straight corridor (endpoint geocode) + {BUFFER_M / 1000:.0f} km "
                f"uncertainty buffer (no OSM power=line within {SNAP_M / 1000:.0f} km)"
            )
            p["geometry_note"] = "corridor proximity, not surveyed distance"
        else:
            g5070 = legacy
            p["geometry_source"] = "straight_fallback"
            p["buffer_m"] = BUFFER_M
            p["geometry_basis"] = (
                f"straight fallback: geocoded point (no OSM power=line within "
                f"{SNAP_M / 1000:.0f} km)"
            )
            p["geometry_note"] = "corridor proximity, not surveyed distance"

        counts[p["geometry_source"]] += 1
        p["center_lat"] = round(center.y, 6)
        p["center_lon"] = round(center.x, 6)
        coords = back4326(g5070)
        new_feats.append({"type": "Feature", "properties": p,
                          "geometry": {"type": geom["type"],
                                       "coordinates": coords[0] if geom["type"] == "Point" else coords}})

    assert all(f["properties"].get("geometry_source") in counts for f in new_feats)
    assert all(f["geometry"] for f in new_feats)
    GEOJSON.write_text(json.dumps({"type": "FeatureCollection",
                                   "features": new_feats}, indent=1))

    write_pairs(legacy_feats, new_feats)

    n = len(new_feats)
    rate = 100 * counts["osm_snapped"] / n
    print(f"geometry_source: {counts} — snap rate {rate:.1f}% of {n} projects")
    print("wrote", GEOJSON)


def write_pairs(legacy_feats: list[dict], new_feats: list[dict]) -> None:
    """Route-aware pairs_metrics: distance_m (new scored geometry),
    distance_m_legacy_straightline (old closest-point column, renamed to meters),
    distance_center_mi (guide/golden, unchanged), time_gap_days.
    Inclusion: min(center, legacy, route) < 40 km (union of old + new rules)."""
    byu = lambda feats: (  # noqa: E731
        [f for f in feats if "Dominion" in f["properties"]["utility"]],
        [f for f in feats if f["properties"]["utility"] == "Georgia Power"])
    l_desc, l_gpc = byu(legacy_feats)
    r = {(f["properties"]["project_id"]): f for f in new_feats}

    rows = []
    for la in l_desc:
        for lb in l_gpc:
            ga = line5070(la["geometry"]["coordinates"]) if la["geometry"]["type"] == "LineString" \
                else point5070(*la["geometry"]["coordinates"])
            gb = line5070(lb["geometry"]["coordinates"]) if lb["geometry"]["type"] == "LineString" \
                else point5070(*lb["geometry"]["coordinates"])
            fa, fb = r[la["properties"]["project_id"]], r[lb["properties"]["project_id"]]
            ra = line5070(fa["geometry"]["coordinates"]) if fa["geometry"]["type"] == "LineString" \
                else point5070(*fa["geometry"]["coordinates"])
            rb = line5070(fb["geometry"]["coordinates"]) if fb["geometry"]["type"] == "LineString" \
                else point5070(*fb["geometry"]["coordinates"])

            d_route = ra.distance(rb)
            d_legacy = ga.distance(gb)
            pa, pb = fa["properties"], fb["properties"]  # new props carry center/date
            d_center = hav_mi(pa["center_lat"], pa["center_lon"],
                              pb["center_lat"], pb["center_lon"]) * R_M
            if min(d_center, d_legacy, d_route) >= KM40_MI * R_M:
                continue
            gap = abs((date.fromisoformat(pa["in_service_date"])
                       - date.fromisoformat(pb["in_service_date"])).days)
            rows.append({
                "project_id_a": pa["project_id"], "project_id_b": pb["project_id"],
                "distance_m": round(d_route, 3),
                "distance_m_legacy_straightline": round(d_legacy, 3),
                "distance_center_mi": round(d_center / R_M, 3),
                "time_gap_days": gap,
            })
    pd.DataFrame(rows).to_csv(PROC / "pairs_metrics.csv", index=False)
    print(f"pairs_metrics: {len(rows)} rows (route-aware + legacy columns)")


if __name__ == "__main__":
    main()