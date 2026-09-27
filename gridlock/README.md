# Gridlock

Energy-project overlap explorer: score, map, and brief overlapping utility transmission/IRP projects (DESC × Georgia Power × Dominion).

**Phase status:** 01 foundation — see [docs/PROJECT-STATE.md](docs/PROJECT-STATE.md) for the phase tracker, locked decisions, and changelog.

## Layout

- `backend/` — FastAPI app + data pipeline (phases 02–03)
- `frontend/` — Vite / React / TypeScript app (phase 04)
- `data/release/` — verbatim copy of the challenge release folder (ground truth)
- `data/processed/` — canonical CSVs/GeoJSON (phase 02)
- `scripts/` — smoke self-checks (`check_01.py`, …)

## Quick start

```bash
uv sync                      # Python env (3.12)
cd frontend && npm install   # frontend deps
uv run python scripts/check_01.py
```

## How we solved the straight-line problem

The challenge brief names the core data gap: *"many features are effectively
straight-line corridor sketches, and existing ≠ planned."* Most published
planned-corridor layers are just two dots joined by a line — the true route is
unknown. This build does not ship that as-is:

1. **Pull real infrastructure.** One free, credential-less query against the
   OSM Overpass API brings in the existing transmission network for the SC/GA
   territory: **15,810 `power=line` ways**, 5,315 substations (183,554 tower
   nodes counted and dropped from the cache — unused by the snap). Cached at
   `data/processed/_cache/overpass_power.json` so the build stays reproducible
   offline.
2. **Snap where infrastructure exists.** Each project corridor attempts to
   snap to the nearest real `power=line` way that lies within **10 km of both
   endpoints**; the corridor geometry becomes the segment of that actual
   power line between the two projections — a routing proxy, not a straight
   sketch. Heuristic guards reject degenerate snaps (both endpoints collapsing
   to one crossing, or a detour longer than 2× the straight shot + buffer).
3. **Buffer where it doesn't.** With no OSM line within 10 km, the straight
   estimate is kept but explicitly downgraded: `buffered_estimate` carries a
   declared **10 km uncertainty buffer**, and single-point projects become
   `straight_fallback`. Nothing is silently upgraded.
4. **Disclose the grounding per project.** Every project carries a
   `geometry_source` tag — `osm_snapped` / `buffered_estimate` /
   `straight_fallback` — shown in the map legend (with live counts) and the
   detail drawer, so a viewer can see exactly which corridors are grounded in
   real infrastructure.
5. **Score the route-aware geometry directly.** Pair distance is now the
   EPSG:5070 **polyline-to-polyline** separation between corridor geometries,
   feeding the same locked tier thresholds (crossing / 1.6 / 8 / 40 km + 15-pt
   window) with no hidden confidence multiplier. The old straight-line
   distance is kept as `distance_m_legacy_straightline` in `pairs_metrics.csv`
   for traceability, and the starter-workbook golden test survives unchanged
   as a labeled legacy reference next to the new route-aware golden
   (`scripts/check_07.py`) — nothing was silently replaced.

**Honest numbers:** the snap rate is **62.5 % (105 of 168 projects)**; the
rest are disclosed as buffered/fallback rather than forced onto unrelated
infrastructure. Snapped geometry produced **zero** spurious crossing pairs.
The ledger's top-ranked crossings all come from two pre-existing geocode
misses from the phase-02 ingest (`Square D` matched to Cambridge, MA — labeled
*unconfirmed*; `Killian` ~150 km off) whose straight lines now run across the
map — visible, labeled `buffered_estimate`, and documented in
`docs/DATA-NOTES.md` §5 as a finding, not hidden.
