# 00 — PROJECT STATE (anti-drift anchor)

**This file is the single source of truth for intent, decisions, and history. Every phase READS this file first and WRITES a changelog entry before it finishes. Dual location: this copy (plans home) is canonical; a synced copy lives at `hackathon\gridlock\docs\PROJECT-STATE.md` after each phase ends. On conflict: this copy wins → halt and ask the user.**

---

## 1. Original Intent (LOCKED — amend only by asking the user)

> "the data is out now. look in this folder. update the report using this folder as the main data source. `C:\Users\drewq\Documents\code\hackathon\research\Sperry-Tech-Challenge` use the other ones found if you want. so use this, the md file just made and the data found in your last run to make a folder with detailed numbered phase plans to give to claude code to complete this challenge. we will be using UI Example 3. the challege organisers want us to integrate AI. SPerry tech uses ai for the software they make for their parent construction company so we NEED that in there. look up what types of AI Sperry Tech uses and what AI can do for us here and ask questions suggesting models we use and and where to integrate them. with these plans you should place them 1 dir up. use nextlevelbuilder/ui-ux-pro-max-skill for the UI when yiu get to that. also for this: 'but many features are effectively straight-line corridor sketches, and existing ≠ planned: no base layer shows the future projects; only the PDF lists do.' can we just create our own layer if we have some sort of geo location still. ask us a lot of questions when making this plan and force phases to ask us questions too. make each phase update a central MD file and refer to that after each major update so each phase know what has happened in the past and what to do to still adhere to our intent if we kinda veered off trach for some reason"

**Deliverable of the planning session (done):** reconciled report `research\gridlock-evaluation.md` + this phase-plans folder. **Deliverable of the build (this folder drives):** the Gridlock app in `hackathon\gridlock\` completing phases 01–05, stretch 06.

**If you feel the build veering off track: STOP, re-read §1, and ask the user. Do not self-correct by inventing new direction.**

---

## 2. Locked Decisions (49 — do NOT re-ask; ask only what a phase's START-GATE lists)

### Logistics & governance
- Plans live at `hackathon\phase-plans\` (one dir up from `research\`); app repo at `hackathon\gridlock\`.
- Deadline: **under 24 hours** → relative clock **T+0..24h** (T+0 = build kickoff; budgets per phase below).
- One session, sequential phases, solo (subagents only for isolated read-only lookups).
- Git: single branch `main`; **commit per phase**; commit messages end `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
- State file dual-location: this home file = source of truth; copy to `gridlock\docs\PROJECT-STATE.md` at each phase end (sync rule §5).
- Release data copied into `gridlock\data\release\` (folder = ground truth for the build).
- Question cadence: **2–4 AskUserQuestion items at every phase open** (START-GATE), plus ask again before any irreversible/direction-setting choice. Mechanical fixes may proceed with a changelog note; **intent-level drift → halt and ask**.
- Original Intent is locked (§1); amendments only by asking the user.

### Data & scoring
- **Folder is ground truth**: `research\Sperry-Tech-Challenge\` — 6 files (outline DOCX, Finding_Real_Locations_Guide DOCX, Projects_Overlaps.xlsx, Dominion 2024–2028 PDF [44 pp], Georgia Power 2025 IRP Vol.3 PDF [668 pp], Sperry intern listing DOCX).
- Canonical scoring (byte-identical wording everywhere): "score = tier points (crossing=100, <1.6 km=60, <8 km=40, <40 km=20) + 15 if build windows overlap, total capped at 100; tie-break by smaller closest-point distance". Build window = `[in-service year, in-service year + 1]`. All distance math in **EPSG:5070**.
- Time gap: **scored by year** (window rule above); **displayed as days** via `time_gap` = |in_service_date_a − in_service_date_b| in days (release guide + starter workbook semantics — absolute date difference, exact integers).
- Release guide method (ground truth for the golden fixture): project **center point = midpoint of its two named sub-points; if only one point is located, that point is the center**; overlap = **center-to-center haversine < 25 mi (40,234 m)**; every match confirmed against the PDF description/zone or flagged lower-confidence.
- GPC scope: **GPC-sponsored rows only** (ITS Table 2 Sponsor column ≈ 122 rows).
- Own layer: ~~**straight corridors** — geocoded endpoints → LineString/Point GeoJSON, our own styled layer (snap-to-existing = stretch only).~~ **Superseded by phase 07 (`03.5-scoring.md`), by user direction: route-aware corridors — snap to OSM `power=line` within 10 km where possible, 10 km declared buffer where not; `geometry_source` discloses which, per project.**
- Geocode QA: automated pass + **per-endpoint confidence labels** (confirmed / likely / unconfirmed) + manual second look.
- Freshness: release data is the build's data; **live cross-check spot** (a few sources re-fetched) noted in README.
- Golden test: ~~**reproduce the starter workbook's 6 overlap rows, ±0.1 mi, via center-point haversine** (exact expected values embedded in phase 02).~~ **Superseded by phase 07, by user direction: kept as the labeled LEGACY reference test, joined by a hand-verified ROUTE-aware golden for the same 6 pairs — both in `scripts/check_07.py`, nothing dropped.** Starter export schema (`Projects_Overlaps.xlsx`) is preserved for CSV export.
- Table rows: **top 10 visible; excluded >40 km greyed below** (expandable); **CSV exports all** rows.
- Basemap: **light only**. Palette binding (exact): DESC `#2563EB`, GPC `#059669`, halos — touching `#DC2626`, <1.6 km `#F97316`, <8 km `#FBBF24`, <40 km `#FDE68A`, excluded grey at 20% opacity.

