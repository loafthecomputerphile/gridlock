"""Phase 02 smoke self-check (golden test). Run: uv run python scripts/check_02.py

Reads the starter xlsx DIRECTLY (independent of ingest), recomputes the 6 golden
overlap rows via center-point haversine, then validates build outputs.
Exits non-zero (assert) on any failure; prints PASS per check.
"""
import json
import math
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
REL = ROOT / "data" / "release"
PROC = ROOT / "data" / "processed"
R_MI = 3958.7613
KM40_MI = 40 / 1.609344

# golden fixture (DATA-NOTES §3): pair -> (distance_mi, time_gap_days)
GOLDEN = {
    ("DESC_2", "GPC_1"): (4.09, 3074),
    ("DESC_3", "GPC_2"): (5.65, 152),
    ("DESC_3", "GPC_3"): (7.55, 517),
    ("DESC_1", "GPC_1"): (8.01, 3074),
    ("DESC_5", "GPC_2"): (14.34, 365),
    ("DESC_5", "GPC_3"): (14.81, 730),
}


def hav_mi(la1, lo1, la2, lo2):
    a = (math.sin(math.radians(la2 - la1) / 2) ** 2
         + math.cos(math.radians(la1)) * math.cos(math.radians(la2))
         * math.sin(math.radians(lo2 - lo1) / 2) ** 2)
    return 2 * R_MI * math.asin(math.sqrt(a))


def to_date(v) -> date:
    """text '12/31/2024' / '2025-06-01', datetime, or Excel serial (origin 1899-12-30)."""
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.date() if isinstance(v, datetime) else v.to_pydatetime().date()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (datetime(1899, 12, 30) + pd.to_timedelta(float(v), unit="D")).date()
    s = str(v).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable starter date: {v!r}")


def check_golden_rows() -> None:
    xl = next(REL.rglob("Projects_Overlaps.xlsx"))
    projects = pd.read_excel(xl, sheet_name="projects").set_index("project_id")
    ovl = pd.read_excel(xl, sheet_name="overlaps")
    assert len(ovl) == 6, f"starter overlaps = {len(ovl)}, want 6"

    print("golden fixture (starter xlsx, center haversine):")
    worst_mid, worst_5070 = 0.0, 0.0
    to5070 = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    for _, row in ovl.iterrows():
        a, b = row["project_id_a"], row["project_id_b"]
        pa, pb = projects.loc[a], projects.loc[b]
        # midpoint-vs-workbook-center agreement
        for p in (pa, pb):
            if pd.notna(p["lat_a"]) and pd.notna(p["lat_b"]):
                mid_la = (float(p["lat_a"]) + float(p["lat_b"])) / 2
                mid_lo = (float(p["lon_a"]) + float(p["lon_b"])) / 2
                worst_mid = max(worst_mid, hav_mi(mid_la, mid_lo,
                                                  float(p["lat_center"]), float(p["lon_center"])))
        got = hav_mi(float(pa["lat_center"]), float(pa["lon_center"]),
                     float(pb["lat_center"]), float(pb["lon_center"]))
        got_gap = abs((to_date(pa["in_service_date"]) - to_date(pb["in_service_date"])).days)
        exp_mi, exp_gap = GOLDEN[(a, b)]
        assert abs(got - exp_mi) <= 0.1, f"{a}x{b}: {got:.2f} vs {exp_mi} (want ±0.1)"
        assert got_gap == exp_gap, f"{a}x{b}: gap {got_gap} vs {exp_gap} (want exact)"
        # sheet distance vs ours; EPSG:5070 vs haversine informational
        sheet_mi = float(row["distance_mi"])
        x1, y1 = to5070.transform(float(pa["lon_center"]), float(pa["lat_center"]))
        x2, y2 = to5070.transform(float(pb["lon_center"]), float(pb["lat_center"]))
        d5070 = math.hypot(x2 - x1, y2 - y1) / 1609.344
        worst_5070 = max(worst_5070, abs(d5070 - got))
        print(f"  {row['overlap_id']} {a}x{b}: want {exp_mi:.2f} mi/{exp_gap} d "
              f"got {got:.2f} mi/{got_gap} d (sheet {sheet_mi:.2f}, 5070 {d5070:.2f})")
    assert worst_mid <= 0.01, f"midpoint vs workbook center off by {worst_mid:.3f} mi"
    print(f"PASS golden 6/6 (midpoint vs lat_center max {worst_mid:.3f} mi; "
          f"EPSG:5070 vs haversine delta {worst_5070:.3f} mi informational)")


