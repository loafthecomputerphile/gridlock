# DATA NOTES (phase 02)

Ground truth = `data\release\` (verbatim copy of `research\Sperry-Tech-Challenge\`).

## 1. Guide method (`Finding_Real_Locations_Guide.docx`, read in full)

- **Center point** = midpoint of the project's two named sub-points; if only one point is located, that point IS the center. Workbook formula: `IF(ISBLANK(b), a, IF(ISBLANK(a), b, (a+b)/2))`.
- **Overlap** = center-to-center **haversine < 25 mi (40,234 m)** — straight-line only, no driving distance.
- **`time_gap`** = |in_service_date_a − in_service_date_b| in **days** (exact integer). Scoring still uses years (00 §2).
- **Verification loop**: re-read the PDF description/zone/landmarks for each match → confirmed, or flag **lower-confidence**.
- **Geocode**: Overpass template `nwr["power"="substation"]["operator"~"YOUR_UTILITY_NAME",i](SOUTH,WEST,NORTH,EAST);` at overpass-turbo.eu (`substation`→`line` for lines); also Nominatim / Open Infrastructure Map. **Scale-up tip:** query ALL of a utility's tagged infrastructure at once → one GeoJSON per utility → filter to the project list.
- The guide's method overrides anything guessed elsewhere.

## 2. Starter workbook `Projects_Overlaps.xlsx` — exact columns (CSV export contract, phase 03)

**Sheet `projects` (10 rows × 17 cols):**
`project_id, utility, state, project_name, name_a, lat_a, lon_a, name_b, lat_b, lon_b, lat_center, lon_center, in_service_date, overlap_count, overlap_1, overlap_2, overlap_3`
- `overlap_N` holds the counterpart **project_id** (not an OVL id).
- `in_service_date` mixes formats: text `12/31/2024`, text `2025-06-01`, and datetime objects (`6/1/2033`, `2025-05-01`). Excel serials also possible (`45809` = 2025-06-01, `45778` = 2025-05-01) — parser must handle all.

**Sheet `overlaps` (6 rows × 9 cols):**
`overlap_id, distance_mi, time_gap (day), utility_a, project_id_a, project_name_a, utility_b, project_id_b, project_name_b`

## 3. Golden fixture (±0.1 mi, center-point haversine; time_gap exact)

| overlap | pair | distance_mi | time_gap (day) |
|---|---|---|---|
| OVL_1 | DESC_2 × GPC_1 | 4.09 | 3074 |
| OVL_2 | DESC_3 × GPC_2 | 5.65 | 152 |
| OVL_3 | DESC_3 × GPC_3 | 7.55 | 517 |
| OVL_4 | DESC_1 × GPC_1 | 8.01 | 3074 |
| OVL_5 | DESC_5 × GPC_2 | 14.34 | 365 |
| OVL_6 | DESC_5 × GPC_3 | 14.81 | 730 |

## 4. Ingest notes (filled during phase 02 build)

**DESC PDF (44 pp, all parsed, assert 44):**
- Dashes: source uses `` (U+FFFD) and `` (U+F8FF) inside endpoint names — replaced with `" - "` before splitting.
- Phased dates: `'10/1/2025 (phase 1) and 10/1/2026 (phase 2)'` → extract-first regex, take phase 1 (earliest = first in-service); raw kept in notes.
- 2-digit years (`'12/31/23'`) → `%m/%d/%y`.
- p14/p15 near-duplicate titles differ only by a trailing "Rebuilds" suffix — both kept (distinct rows in source).
- `&` multi-corridor titles: first corridor only (ponytail ceiling).
- 3-part titles: `A - B - C` → endpoints A / B (first dash split wins).

**GPC 2025 IRP Vol.3, Table 2 (pages 177–191, 208 rows parsed, 0 unparsed):**
- Layout: row line = `zone year teams# name-part1 date sponsor REDACTED×5`; the name's **wrapped remainder appears on subsequent lines AFTER the date/sponsor/REDACTED run** — joined back onto name-part1 at finalize (verified: all 5 starter names reconstruct byte-exact).
- Guards: stray `(\d{3}\s+…` sponsor-cell artifact lines matching `^\([A-Z]{2,4}\)$` skipped; malformed zone-less rows (e.g. p191 `215 20266 GTC: …`) containing REDACTED but not matching the row regex skipped.
- Sponsors: GPC 122, GTC 54, SAV 16, MEAG 14, DU 2. Kept = **124** (sponsor=GPC 122 **+ starter rows GPC_2/GPC_3 which carry sponsor=SAV** in Table 2 — workbook is ground truth), dropped 84.
- Costs all REDACTED in source → `cost_usd` empty; `raw_date` preserved in notes.

**Starter workbook fidelity:** the 10 starter rows (5 DESC + 5 GPC) keep workbook endpoint names, per-row coords, centers (`_center`), and dates **verbatim** (only bit-faithful choice: MCINTOSH has dual coords per side of the line; blank starter endpoints — Hooks Sub, PURRYSBURG, Ft Johnson — stay blank, never live-geocoded into the row).

