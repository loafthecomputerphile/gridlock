"""Phase 06 bonus (A) self-check. Run: uv run python scripts/check_06_bonus.py

Golden pair recomputes shared-ROW acres by hand (literal arithmetic, not the
engine function) within 1%; width linearity; crossing (d=0) -> 0 acres.
Exits non-zero (assert) on any failure; prints PASS per check.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.engine import build_overlaps  # noqa: E402

rows = build_overlaps()
rank1 = rows[0]

# --- golden: hand-recompute rank-1 pair at the 150 ft default width ---
d_m = rank1["distance_m"]
length_mi = d_m / 1609.344
acres_hand = 150.0 * length_mi * 5280.0 / 43560.0  # width_ft x 5280 / 43560 per mile
got = rank1["est_shared_row_acres"]
assert abs(got - acres_hand) <= 0.01 * acres_hand, (
    f"rank1 {rank1['overlap_id']}: engine {got} vs hand {acres_hand:.6f} >1%")
print(f"PASS golden {rank1['overlap_id']}: acres {got} == hand {acres_hand:.6f} (within 1%)")

# --- acres scale linearly with ROW width (UI rescales engine value this way;
# engine stores 3 decimals, so allow that rounding slack) ---
assert abs(rank1["est_shared_row_acres"] * (100.0 / 150.0)
           - 100.0 * length_mi * 5280.0 / 43560.0) < 5e-4, "width scaling not linear"
print("PASS width linearity (100 ft = engine x 100/150)")

# --- crossing pair (d=0) -> 0 acres when any exist; no NaN anywhere ---
crossings = [r for r in rows if r["tier"] == "crossing"]
if crossings:
    assert all(r["est_shared_row_acres"] == 0.0 for r in crossings), "crossing acres != 0"
assert all(r["est_shared_row_acres"] == r["est_shared_row_acres"] for r in rows), "NaN acres"
# every acre value must equal its own hand-recompute (formula holds for all tiers)
for r in rows:
    hand = 150.0 * (r["distance_m"] / 1609.344) * 5280.0 / 43560.0
    assert abs(r["est_shared_row_acres"] - hand) <= max(5e-4, 0.01 * hand), r["overlap_id"]
print(f"PASS {len(crossings)} crossing pairs -> 0.0 acres; all {len(rows)} rows match hand recompute; no NaN")

print("check_06_bonus: PASS")