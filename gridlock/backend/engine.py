"""Phase 03 scoring engine — canonical rule (byte-identical, 00 §2):

score = tier points (crossing=100, <1.6 km=60, <8 km=40, <40 km=20) + 15 if build windows overlap, total capped at 100; tie-break by smaller closest-point distance

Build window = [in-service year, in-service year + 1]; missing year -> bonus 0
(year_unknown: true), row never dropped. All distance math in EPSG:5070
(to_crs before ANY distance computation — never degrees). Pair scope =
DESC x GPC cross pairs (starter workbook scope). Excluded rows (>40 km) kept
as the 25 nearest exemplars (START-GATE 03-1).

Phase 03.5 (plan "07"): corridor geoms in the geojson are route-aware
(OSM-snapped / buffered — backend/build_routes.py), so `distance_m` is a
polyline-to-polyline separation and feeds the tier thresholds directly
(START-GATE 03.5 Q4: no confidence multiplier). `distance_center_mi` reads
the stored legacy centers (center_lat/center_lon props) so the guide/golden
center metric is unaffected by snapping.

Run: uv run python backend/engine.py   (rebuilds data/processed/overlaps.csv)
"""
from __future__ import annotations

import math
from datetime import date, datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

KM40 = 40000.0          # locked inclusion cutoff (40 km; START-GATE 03-3: >40,234 m excluded)
EXEMPLAR_RADIUS = 150_000.0  # ponytail: scan cap for the 25-nearest excluded exemplars; widen if pool < 25
EXEMPLARS = 25          # START-GATE 03-1
R_MI = 3958.7613

# starter `overlaps` sheet header — CSV export contract (byte order matters)
CSV_COLS = ["overlap_id", "distance_mi", "time_gap (day)", "utility_a",
            "project_id_a", "project_name_a", "utility_b", "project_id_b",
            "project_name_b"]


def tier_for(d_m: float) -> tuple[str, int]:
    """(tier, points) from closest-point distance in meters. Strict <; inclusion <= 40 km."""
    if d_m == 0:
        return "crossing", 100
    if d_m < 1600:
        return "<1.6 km", 60
    if d_m < 8000:
        return "<8 km", 40
    if d_m <= KM40:
        return "<40 km", 20
    return "excluded", 0


def shared_year(ya: int | None, yb: int | None) -> int | None:
    """[y, y+1] windows overlap -> the shared year; any missing year -> None."""
    if ya is None or yb is None:
        return None
    if ya <= yb + 1 and yb <= ya + 1:
        return max(ya, yb)
    return None


def score_for(points: int, shared: int | None) -> int:
    """tier points + 15 if windows overlap, capped at 100 (excluded+overlap scores 15 by formula)."""
    return min(100, points + (15 if shared is not None else 0))


def sort_overlaps(rows: list[dict]) -> list[dict]:
    """Canonical rank order: score desc, then smaller closest-point distance."""
    return sorted(rows, key=lambda r: (-r["score"], r["distance_m"]))


def year_of(iso: str) -> int | None:
    s = str(iso)
    return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else None


def to_date(v) -> date | None:
    """ISO 'YYYY-MM-DD' or Excel serial (origin 1899-12-30); unparsable -> None."""
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.date()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (datetime(1899, 12, 30) + pd.to_timedelta(float(v), unit="D")).date()
    try:
        return date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def hav_mi(la1: float, lo1: float, la2: float, lo2: float) -> float:
    a = (math.sin(math.radians(la2 - la1) / 2) ** 2
         + math.cos(math.radians(la1)) * math.cos(math.radians(la2))
         * math.sin(math.radians(lo2 - lo1) / 2) ** 2)
    return 2 * R_MI * math.asin(math.sqrt(a))


