"""Phase 03 smoke self-check. Run: uv run python scripts/check_03.py

Boots the app via TestClient (golden asserted THROUGH the API path), checks
tier/score boundary cases, tie-break order, CSV export contract, and the
rank invariant. Exits non-zero (assert) on any failure; prints PASS per check.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from fastapi.testclient import TestClient

from backend import engine
from backend.app import app

REL = ROOT / "data" / "release"
PROC = ROOT / "data" / "processed"

# golden fixture (DATA-NOTES §3): pair -> (distance_mi, time_gap_days)
GOLDEN = {
    ("DESC_2", "GPC_1"): (4.09, 3074),
    ("DESC_3", "GPC_2"): (5.65, 152),
    ("DESC_3", "GPC_3"): (7.55, 517),
    ("DESC_1", "GPC_1"): (8.01, 3074),
    ("DESC_5", "GPC_2"): (14.34, 365),
    ("DESC_5", "GPC_3"): (14.81, 730),
}


def main() -> None:
    c = TestClient(app)

    r = c.get("/api/health")
    assert r.status_code == 200, f"health {r.status_code}"
    h = r.json()
    assert h["status"] == "ok" and "overlaps.csv" in h["data_files"], h
    print(f"PASS health 200 (phases_done={h['phases_done']}, {len(h['data_files'])} data files)")

    r = c.get("/api/projects")
    assert r.status_code == 200, f"projects: {r.status_code}"
    # guide-only policy: API serves located projects only; total comes from health
    assert h["projects_total"] == 168, f"projects_total = {h['projects_total']}"
    assert len(r.json()) == h["projects_located"], (
        f"/api/projects {len(r.json())} vs health projects_located {h['projects_located']}")
    assert h["projects_located"] <= h["projects_total"]
    print(f"PASS /api/projects ({h['projects_located']} located of "
          f"{h['projects_total']} total — unmapped excluded)")

    rows = c.get("/api/overlaps").json()
    idx = {(x["project_a"], x["project_b"]): x for x in rows}
    for (a, b), (exp_mi, exp_gap) in GOLDEN.items():
        x = idx.get((a, b)) or idx.get((b, a))
        assert x, f"golden pair {a}x{b} missing from /api/overlaps"
        assert abs(x["distance_center_mi"] - exp_mi) <= 0.1, \
            f"{a}x{b}: center {x['distance_center_mi']} vs {exp_mi} (want ±0.1)"
        assert x["time_gap"] == exp_gap, \
            f"{a}x{b}: time_gap {x['time_gap']} vs {exp_gap} (want exact)"
        assert x["tier"] != "excluded", f"{a}x{b} landed in excluded"
        print(f"  {x['overlap_id']} {a}x{b}: {x['distance_center_mi']} mi / "
              f"{x['time_gap']} d (want {exp_mi}±0.1 / {exp_gap})")
    print("PASS golden 6/6 via API")

    # tier boundaries (plan: strict <, inclusion <= 40 km)
    T = engine.tier_for
    assert T(0) == ("crossing", 100)
    assert T(1599)[0] == "<1.6 km" and T(1599)[1] == 60
    assert T(1600)[0] == "<8 km" and T(1600)[1] == 40
    assert T(7999)[0] == "<8 km" and T(7999)[1] == 40
    # plan Task C said d=8000→<8, but Task A's table is strict (`d < 8000`) —
    # strict table governs (user-confirmed mid-phase fork, logged in 00 §6)
    assert T(8000) == ("<40 km", 20)
    assert T(40000)[0] == "<40 km" and T(40000)[1] == 20
    assert T(40001) == ("excluded", 0)
    print("PASS tier boundaries (0/1599/1600/7999/8000/40000/40001, strict <8000)")

    # score cases
    assert engine.score_for(100, None) == 100    # crossing + no window
    assert engine.score_for(100, 2026) == 100    # cap at 100
    assert engine.score_for(20, 2026) == 35      # <40 km + window overlap
    assert engine.score_for(20, None) == 20      # <40 km, no window
    print("PASS score cases (cap 100, <40+window=35)")

    # tie-break: score desc, then smaller closest-point distance
    t = [{"score": 40, "distance_m": 900.0},
         {"score": 40, "distance_m": 500.0},
         {"score": 60, "distance_m": 9999.0}]
    assert [r["distance_m"] for r in engine.sort_overlaps(t)] == [9999.0, 500.0, 900.0]
    print("PASS tie-break (score desc, distance asc)")

    # excluded exemplars per START-GATE 03-1
    ex = [x for x in rows if x["tier"] == "excluded"]
    assert len(ex) == engine.EXEMPLARS, f"excluded exemplars = {len(ex)}, want {engine.EXEMPLARS}"
    print(f"PASS excluded exemplars ({len(ex)} rows, all > 40 km)")

    # invariant: no excluded pair ranked above any crossing pair
    tiers = [x["tier"] for x in rows]
    if "crossing" in tiers and "excluded" in tiers:
        last_x = max(i for i, t in enumerate(tiers) if t == "crossing")
        first_e = min(i for i, t in enumerate(tiers) if t == "excluded")
        assert last_x < first_e, "excluded pair ranked above a crossing pair"
    print(f"INVARIANT ok: no far-same-year pair above any crossing pair ({len(rows)} rows)")

    # CSV export contract == starter header, same rows as API
    want_hdr = pd.read_excel(next(REL.rglob("Projects_Overlaps.xlsx")),
                              sheet_name="overlaps").columns.tolist()
    r = c.get("/api/export/overlaps.csv")
    assert r.status_code == 200, r.status_code
    got_hdr = r.text.splitlines()[0].split(",")
    assert got_hdr == want_hdr, f"CSV header {got_hdr} != starter {want_hdr}"
    disk_hdr = (PROC / "overlaps.csv").read_text(encoding="utf-8").splitlines()[0].split(",")
    assert disk_hdr == want_hdr, "on-disk overlaps.csv header != starter header"
    assert len(r.text.splitlines()) - 1 == len(rows), "CSV rows != API rows"
    print(f"PASS CSV header == starter header ({len(rows)} rows, API == disk)")

    print("ALL CHECKS PASS")


if __name__ == "__main__":
    main()