### Stack
- Backend: **Python / FastAPI** + geopandas, shapely, pdfplumber, geopy, pandas, pyproj — env via **uv**.
- Frontend: **Vite / React / TypeScript**, TanStack Table, MapLibre GL, Zustand, Tailwind — via **npm**.
- Serving: **single-port FastAPI** serves the built static frontend. Demo: **offline-first static**, **local only**.
- Testing: **smoke self-checks** (assert-style scripts; no heavy test framework).
- UI: **UI Example 3 = Concept C "Ledger"** (sortable ranked table primary surface + sticky linked map inset). UI built with skill `nextlevelbuilder/ui-ux-pro-max-skill`, **building around the report palette above** (skill styles, palette governs hues).

### AI
- **Free-tier only** → OpenRouter with a **provider adapter** (others swappable later).
- Pinned primary model: **`meta-llama/llama-3.3-70b-instruct:free`**, **fallback-on-error** to a secondary free model in the adapter.
- Features: **(1) pair-brief generator** — planner-prose, 3–4 sentences, numbers injected from the pair data; **(2) natural-language table query** — filter/sort/count ONLY (never writes, never answers free-form knowledge).
- Caching: **disk JSON cache + live fallback** (cache key includes model + prompt version).
- UX: **status chip + graceful fallback** — states: live / cached / rate-limited / unavailable + Retry; NL query falls back to a local keyword filter when AI is down. Placement: **command bar** (NL query) + **detail drawer** (pair briefs).
- Sperry Tech AI ("software · engineering · research"; construction-company parent → ETL/validation/ML over messy project data): **pitch + README framing only**, not a runtime dependency.
- Ship floor: **map + table + 1 AI feature (pair briefs)** ship; NL query + exports next; **pitch and bonus cost/impact are cut first** → stretch phase 06.

### Report reconciliation (completed this session)
- Full reconciliation of `research\gridlock-evaluation.md`; all source rows **kept with statuses refreshed**; UI section keeps the Concept A analysis and appends the **locked-choice-C** note.

---

## 3. Phase Tracker