def build_overlaps() -> list[dict]:
    """Score every DESC x GPC pair <= 40 km (EPSG:5070 closest point) + 25 excluded
    exemplars; canonical sort; writes data/processed/overlaps.csv; returns rows."""
    gdf = gpd.read_file(PROC / "gridlock_projects.geojson")
    geom4326 = gdf.geometry.to_numpy()
    geom5070 = gdf.to_crs(5070).geometry.to_numpy()

    desc_pos = np.flatnonzero(gdf["utility"].str.contains("Dominion", na=False).to_numpy())
    gpc_pos = np.flatnonzero((gdf["utility"] == "Georgia Power").to_numpy())
    desc_g, gpc_g = geom5070[desc_pos], geom5070[gpc_pos]
    tree = shapely.STRtree(gpc_g)

    # candidate prefilter, then ALWAYS exact re-check (plan: a.distance(b) <= 40000)
    qi, qj = tree.query(desc_g, predicate="dwithin", distance=KM40)
    dd = shapely.distance(desc_g[qi], gpc_g[qj])
    pairs = [(int(desc_pos[i]), int(gpc_pos[j]), float(d))
             for i, j, d in zip(qi, qj, dd) if d <= KM40]

    # excluded exemplars: 25 nearest pairs just beyond 40 km (START-GATE 03-1)
    qi, qj = tree.query(desc_g, predicate="dwithin", distance=EXEMPLAR_RADIUS)
    dd = shapely.distance(desc_g[qi], gpc_g[qj])
    far = [(int(desc_pos[i]), int(gpc_pos[j]), float(d))
           for i, j, d in zip(qi, qj, dd) if d > KM40]
    far.sort(key=lambda t: t[2])
    pairs += far[:EXEMPLARS]

    info = {}
    for pos in np.concatenate([desc_pos, gpc_pos]):
        p = gdf.iloc[int(pos)]
        # 03.5: legacy straight-line center (golden/guide metric) stored as props
        clat, clon = p.get("center_lat"), p.get("center_lon")
        if clat is not None and not pd.isna(clat) and clon is not None and not pd.isna(clon):
            c = shapely.Point(float(clon), float(clat))
        else:
            c = geom4326[int(pos)].centroid
        info[int(pos)] = {
            "project_id": p["project_id"], "name": p["name"], "utility": p["utility"],
            "year": year_of(p["in_service_date"]), "date": to_date(p["in_service_date"]),
            "center": (c.y, c.x),
            "g4326": geom4326[int(pos)], "g5070": geom5070[int(pos)],
        }

    to4326 = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True)
    rows = []
    for i, j, d_m in pairs:
        a, b = info[i], info[j]
        tier, points = tier_for(d_m)
        shared = shared_year(a["year"], b["year"])
        gap = abs((a["date"] - b["date"]).days) if a["date"] and b["date"] else None
        sl = shapely.shortest_line(a["g5070"], b["g5070"])  # map segment, metric
        coords = [list(to4326.transform(x, y)) for x, y in shapely.get_coordinates(sl)]
        rows.append({
            "project_a": a["project_id"], "project_b": b["project_id"],
            "name_a": a["name"], "name_b": b["name"],
            "utilities": [a["utility"], b["utility"]],
            "tier": tier, "score": score_for(points, shared),
            "distance_m": d_m,
            "min_distance_km": round(d_m / 1000, 3),
            "distance_center_mi": round(hav_mi(*a["center"], *b["center"]), 3),
            "time_gap": gap,
            "shared_in_service_year": shared,
            "year_a": a["year"], "year_b": b["year"],
            "year_unknown": a["year"] is None or b["year"] is None,
            "shortest_line": {"type": "LineString", "coordinates": coords},
        })

    rows = sort_overlaps(rows)
    for n, r in enumerate(rows, 1):
        r["rank"] = n
        r["overlap_id"] = f"OVL_{n}"
    write_csv(rows)
    return rows


def write_csv(rows: list[dict]) -> Path:
    df = pd.DataFrame([{
        "overlap_id": r["overlap_id"],
        "distance_mi": round(r["distance_center_mi"], 2),
        "time_gap (day)": r["time_gap"],
        "utility_a": r["utilities"][0],
        "project_id_a": r["project_a"],
        "project_name_a": r["name_a"],
        "utility_b": r["utilities"][1],
        "project_id_b": r["project_b"],
        "project_name_b": r["name_b"],
    } for r in rows])[CSV_COLS]
    out = PROC / "overlaps.csv"
    df.to_csv(out, index=False)
    return out


if __name__ == "__main__":
    rs = build_overlaps()
    counts = pd.Series([r["tier"] for r in rs]).value_counts().to_dict()
    print(f"overlaps: {len(rs)} rows {counts}")
    print("wrote", PROC / "overlaps.csv")