**Geocode / live drift:**
- HIFLD bbox rows: **6504** (plan est ~4019) · Overpass named substations: **1866** (plan est ~5587) — live drift.
- Okatie–Bluffton cross-check (plan predicted a discrepancy): **no discrepancy observed**.
- `QA BUG: GOSHEN vs live layer ~87 mi` — starter seed vs live OSM-name collision; starter coords win per verbatim rule, printed for manual eyeball.
- Ungeocodeable fallback: START-GATE said "county centroid" — county not derivable from endpoint names alone → **state centroid** + `unconfirmed` label (mechanical deviation).
- EIA 860M cross-ref skipped (mechanical: no registry in release folder; Overpass+HIFLD+Nominatim cover it).
- folium debug map skipped → numeric sanity instead (QA BUG prints + non-confirmed eyeball list) — mechanical, 24h clock.
- Nominatim: 1 req/s explicit sleep per call (geopy has no per-call delay kwarg), 3-try backoff, state-regex check, singleton client.

**Outputs** (`data/processed/`): `projects.csv` (15 cols), `gazetteer.csv` (7 cols), `gridlock_projects.geojson` (geometry_basis on every feature), `pairs_metrics.csv` (pair fields `distance_center_mi, distance_closest_mi, time_gap_days`; dropped `min(center, closest) ≥ 40 km` — no tighter prefilter, 44×122 pairs is cheap).

**Final build stats (check_02 ALL PASS):** 168 projects (DESC=44, GPC=124), 205 gazetteer endpoints — 109 confirmed / 59 likely / 37 unconfirmed (sources: nominatim 62, hifld 55, overpass 47, state-centroid 27, starter 14), 211 pairs, 168 geojson features. Golden 6/6 exact ±0.1 mi and exact time_gap; midpoint-vs-`lat_center` max deviation 0.000 mi; EPSG:5070 vs haversine delta ≤0.046 mi (informational).

## 5. Route-aware corridors (phase 03.5 / plan "07")

**Method** (`backend/build_routes.py`, START-GATE answers Q1=c snap+buffer · Q2=10 km · Q3=b legacy+new golden · Q4=direct feed, no multiplier):

- **Overpass pull** (one query, cached `_cache/overpass_power.json`, 28.1 MB):
  204,679 elements — 15,810 `power=line` ways + 183,554 `power=tower` nodes +
  5,315 substations. Towers are counted but **pruned from the cache** after the
  pull (unused by snapping; keeps the repo sane) — mechanical, noted here.
- **Snap rule:** nearest `power=line` way within **10 km of both endpoints**
  (min summed endpoint distance wins); geometry = `substring(way,
  project(a), project(b))` in EPSG:5070. Guards: reject if snapped length
  < 0.5 × straight length (both endpoints collapsed onto one crossing) or
  > 2 × straight length + 10 km (unrelated detour). Single-way proxy — no
  multi-way pathfinding (documented ceiling).
- **Result:** `osm_snapped` **105 (62.5 %)**, `buffered_estimate` 59,
  `straight_fallback` 4 — all 168 tagged, no nulls. Buffer is a declared
  uncertainty band (`buffer_m` prop), not a score modifier (Q4).
- **Legacy preservation:** the phase-02 straight geojson is cached once at
  `_cache/gridlock_projects_straight.geojson`; `distance_m_legacy_straightline`
  (old closest-point column, now meters) recomputes from it, and
  `center_lat`/`center_lon` props pin the guide/center-golden metric so
  snapping can never move the workbook centers. `pairs_metrics.csv`: 211 rows
  (same set — inclusion = min(center, legacy, route) < 40 km).

**Golden handling (Q3b):** both tests live in `scripts/check_07.py` —
LEGACY (center haversine ±0.1 mi, exact gap, unchanged) and ROUTE (engine
distance for the same 6 pairs: 0.587 / 3.241 / 3.403 / 6.852 / 8.377 /
8.426 mi). Hand-verification basis per pair is in the check's header comment:
snapped-way voltage tags vs the PDF/IRP project titles (115/230/46 kV all
match), snap distances 1.8 m–1.8 km, route ≤ center for every pair, none
excluded. One caveat logged: **DESC_5** (115 kV) snapped to a 230 kV-tagged
way (parallel ROW, 1.8 km snap).

**Finding (eyeball, plan Verify):** all 34 `crossing` rows are
`buffered_estimate × buffered_estimate` — **zero involve snapped geometry** —
and they pre-date this phase (the identical pairs are 0.0 m in the cached
straight geojson). Root cause is phase-02 geocode debt: `Square D`
(Nominatim, *unconfirmed*) → Cambridge, MA, making DESC_16 a 1,777 km line
(9 crossings); `Killian` (~150 km off, *likely*) making DESC_13 a 204 km line
(2 crossings). Disclosed in README; not silently fixed (phase-02
automated-QA answer stands — fix requires user direction).
