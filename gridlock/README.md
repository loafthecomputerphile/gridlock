# Gridlock

Energy-project overlap explorer: score, map, and brief overlapping utility
transmission/IRP projects (DESC × Georgia Power × Dominion), with an AI pair
brief and a natural-language table query.

**Phase status:** 01–05 + 07 route-aware corridors done — see
[docs/PROJECT-STATE.md](docs/PROJECT-STATE.md) for the phase tracker, locked
decisions, and changelog.

## 30-second demo (single port, offline-capable)

```bash
cd frontend && npm run build   # once — builds the static UI into frontend/dist
cd .. && uv run uvicorn backend.app:app --port 8000
# open http://localhost:8000
```

1. **Ledger** loads ranked pairs (score desc) with the linked map inset —
   click a row → the map frames that pair's tier-limit circle.
2. **Click a pair** → the detail drawer opens: both project cards, nearest
   HIFLD line, and the **AI pair brief** with its status chip (live / cached /
   rate-limited + retry).
3. **Type in the command bar** (bottom): `pairs with 2026 service year, sort
   by score desc` → Enter → the parsed query appears as **chips above the
   table** (source chip says AI or local parser) and the table narrows.
4. Tiers chips / legend toggles / **export CSV** / **HIFLD** toggle as needed.
5. **Offline proof:** with no network (and no API key), the app still loads,
   the table and map work, briefs answer `cached`, and the NL chips answer
   `local` — every chip state is truthful.

No `OPENROUTER_API_KEY`? Everything still runs; briefs degrade to their
`AI unavailable` chip and NL queries fall back to the local keyword parser.
Add the key via env var or `gridlock/.env`, then
`uv run python -m backend.ai.prewarm` to pre-generate top-10 briefs for the
offline demo.

## What's here

- `backend/` — FastAPI app + data pipeline (phases 02–03), AI adapter + endpoints (05)
- `backend/ai/` — provider adapter (OpenRouter, fallback model, disk JSON cache), prompts, briefs, NL query, prewarm
- `frontend/` — Vite / React / TypeScript app (phase 04), served by FastAPI at `/`
- `data/release/` — verbatim copy of the challenge release folder (ground truth)
- `data/processed/` — canonical CSVs/GeoJSON (phase 02), `ai_cache/` (brief/query cache)
- `scripts/` — smoke self-checks (`check_01.py` … `check_05.py`)

```bash
uv sync                      # Python env (3.12)
cd frontend && npm install   # frontend deps
uv run python scripts/check_01.py
```

## AI integration (phase 05)

Two features, both behind a **provider-neutral adapter**
(`backend/ai/adapter.py`) so the provider can be swapped later:

1. **Pair brief** — `POST /api/ai/brief` injects only the pair's own facts
   (names, utilities, distance, tier, score, windows, time gap, confidence,
   geometry basis) into a planner-voice prompt; the model writes 3–4 sentences
   of coordination prose and is told never to invent numbers. The drawer shows
   a status chip: **live / cached / rate-limited / unavailable + Retry**.
2. **NL table query** — `POST /api/ai/query` turns a plain-English request
   into a whitelist-validated `{filters, sort, intent}` JSON that is applied
   server-side to the overlaps table. **Filter/sort/count only** — no SQL, no
   free-form answers, nothing executes; anything outside the column whitelist
   is rejected (422). When the model is down, a local keyword parser produces
   the same shape with `source: local`, and the chips above the table say
   which source parsed them.

Hardening: `OPENROUTER_API_KEY` read from env or `.env` (never committed;
the app runs degraded without it), pinned primary model
`meta-llama/llama-3.3-70b-instruct:free` with fallback to a second free model
on 429/5xx/timeout (2 retries with backoff on 429 only), 15 s timeout, and a
disk JSON cache keyed by `sha256(model + prompt_version + payload)` —
read-first on every call, so the demo is deterministic offline.

## Data provenance (release folder = ground truth)

Every source file under `data/release/` (verbatim copy of the challenge
release folder):