def check_outputs() -> None:
    for f in ("projects.csv", "gazetteer.csv", "gridlock_projects.geojson", "pairs_metrics.csv"):
        assert (PROC / f).exists(), f"missing output: {f}"

    proj = pd.read_csv(PROC / "projects.csv")
    n_desc = int((proj["utility"].str.contains("Dominion", case=False, na=False)).sum())
    n_gpc = int((proj["utility"] == "Georgia Power").sum())
    assert n_desc == 44, f"DESC rows = {n_desc}, want 44"
    assert 117 <= n_gpc <= 127, f"GPC rows = {n_gpc}, want 122±5"
    assert proj["source_file"].notna().all(), "row(s) missing source_file"
    assert proj["project_id"].is_unique, "duplicate project_id"
    print(f"PASS projects.csv ({len(proj)} rows; DESC={n_desc}, GPC={n_gpc} exact)")

    gaz = pd.read_csv(PROC / "gazetteer.csv")
    assert gaz["confidence"].isin(["confirmed", "likely", "unconfirmed"]).all(), \
        "gazetteer row missing/invalid confidence"
    assert gaz["endpoint_name"].is_unique, "duplicate endpoint_name"
    print(f"PASS gazetteer.csv ({len(gaz)} endpoints, all confidence-labeled)")

    feats = json.loads((PROC / "gridlock_projects.geojson").read_text())["features"]
    # guide-only policy (DATA-NOTES §6): unmapped projects have no feature
    unm_path = PROC / "unmapped_projects.csv"
    n_unmapped = len(pd.read_csv(unm_path)) if unm_path.exists() else 0
    assert len(feats) + n_unmapped == len(proj), (
        f"geojson {len(feats)} + unmapped {n_unmapped} != projects {len(proj)}")
    fids = {f["properties"]["project_id"] for f in feats}
    starter10 = [f"DESC_{i}" for i in range(1, 6)] + [f"GPC_{i}" for i in range(1, 6)]
    missing = [s for s in starter10 if s not in fids]
    assert not missing, f"starter projects missing from geojson: {missing}"
    assert all(f["properties"].get("geometry_basis") for f in feats), \
        "feature missing geometry_basis"
    assert all(f["geometry"] for f in feats), "feature missing geometry"
    print(f"PASS geojson ({len(feats)} features + {n_unmapped} unmapped = {len(proj)}; "
          "all geometry_basis present, starter projects mapped)")

    pairs = pd.read_csv(PROC / "pairs_metrics.csv")
    idx = {(r.project_id_a, r.project_id_b): r for r in pairs.itertuples()}
    for (a, b), (exp_mi, exp_gap) in GOLDEN.items():
        r = idx.get((a, b))
        assert r is not None, f"golden pair {a}x{b} missing from pairs_metrics"
        assert abs(r.distance_center_mi - exp_mi) <= 0.1, \
            f"{a}x{b}: pairs_metrics center {r.distance_center_mi} vs {exp_mi}"
        assert r.time_gap_days == exp_gap, \
            f"{a}x{b}: pairs_metrics gap {r.time_gap_days} vs {exp_gap}"
    assert (pairs["distance_center_mi"] < KM40_MI).any() or \
           (pairs["distance_closest_mi"] < KM40_MI).any(), "pairs filter kept nothing"
    print(f"PASS pairs_metrics.csv ({len(pairs)} pairs; 6 golden pairs match within ±0.1)")


if __name__ == "__main__":
    check_golden_rows()
    check_outputs()
    print("ALL CHECKS PASS")