| # | File | T+ budget | Status |
|---|---|---|---|
| 01 | 01-FOUNDATION.md | T+0–2h | done |
| 02 | 02-DATA-PIPELINE.md | T+2–8h | done |
| 03 | 03-SCORING-API.md | T+8–12h | done |
| 04 | 04-FRONTEND.md | T+12–19h | done |
| 05 | 05-AI-SHIP.md | T+19–23h | not started |
| 06 | 06-STRETCH.md (stretch, cut-first items) | T+23–24h+ | not started |
| 07 | 03.5-scoring.md (route-aware corridors; intent change, supersedes §2 straight-line lock) | stretch, after 05/06 if clock allows — run early by user request | done |

Ship floor = end of phase 05 with pair briefs working. If the clock runs out mid-phase: finish the phase's Verify minimum, write the changelog, stop — do not start the next phase.

---

## 4. Changelog (append-only; newest last; stamp with T+ time)

| T+ | Phase | What changed | Why / who decided |
|---|---|---|---|
| T−0 | planning | Report fully reconciled vs release folder; phase plans authored (this folder) | User-approved plan; 49 locked decisions |
| T+~1 | 01 | scaffold + data copy committed: uv py3.12 env, Vite react-ts frontend, 6 release files, README stub, `scripts/check_01.py` all green | START-GATE answers: Python **3.12** · scaffold **minimal react-ts** · README **stub now** · data copy **all 6 files verbatim** |
| T+~7 | 02 | ingest built + committed: `projects.csv` 168 rows (DESC 44, GPC 124), `gazetteer.csv` 205 endpoints (109 confirmed/59 likely/37 unconfirmed), `gridlock_projects.geojson`, `pairs_metrics.csv` 211 rows; golden **6/6 pass** (`check_02` ALL PASS, ±0.1 mi + exact time_gap); DATA-NOTES §4 filled | START-GATE answers: county-centroid+unconfirmed · Santee Cooper out · 1 req/s+backoff · automated labels only. Mechanical: county not derivable → state centroid (noted §4); GPC_2/GPC_3 kept though sponsor=SAV (starter=ground truth); geopy `country_codes` kwarg fix (all-89 Nominatim miss bug); folium skipped → numeric QA; EIA 860M skipped; HIFLD 6504 / Overpass 1866 live drift noted |
| T+~11 | 03 | engine + API; golden 6/6 via API; boundaries green | START-GATE answers: 25 nearest excluded exemplars · CSV = all API rows · (40,000–40,234] m excluded per 40 km rule · window = YEAR only. Fork: 8 km boundary conflict → strict table governs (d=8000 → `<40`, §6). Mechanical: `httpx` added as dev dep (TestClient); plan Task C boundary typo fixed in `check_03` |
| T+~17 | 04 | Ledger UI + linked MapLibre inset live: Concept C layout, TanStack v9 sortable ledger (score desc default, 50+load-more), Zustand two-way row↔halo sync, drawer w/ pair detail + phase-05 AI slot, command-bar NL slot stubbed, honesty footer, CSV export link; skill `ui-ux-pro-max` design-system applied (token layer in `index.css`); `scripts/check_04.py` green (build + 6/6 palette hexes + basemap URL in dist) | START-GATE answers: basemap `tiles.openfreemap.org/styles/liberty` · paging 50+load-more · desktop-demo-only · empty state = explainer+nearest (§6). Mechanical: `import * as maplibregl` (v6 ESM, no default export); columns array cast once (v9 per-column generics); `getVisibleCells`→`getAllCells` (no visibility feature) |
| T+~18 | 04 fix | Map pane blank fixed: WebGL2 guard with visible message; remote-style failure now swaps once to a no-tile background style so data layers/legend still render; data layers re-apply via `style.load` (survives setStyle) and halo listeners hoisted to init (was duplicating on re-apply). Ledger↔map split drag-resizable (clamp 25–75%); detail Drawer drag-resizable (clamp 140px–70vh) | User report: "i cant see the map" + resize request; mechanical fix, no intent change |
| T+~19 | 04 fix | Map renders (verified in headless Chrome, screenshot shows basemap + halos + corridors): (1) worker 404 — Vite dep-prebundle rewrites `import.meta.url` so MapLibre worker resolved into `.vite/deps/`; fixed with `?url` import + `maplibregl.setWorkerUrl` (also fixes prod build, worker emitted as asset). (2) container height 0 — `maplibre-gl.css` `.maplibregl-map{position:relative}` overrode Tailwind `absolute inset-0` on the host (equal specificity, later cascade); host div now `h-full w-full`. Temp `window.__map` probe hook removed; tsc/lint/build green | User report: "map is still not rendering"; two-stage root cause via DOM probes |
| T+~20 | 04 fix | Map legibility rework (user: "janky lines… hard to understand"): halos dimmed (0.65; pale <40 tier at 0.8, width 4 — initial 0.35/3.5 rendered but was invisible for <8/<40 on light basemap, user bug "cannot see 8 and 40 km lines when selected") + two-way hover spotlight (row↔line, focus = `hoverId ?? selectedId`); camera flies on SELECT only — hover no longer yanks the view; legend rebuilt as 5 clickable tier toggles (`hiddenTiers` state, independent of table chips; default map = touching + `<1.6` only) + "What you see" symbology explainer (corridor line · single-endpoint dot — tooltip names substation honestly · tier band · focus glow); crossing rows drawn as circle dots (were zero-length LineStrings); map→table hover wired; new `scripts/check_map_lines.py` spot-check green (236 rows 2-pt LineStrings, sampled endpoints sit on claimed corridor geoms ±1 m, segment length == scored distance, tier == `tier_for` — **lines confirmed correct**; `check_05.py` name reserved for phase 05). tsc/lint/build + `check_04` + 14-assert headless probe all green | User report: messy lines, unsure they are correct, "what is a transmission line / substation"; scope chosen via AskUserQuestion (toggles + spotlight + default filter + spot-check) |
| T+~21 | 07 (03.5) | **Route-aware corridors — this supersedes the §2 "Own layer: straight corridors" lock AND the original golden-test values, by user direction (intent change via `03.5-scoring.md`, not a mechanical fix):** Overpass pull (15,810 `power=line` ways + 5,315 substations; 183,554 towers counted then pruned from cache — mechanical) → `backend/build_routes.py` snaps each corridor to the nearest OSM line within 10 km of both endpoints, buffers where none exists; `geometry_source` on all 168 (osm_snapped **105 = 62.5 %**, buffered 59, fallback 4, no nulls); `pairs_metrics` gains `distance_m` (route-aware, replaces scored distance) + `distance_m_legacy_straightline` (old column renamed, meters) + unchanged `distance_center_mi`; engine scores route geometry with centers pinned via `center_lat/lon` props (golden metric immune to snapping); golden = LEGACY 6/6 **+** ROUTE 6/6 hand-verified vs OSM way voltages/IRP titles (`check_07` green, `check_01–04` + `check_map_lines` still green); UI grounding legend w/ live counts + drawer Grounding tag + honesty footer rewrite; README "straight-line problem" section; DATA-NOTES §5. **Eyeball finding:** all 34 crossing rows are `buffered×buffered` and pre-date the phase (Square D→Cambridge MA *unconfirmed*, Killian ~150 km off — phase-02 geocode debt); 0 involve snapped geometry; disclosed, not silently fixed | START-GATE 03.5: Q1=**(c) snap+buffer** · Q2=**10 km tunable** · Q3=**(b) legacy + route-aware golden, both visible** · Q4=**direct feed only — same thresholds, no confidence multiplier** (all four recommended options accepted) |

