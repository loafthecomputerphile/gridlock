"""Map line correctness spot-check. Run: uv run python scripts/check_map_lines.py

Verifies the corridor segments the map draws are geometrically honest:
every row is a 2-point LineString, sampled endpoints sit on the claimed
project corridor geoms, segment length matches the scored distance, and
tier labels agree with engine.tier_for. Exits non-zero (assert) on failure.
(check_05.py is reserved for phase 05 — hence this name.)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import geopandas as gpd
import shapely
from pyproj import Transformer

from backend import engine

TOL = 1.0  # meters


def main() -> None:
    rows = engine.build_overlaps()  # rewrites overlaps.csv deterministically (same as check_03)
    assert len(rows) >= 200, f"too few rows: {len(rows)}"
    print(f"PASS {len(rows)} rows")

    for r in rows:
        g = r["shortest_line"]
        assert g["type"] == "LineString", f"{r['overlap_id']}: not a LineString"
        assert len(g["coordinates"]) == 2, f"{r['overlap_id']}: {len(g['coordinates'])} coords"
    print("PASS all rows are 2-point LineStrings")

    gdf = gpd.read_file(ROOT / "data" / "processed" / "gridlock_projects.geojson").to_crs(5070)
    corridors = dict(zip(gdf["project_id"], gdf.geometry))
    to5070 = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)

    by_tier: dict[str, list[dict]] = {}
    for r in rows:
        by_tier.setdefault(r["tier"], []).append(r)
    sample = [r for rs in by_tier.values() for r in rs[:5]]

    for r in sample:
        assert r["tier"] == engine.tier_for(r["distance_m"])[0], (
            f"{r['overlap_id']}: tier {r['tier']} != tier_for({r['distance_m']})"
        )
        if r["tier"] == "crossing":
            assert r["distance_m"] == 0, f"{r['overlap_id']}: crossing but {r['distance_m']} m"

        pts = [shapely.Point(to5070.transform(x, y)) for x, y in r["shortest_line"]["coordinates"]]
        seg_len = pts[0].distance(pts[1])
        assert abs(seg_len - r["min_distance_km"] * 1000) < TOL, (
            f"{r['overlap_id']}: segment {seg_len:.3f} m vs claimed {r['min_distance_km'] * 1000:.3f} m"
        )
        # each endpoint must sit on one of the two claimed corridors
        # (order-tolerant: shortest_line emits [on A, on B], but verify both)
        ga, gb = corridors[r["project_a"]], corridors[r["project_b"]]
        d_ab = ga.distance(pts[0]) + gb.distance(pts[1])
        d_ba = ga.distance(pts[1]) + gb.distance(pts[0])
        assert min(d_ab, d_ba) < 2 * TOL, (
            f"{r['overlap_id']}: endpoints off corridor geoms (d={min(d_ab, d_ba):.3f} m)"
        )

    print(f"PASS sample {len(sample)} rows across {len(by_tier)} tiers "
          f"(endpoints on corridors, length == distance, tier == tier_for)")
    print("ALL CHECKS PASS")


if __name__ == "__main__":
    main()
