"""Phase 03.5 (plan "07") route-aware corridors check. Run: uv run python scripts/check_07.py

Two golden tests, both visible per START-GATE Q3(b):
  LEGACY  — the phase-02 center-point-haversine fixture (starter workbook,
            ±0.1 mi, exact time_gap), asserted against pairs_metrics
            `distance_center_mi`. Kept as the labeled straight-line reference;
            NOT silently dropped.
  ROUTE   — the scored engine distance for the same 6 pairs under route-aware
            geometry, hand-verified (justification per pair below).

Also: geometry_source completeness (all 168, valid enum, no nulls), snap-rate
log, pairs_metrics schema, engine-vs-CSV distance agreement, and a top-10
printout for eyeballing (plan Verify: "eyeball the top 10 ranked pairs").
Exits non-zero (assert) on any failure.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from backend import engine

PROC = ROOT / "data" / "processed"
VALID_SOURCES = {"osm_snapped", "buffered_estimate", "straight_fallback"}

# LEGACY golden (DATA-NOTES §3, starter workbook, center haversine): pair -> (mi, days)
LEGACY_GOLDEN = {
    ("DESC_2", "GPC_1"): (4.09, 3074),
    ("DESC_3", "GPC_2"): (5.65, 152),
    ("DESC_3", "GPC_3"): (7.55, 517),
    ("DESC_1", "GPC_1"): (8.01, 3074),
    ("DESC_5", "GPC_2"): (14.34, 365),
    ("DESC_5", "GPC_3"): (14.81, 730),
}

# ROUTE-aware golden — hand-verified 2026-09-27 against PDF project titles,
# starter-workbook geography and the OSM way tags each corridor snapped to:
#   DESC_2 x GPC_1 0.587 mi: both at Lake Thurmond; DESC_2 point on OSM way
#     9142560 (115 kV, matches "115kV Tie"), GPC_1 on way 52102614 (115 kV,
#     matches "115KV REBUILD"); snap 15 m / 941 m.
#   DESC_3 x GPC_2 3.241 mi: Jasper-Okatie 230 kV on way 185380544 (230 kV),
#     MCINTOSH-PURRYSBURG 230KV on way 1054230281 (230 kV) — voltages match
#     the IRP titles exactly; snap 925 m / 2 m.
#   DESC_3 x GPC_3 3.403 mi: GPC_3 GOSHEN-MCINTOSH 115KV on way 1015932064
#     (115 kV, matches title); snap 643 m.
#   DESC_1 x GPC_1 6.852 mi: DESC_1 is a starter single POINT at Stevens Creek
#     (workbook-verbatim, snapped 35 m to the 46 kV way named in its title).
#   DESC_5 x GPC_2 8.377 mi: DESC_5 snapped to way 185381110 (230 kV vs the
#     project's 115 kV — parallel ROW, snap 1.8 km, caveat noted) ; GPC_2 as above.
#   DESC_5 x GPC_3 8.426 mi: same DESC_5 geom; GPC_3 as above.
# All route distances <= center distances (converging border corridors) and
# every pair stays in a scored tier (none excluded).
ROUTE_GOLDEN = {
    # pair: (route_mi, expected tier)
    ("DESC_2", "GPC_1"): (0.587, "<1.6 km"),
    ("DESC_3", "GPC_2"): (3.241, "<8 km"),
    ("DESC_3", "GPC_3"): (3.403, "<8 km"),
    ("DESC_1", "GPC_1"): (6.852, "<40 km"),
    ("DESC_5", "GPC_2"): (8.377, "<40 km"),
    ("DESC_5", "GPC_3"): (8.426, "<40 km"),
}
MI_M = 1609.344


def check_legacy_golden(pairs: pd.DataFrame) -> None:
    """LEGACY reference test (Q3b): center haversine + time_gap unchanged."""
    idx = {(r.project_id_a, r.project_id_b): r for r in pairs.itertuples()}
    for (a, b), (exp_mi, exp_gap) in LEGACY_GOLDEN.items():
        r = idx.get((a, b)) or idx.get((b, a))
        assert r is not None, f"legacy golden pair {a}x{b} missing from pairs_metrics"
        assert abs(r.distance_center_mi - exp_mi) <= 0.1, \
            f"LEGACY {a}x{b}: center {r.distance_center_mi} vs {exp_mi} (want ±0.1)"
        assert r.time_gap_days == exp_gap, \
            f"LEGACY {a}x{b}: gap {r.time_gap_days} vs {exp_gap} (want exact)"
    print(f"PASS LEGACY golden {len(LEGACY_GOLDEN)}/6 (center haversine ±0.1 mi, "
          "exact time_gap — straight-line reference kept per Q3b)")


def check_route_golden(pairs: pd.DataFrame) -> None:
    """ROUTE-aware golden: scored engine distance + tier, hand-verified values."""
    rows = engine.build_overlaps()  # also rewrites overlaps.csv (same as check_03)
    idx = {(r["project_a"], r["project_b"]): r for r in rows}
    pidx = {(r.project_id_a, r.project_id_b): r for r in pairs.itertuples()}
    for (a, b), (exp_mi, exp_tier) in ROUTE_GOLDEN.items():
        r = idx.get((a, b)) or idx.get((b, a))
        assert r is not None, f"route golden pair {a}x{b} missing from engine rows"
        got_mi = r["distance_m"] / MI_M
        assert abs(got_mi - exp_mi) <= 0.1, \
            f"ROUTE {a}x{b}: {got_mi:.3f} mi vs hand-verified {exp_mi} (want ±0.1)"
        assert r["tier"] == exp_tier, \
            f"ROUTE {a}x{b}: tier {r['tier']} vs expected {exp_tier}"
        # engine scored distance == pairs_metrics route column (same geometry)
        p = pidx.get((a, b)) or pidx.get((b, a))
        assert p is not None, f"{a}x{b} missing from pairs_metrics"
        assert abs(p.distance_m - r["distance_m"]) < 1.0, \
            f"{a}x{b}: pairs_metrics {p.distance_m} m vs engine {r['distance_m']} m"
        # route-aware must not silently exceed the legacy straight-line floor
        # by more than a snap could explain (guards an unrelated-corridor grab)
        assert got_mi <= LEGACY_GOLDEN[(a, b)][0] + 0.1, \
            f"{a}x{b}: route {got_mi:.2f} mi > legacy center {LEGACY_GOLDEN[(a, b)][0]}"
        print(f"  {a} x {b}: route {got_mi:.3f} mi / tier {r['tier']} / score {r['score']} "
              f"(legacy center {LEGACY_GOLDEN[(a, b)][0]} mi)")
    print(f"PASS ROUTE golden {len(ROUTE_GOLDEN)}/6 (hand-verified, engine == CSV)")


def check_geometry_sources() -> None:
    feats = json.loads((PROC / "gridlock_projects.geojson").read_text(encoding="utf-8"))["features"]
    assert len(feats) == 168, f"features = {len(feats)}, want 168"
    counts = dict.fromkeys(VALID_SOURCES, 0)
    for f in feats:
        src = f["properties"].get("geometry_source")
        assert src in VALID_SOURCES, f"{f['properties']['project_id']}: bad geometry_source {src!r}"
        assert f["properties"].get("geometry_basis"), \
            f"{f['properties']['project_id']}: missing geometry_basis"
        assert f["geometry"], f"{f['properties']['project_id']}: missing geometry"
        assert f["properties"].get("center_lat") is not None, \
            f"{f['properties']['project_id']}: missing legacy center prop"
        counts[src] += 1
    n = len(feats)
    rate = 100 * counts["osm_snapped"] / n
    print(f"PASS geometry_source on all {n} rows (no nulls): {counts} — "
          f"snap rate {rate:.1f}% (log for README; low rate = finding, not failure)")
    # the golden set is starter-workbook ground truth — all 6 must be grounded
    # (any of the three sources is disclosed; assert none silently null above)


def check_pairs_schema(pairs: pd.DataFrame) -> None:
    want = {"project_id_a", "project_id_b", "distance_m",
            "distance_m_legacy_straightline", "distance_center_mi", "time_gap_days"}
    assert want <= set(pairs.columns), f"pairs_metrics missing {want - set(pairs.columns)}"
    assert pairs["distance_m"].notna().all(), "null route distance"
    assert pairs["distance_m_legacy_straightline"].notna().all(), "null legacy distance"
    assert (pairs["distance_m"] >= 0).all() and (pairs["distance_m_legacy_straightline"] >= 0).all()
    print(f"PASS pairs_metrics schema ({len(pairs)} rows; route + legacy + center columns, no nulls)")


def print_top10() -> None:
    rows = engine.build_overlaps()[:10]
    src = {f["properties"]["project_id"]: f["properties"]["geometry_source"]
           for f in json.loads((PROC / "gridlock_projects.geojson").read_text(encoding="utf-8"))["features"]}
    print("top 10 ranked pairs (eyeball: sources, distances, tiers — plan Verify):")
    for r in rows:
        print(f"  #{r['rank']:>2} {r['project_a']}({src[r['project_a']][:4]}) x "
              f"{r['project_b']}({src[r['project_b']][:4]}) "
              f"{r['distance_m'] / MI_M:6.3f} mi tier={r['tier']:<8} score={r['score']} "
              f"{r['name_a'][:32]!r} x {r['name_b'][:32]!r}")


def main() -> None:
    pairs = pd.read_csv(PROC / "pairs_metrics.csv")
    check_legacy_golden(pairs)
    check_route_golden(pairs)
    check_geometry_sources()
    check_pairs_schema(pairs)
    print_top10()
    print("ALL CHECKS PASS")


if __name__ == "__main__":
    main()