---

## 5. Sync Protocol (dual location)

1. This file (`phase-plans\00-PROJECT-STATE.md`) is canonical.
2. At each phase end: copy it to `gridlock\docs\PROJECT-STATE.md`, commit both the repo copy and the changelog entry with the phase commit.
3. Before starting a phase: read THIS file, not the repo copy.
4. Conflict (copies differ beyond the expected changelog tail): home wins → halt and ask the user.

---

## 6. Open Questions log

Record every START-GATE answer and mid-phase fork here as they happen (append rows):

| T+ | Phase | Question | Answer |
|---|---|---|---|
| T+~1 | 01 | Python version? | 3.12 (recommended) |
| T+~1 | 01 | Scaffold style? | minimal hand-rolled Vite react-ts |
| T+~1 | 01 | README timing? | stub now, full in phase 05 |
| T+~1 | 01 | Data copy scope? | all 6 release files verbatim |
| T+~2 | 02 | Ungeocodeable endpoint fallback? | county centroid + `unconfirmed` label |
| T+~2 | 02 | Santee Cooper? | out of scope (release folder = ground truth) |
| T+~2 | 02 | Geocode rate discipline? | 1 req/s + retries with backoff |
| T+~2 | 02 | QA depth? | automated labels only (24h clock) |
| T+~8 | 03 | Excluded-pair rows (>40 km)? | 25 nearest exemplars (recommended) |
| T+~8 | 03 | CSV export scope? | all API rows incl. excluded exemplars (recommended) |
| T+~8 | 03 | 25 mi vs 40 km edge (40,000–40,234 m]? | exclude per locked 40 km rule (recommended) |
| T+~8 | 03 | Date → build window? | YEAR only, [year, year+1] (recommended) |
| T+~9 | 03 | 8 km boundary conflict (Task A table `d < 8000` vs Task C test `d=8000→<8`)? | strict table governs: d=8000 → `<40 km`/20; test typo fixed (7999→<8, 8000→<40) (recommended) |
| T+~16 | 04 | Light basemap tiles for MapLibre inset? | `https://tiles.openfreemap.org/styles/liberty` (user-supplied custom answer; free, no API key) |
| T+~16 | 04 | Excluded/behind-top-10 rows in ledger? | first 50 + "load more" (recommended) |
| T+~16 | 04 | Mobile support level? | desktop-demo-only (recommended) |
| T+~16 | 04 | Empty state if zero pairs survive filter? | explainer + nearest-candidates list (recommended) |
| T+~21 | 07 (03.5) | Route-awareness depth? | (c) both — snap where OSM corridor nearby, buffer where none (recommended) |
| T+~21 | 07 (03.5) | Buffer size for unsnapped endpoints/segments? | 10 km, tunable constant (recommended) |
| T+~21 | 07 (03.5) | Golden test under route-aware distance? | (b) keep old golden as labeled legacy/straight-line reference AND add new route-aware test — both visible, nothing silently dropped (recommended) |
| T+~21 | 07 (03.5) | Scoring impact of route-aware distance? | direct feed only — new distance_m feeds the same tier thresholds; geometry_source disclosed for transparency, no confidence multiplier (recommended) |

---

## 7. The phase-file pattern (every phase file follows this)

Each numbered file contains, in order:

1. **Header** — mission, T+ budget, inputs (specific report sections + specific release files under `research\Sperry-Tech-Challenge\` and `gridlock\data\release\`).
2. **START-GATE** — 2–4 real AskUserQuestion items. **The user must answer before any task runs.** Never re-ask anything in §2.
3. **Tasks** — checklist with exact paths under `hackathon\gridlock\`; critical schemas/formulas/URLs/palette values embedded inline (no need to open the report mid-build).
4. **Verify** — phase-specific smoke self-checks / golden tests; the phase does not exit red.
5. **STATE UPDATE** — re-read `00-PROJECT-STATE.md`; append its §4 changelog row; log START-GATE answers in its §6; sync the file to `gridlock\docs\`.
6. **Halt rule** — intent-level drift → stop and ask. Mechanical fixes → proceed + changelog note.