| File | Used for |
|---|---|
| `ShellHacks_Challenge_Gridlock.docx` | challenge outline / scope |
| `Finding_Real_Locations_Guide.docx` | the ONLY location method used (see below) |
| `Projects_Overlaps.xlsx` | starter workbook: 6-row golden fixture + export schema |
| `Project Listings/Dominion Energy/2024-2028-2million-and-above-project-descriptions.pdf` | Dominion 2024–2028 project list (44 pp, PDF extraction) |
| `Project Listings/Georgia Power/2025 IRP Volume 3 PUBLIC DISCLOSURE.pdf` | GPC 2025 IRP Vol. 3 (668 pp, sponsor-column filter) |
| `Opportunities/Software_Engineer_Intern_Listing.docx` | Sperry Tech AI framing (README only) |

Processed outputs and their QA live in `docs/DATA-NOTES.md`.

**CEII:** this build uses **public files only** from the release folder plus
public reference layers (OSM, HIFLD public viewer). **No exact critical-asset
routes are included** — corridor geometry is a planning-level proxy, and
unlocatable projects are excluded rather than guessed.

**Freshness (live cross-check spot):** the release data is the build's data.
During the build, a few sources were re-fetched live as a spot check — OSM
Overpass and the HIFLD service both drift against the release listings
(numbers and drift noted in `docs/DATA-NOTES.md`); the release folder remains
ground truth on any conflict.

## Scoring rule (canonical)

score = tier points (crossing=100, <1.6 km=60, <8 km=40, <40 km=20) + 15 if
build windows overlap, total capped at 100; tie-break by smaller closest-point
distance. Build window = `[in-service year, in-service year + 1]`. All
distance math in EPSG:5070. Time gap is *scored* by year (the window rule
above) and *displayed* as days (`time_gap` = |date A − date B| in days).

**Honesty caveat:** all distances here are **corridor proximity, not surveyed
distance** — separations between planning-level corridor geometries, never
as-built clearances.

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

And the locations themselves are held to the same standard (see
`docs/DATA-NOTES.md` §6): coordinates come **only** from the release
folder's own Finding-guide method — OSM Overpass power-infrastructure name
matches (unique, in the endpoint's hinted state) plus Nominatim hits in that
state, each point reverse-geocode-confirmed. The earlier HIFLD and
state-centroid fallbacks were removed: they were not in the guide, and they
drew the nationwide starburst lines (state centroids as shared hubs) and the
`Square D → Cambridge, MA` point.

**Honest numbers:** **127 of 168 projects are mapped**; the 41 the guide
could not locate are listed in `data/processed/unmapped_projects.csv` and
excluded from the map and pairs — never plotted at a guessed point. Of the
mapped set the snap rate is **74.8 % (95 of 127)**; the rest are disclosed
as buffered estimates rather than forced onto unrelated infrastructure. The
ledger's top pairs are now all plausible SC–GA border projects (Lake
Thurmond, Okatie/Aiken, Savannah area); the old top-ranked 0-distance
"crossings" were geocode artifacts and are gone with the policy change —
documented in `docs/DATA-NOTES.md` §6, not hidden.

**Reference overlay:** the map can also show the national **HIFLD** electric
transmission-lines layer (HIFLD/ORNL via ArcGIS, SC/GA bbox subset cached at
`data/processed/_cache/hifld_lines.geojson`, 6,611 lines) as a toggleable
grey underlay, and each pair's detail drawer links its closest point to the
nearest HIFLD line (`voltage class · owner · distance`). Purely
display + disclosure — it never feeds scoring or endpoint location
(`uv run python backend/fetch_hifld_lines.py` to refresh the cache).

## Why AI, and why this AI (Sperry Tech framing)

Sperry Tech's **AI Department "builds software and machine learning
capabilities for the business"** for its construction-parent company: per the
release intern listing (`data/release/Opportunities/
Software_Engineer_Intern_Listing.docx`), that means **extraction pipelines
from business systems**, **validation and data-quality checks**,
**training-data preparation**, and **document parsing and metadata
extraction**. This app mirrors that exact stack against utility filings: PDF
extraction (668-pp IRP + 44-pp project list → structured rows) → validation
against the starter workbook's golden fixture → **AI-written coordination
briefs** over the validated pairs and a **natural-language query** over the
result table — precisely the challenge's ask to integrate AI where the data
actually is.