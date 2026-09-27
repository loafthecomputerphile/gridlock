"""Phase 02 data build: release PDFs -> data/processed/.

Run: uv run python backend/build_data.py

Outputs: projects.csv, gazetteer.csv, gridlock_projects.geojson, pairs_metrics.csv,
unmapped_projects.csv
Guide method (DATA-NOTES §1): center = midpoint of two sub-points (one point if the
other is unlocated); overlap = center haversine < 25 mi; every match labeled.
Starter rows keep workbook endpoint names / coords / centers / dates verbatim
(golden fidelity); everything else is geocoded live and labeled.

Location policy (03.5 follow-up, user direction "use only data given in the
Sperry Tech Challenge folder", DATA-NOTES §6): records come from the release
folder; locations only from the folder's own Finding-guide method — OSM
Overpass power-infrastructure name matches (unique, in the ENDPOINT'S hinted
state) + Nominatim hits in the hinted state only. HIFLD and the state-centroid
fallback are NOT in the guide and were removed (they produced the map's
starburst lines / Cambridge-MA point). Projects the guide can't locate stay
in projects.csv but get no geometry: one located endpoint -> single-point
center, none -> excluded from geojson/pairs and listed in
unmapped_projects.csv.
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pdfplumber
from pyproj import Transformer
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[1]
REL = ROOT / "data" / "release"
PROC = ROOT / "data" / "processed"
CACHE = PROC / "_cache"
PROC.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)

BBOX = {"xmin": -85.6, "ymin": 30.3, "xmax": -78.5, "ymax": 35.2}  # W,S,E,N
R_MI = 3958.7613
CHECKED_ON = "2026-09-26"
# Mechanical QA (DATA-NOTES §6): a candidate must land in the ENDPOINT's hinted
# state (SC for DESC, GA for GPC) — rough rects with ~0.3° border fudge. The
# territory bbox alone let cross-state name collisions through (Summerville→AL,
# Hammond→SC), which drew the last of the nationwide junk lines.
STATE_BOX = {"SC": (-83.7, 31.7, -78.2, 35.5), "GA": (-86.0, 30.0, -80.4, 35.5)}
STATE_RE = {"SC": r", (SC|South Carolina)\b", "GA": r", (GA|Georgia)\b"}


def state_ok(state: str, lat: float, lon: float) -> bool:
    box = STATE_BOX.get(state)
    if not box:
        return True
    x0, y0, x1, y1 = box
    return x0 <= lon <= x1 and y0 <= lat <= y1

_geo = None  # Nominatim singleton: min_delay_seconds applies across calls


def find_pdf(*keys: str) -> Path:
    hits = [p for p in REL.rglob("*.pdf") if all(k.lower() in str(p).lower() for k in keys)]
    assert len(hits) == 1, f"expected 1 pdf matching {keys}, got {hits}"
    return hits[0]


def norm(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def http_json(url: str, data: bytes | None = None, timeout: int = 90, tries: int = 3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "gridlock-hackathon/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2**i)


# ---------------------------------------------------------------- Task B: ingest

def parse_date(raw: str) -> str:
    # extract-first: phased rows like "10/1/2025 (phase 1) and 10/1/2026 (phase 2)"
    # take phase 1 (earliest = first in-service)
    m = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", str(raw))
    if m:
        seg = m.group(0)
        fmt = "%m/%d/%Y" if len(seg.rsplit("/", 1)[1]) == 4 else "%m/%d/%y"
        return datetime.strptime(seg, fmt).date().isoformat()
    m = re.search(r"\d{4}-\d{1,2}-\d{1,2}", str(raw))
    if m:
        return datetime.strptime(m.group(0), "%Y-%m-%d").date().isoformat()
    raise ValueError(f"unparseable date: {raw!r}")


def starter_date(v) -> str:
    """Starter in_service_date: text, datetime, or Excel serial (origin 1899-12-30)."""
    if isinstance(v, (pd.Timestamp, datetime)):
        return pd.Timestamp(v).date().isoformat()
    if isinstance(v, (int, float)) and not pd.isna(v):
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).date().isoformat()
    return parse_date(str(v))


def first_voltage(text: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)\s*k\s*v", text, re.I)
    return m.group(1) if m else ""


def project_type(text: str) -> str:
    if re.search(r"\bplant\b|combined cycle", text, re.I):
        return "plant"
    if re.search(r"substation|\bsub\b|switch|reactor|breaker|relay|valve|autobank|transformer|statcom", text, re.I):
        return "substation"
    return "line"


def _clean_part(part: str) -> str:
    part = part.split(":", 1)[0]                                     # drop action/zone after colon
    part = re.split(r"\s+\d+(?:[./-]\d+)*\s*k\s*v", part, 1, flags=re.I)[0]  # drop at voltage
    part = re.sub(r"\s*\([^)]*\)\s*$", "", part).strip(" ,")         # trailing (SAV)/(USA) etc
    part = re.split(r"\s+(?:and|with)\s+", part, 1, flags=re.I)[0]
    return part.strip(" ,-")


def extract_endpoints(name: str, zone_strip: bool = False) -> tuple[str, str]:
    """Title/name -> (endpoint_a, endpoint_b). First corridor only; second endpoint is
    parts[1] (route-proximal — handles 3-part titles like Cameron Jct - Cameron - St Matthews)."""
    seg = re.split(r"\s+&\s+|\s+and\s+", name, 1, flags=re.I)[0]
    # replacement-char dashes: PDF emits U+FFFD (and sometimes the U+F8FF apple glyph)
    seg = seg.replace("–", " - ").replace("—", " - ")
    seg = seg.replace("�", " - ").replace("", " - ")
    if zone_strip:
        seg = re.sub(r"^[A-Z]{2,4}:\s*", "", seg)                    # GPC zone tags
    parts = [p for p in re.split(r"\s+-\s+", seg) if p.strip()]
    if len(parts) == 1:                                               # glued: Okatie-Bluffton
        parts = [p for p in re.split(r"(?<=[a-z0-9)])-(?=[A-Z(])", seg) if p.strip()]
    a = _clean_part(parts[0])
    b = _clean_part(parts[1]) if len(parts) > 1 else ""
    junk = {"", "TAP", "REBUILD", "CONSTRUCT", "REBLS", "REBLD", "TIE", "LOOP", "REPLACE"}
    if b.upper() in junk or len(b) < 3:
        b = ""
    if a.upper() in junk or len(a) < 3:
        a, b = b, ""
    return a, b


def parse_desc() -> list[dict]:
    pdf = find_pdf("dominion")
    rows = []
    with pdfplumber.open(pdf) as doc:
        for page_no, page in enumerate(doc.pages, 1):
            t = page.extract_text() or ""
            title = re.search(r"5 Year Budget\n(.*?)\nProject ID", t, re.S)
            assert title, f"DESC page {page_no}: title not found"
            title = title.group(1).replace("\n", " ").strip()
            pid = re.search(r"Project ID\n(.*?)\nProject Description", t, re.S).group(1).strip()
            status = re.search(r"Project Status\n(.*?)\nPlanned In-Service Date", t, re.S).group(1).strip()
            raw_date = re.search(r"Planned In-Service Date\n(.*?)\nEstimated Project Cost", t, re.S).group(1).strip()
            costs = re.findall(r"\$[\d,]+", t[t.find("Estimated Project Cost"):])
            assert costs, f"DESC page {page_no}: no cost"
            ep_a, ep_b = extract_endpoints(title)
            rows.append({
                "project_id": None, "name": title,
                "utility": "Dominion Energy South Carolina", "sponsor": "DESC",
                "type": project_type(title), "endpoint_a": ep_a, "endpoint_b": ep_b,
                "voltage_kv": first_voltage(title),
                "in_service_date": parse_date(raw_date), "status": status,
                "cost_usd": int(costs[-1].replace("$", "").replace(",", "")),
                "county": "", "source_file": pdf.name, "source_page": page_no,
                "notes": f"raw_date={raw_date}; pdf_project_id={pid}",
                "_src_key": norm(title),
            })
    return rows


GPC_NOISE = (
    "PUBLIC DISCLOSURE", "CRITICAL ENERGY", "Recipient", "handled in accordance",
    "duplications", "Marketing Function", "GA ITS Ten-Year Plan",
)


def parse_gpc() -> tuple[list[dict], int]:
    """GA ITS Ten-Year Plan Table 2, pages 177-191 (1-indexed). Row:
    zone year teams# <name, wraps> need-date sponsor REDACTED..."""
    pdf = find_pdf("georgia")
    rows: list[dict] = []
    failed = 0
    with pdfplumber.open(pdf) as doc:
        for page_no in range(177, 192):
            t = doc.pages[page_no - 1].extract_text() or ""

            def finalize(cur):
                nonlocal failed
                if cur is None:
                    return
                m = re.search(r"(.*?)\s+(\d{1,2}/\d{1,2}/\d{4})\s+([A-Z]+)\s+REDACTED", cur["rest"])
                if not m:
                    failed += 1
                    print(f"  warn: GPC row unparsed: {cur['rest'][:90]!r}")
                    return
                # name wraps onto lines AFTER the row's date/sponsor cells
                name = " ".join([m.group(1).strip()] + cur["cont"]).strip()
                ep_a, ep_b = extract_endpoints(name, zone_strip=True)
                rows.append({
                    "project_id": None, "name": name,
                    "utility": "Georgia Power", "sponsor": m.group(3),
                    "type": project_type(name), "endpoint_a": ep_a, "endpoint_b": ep_b,
                    "voltage_kv": first_voltage(name),
                    "in_service_date": parse_date(m.group(2)),
                    "status": "", "cost_usd": "", "county": "",
                    "source_file": pdf.name, "source_page": page_no,
                    "notes": f"raw_date={m.group(2)}; cost REDACTED in source",
                    "_src_key": norm(name),
                })

            cur = None
            for line in t.splitlines():
                line = line.strip()
                if not line or any(n in line for n in GPC_NOISE):
                    continue
                if line.startswith(("Table ", "Zone Year", "A. Georgia", "B. ", "C. ")) or (
                    "TEAMS" in line and "Need Date" in line
                ) or ("Sponsor" in line and "MEAG" in line):
                    continue
                if re.fullmatch(r"\([A-Z]{2,4}\)", line):
                    continue  # wrapped sponsor-cell artifact, not a name
                m = re.match(r"^(\d{3})\s+(\d{4})\s+(\d{4,5})\s+(.*)$", line)
                if m:
                    finalize(cur)
                    cur = {"rest": m.group(4), "cont": []}
                elif cur is not None:
                    if "REDACTED" in line:
                        continue  # malformed row (e.g. missing Zone on p191) — not ours
                    cur["cont"].append(line)
            finalize(cur)
    return rows, failed


def apply_starter(rows: list[dict], starter: pd.DataFrame, util: str) -> set[str]:
    """Starter's 5 rows for this utility keep their IDs, endpoint names, per-row coords,
    centers and dates verbatim (ground truth; MCINTOSH has two distinct starter coords —
    per-row values are the only bit-faithful choice)."""
    smap = {norm(r["project_name"]): r for _, r in
            starter[starter["project_id"].str.startswith(util)].iterrows()}
    matched: set[str] = set()

    def fnum(v):
        return None if pd.isna(v) else float(v)

    for r in rows:
        s = smap.get(r["_src_key"])
        if s is None or s["project_id"] in matched:
            continue
        matched.add(s["project_id"])
        r["project_id"] = s["project_id"]
        r["_starter"] = True
        r["endpoint_a"] = s["name_a"] if isinstance(s["name_a"], str) else ""
        r["endpoint_b"] = s["name_b"] if isinstance(s["name_b"], str) else ""
        r["_la"], r["_lo"] = fnum(s["lat_a"]), fnum(s["lon_a"])
        r["_lb"], r["_lbo"] = fnum(s["lat_b"]), fnum(s["lon_b"])
        r["_center"] = (float(s["lat_center"]), float(s["lon_center"]))
        r["in_service_date"] = starter_date(s["in_service_date"])
        r["notes"] += "; starter row verbatim (names/coords/center/date from workbook)"
    assert len(matched) == 5, f"{util}: starter id matches = {sorted(matched)} (want 5)"
    n = 6
    for r in rows:
        if r["project_id"] is None:
            while f"{util}_{n}" in matched:
                n += 1
            r["project_id"] = f"{util}_{n}"
            matched.add(r["project_id"])
    return matched


# ---------------------------------------------------------------- Task C: geocode

def fetch_overpass() -> list[dict]:
    cache = CACHE / "overpass_subs.json"
    if cache.exists():
        return json.loads(cache.read_text())
    query = (
        '[out:json][timeout:90];'
        f'nwr["power"="substation"]["name"]({BBOX["ymin"]},{BBOX["xmin"]},{BBOX["ymax"]},{BBOX["xmax"]});'
        "out geom;"
    )
    j = http_json("https://overpass-api.de/api/interpreter",
                  data=urllib.parse.urlencode({"data": query}).encode())
    cache.write_text(json.dumps(j.get("elements", [])))
    return j.get("elements", [])


def osm_coord(el: dict):
    if "lat" in el:
        return el["lat"], el["lon"]
    if "center" in el:
        return el["center"]["lat"], el["center"]["lon"]
    geom = el.get("geometry") or []
    if geom:
        lats, lons = [g["lat"] for g in geom], [g["lon"] for g in geom]
        return (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    return None


def hav_mi(la1, lo1, la2, lo2) -> float:
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_MI * math.asin(math.sqrt(a))


def nominatim_geocode(name: str, state: str):
    """START-GATE: 1 req/s + retries with backoff (singleton enforces min_delay).
    03.5 policy: a hit counts only if it is in the HINTED state (SC for DESC,
    GA for GPC) — the old code accepted any SC/GA hit, and before that flagged
    out-of-territory hits but still returned them (Square D -> Cambridge, MA).
    Returns (lat, lon, note) or None."""
    global _geo
    if _geo is None:
        from geopy.geocoders import Nominatim
        _geo = Nominatim(user_agent="gridlock-hackathon/0.1 (one-off project geocode)",
                         timeout=10)
    for query in (f"{name}, {state}", name):
        hit = None
        for i in range(3):
            try:
                time.sleep(1.0)  # START-GATE: 1 req/s (Nominatim policy)
                hit = _geo.geocode(query, exactly_one=True, country_codes="us")
                break
            except Exception as e:
                if i == 2:
                    print(f"  nominatim error {query!r}: {e}")
                    hit = None
                else:
                    time.sleep(2**i)
        if not hit:
            continue
        display = hit.address or ""
        if not re.search(STATE_RE[state], display):
            continue  # wrong state -> miss, try next query form
        return hit.latitude, hit.longitude, f"nominatim:{display}"
    return None


_rev_memo: dict = {}


def reverse_in_state(lat: float, lon: float, state: str) -> bool:
    """Guide confirm step (mechanical): Nominatim reverse-geocode the resolved
    point; False only when the reverse address is DEFINITELY in the wrong
    state (cross-state name collisions that pass the coarse STATE_BOX rects,
    e.g. 'ANNISTON'). Network failure or empty address = keep (never nuke a
    row on a flake)."""
    global _geo
    key = (round(lat, 3), round(lon, 3), state)
    if key in _rev_memo:
        return _rev_memo[key]
    if _geo is None:
        from geopy.geocoders import Nominatim
        _geo = Nominatim(user_agent="gridlock-hackathon/0.1 (one-off project geocode)",
                         timeout=10)
    ok = True
    try:
        time.sleep(1.0)  # START-GATE: 1 req/s
        loc = _geo.reverse((lat, lon), exactly_one=True, language="en")
        display = (loc.address or "") if loc else ""
        if display and not re.search(STATE_RE[state], display):
            ok = False
            print(f"  reverse-reject {lat:.4f},{lon:.4f} hint={state}: {display[:70]}")
    except Exception as e:
        print(f"  reverse error {lat:.4f},{lon:.4f}: {e}")
    _rev_memo[key] = ok
    return ok


def layer_score(key: str, name: str) -> int:
    """3 exact norm match, 2 containment (both sides >= 5 chars), else 0."""
    k = norm(name)
    if not k:
        return 0
    if k == key:
        return 3
    if len(key) >= 5 and len(k) >= 5 and (key in k or k in key):
        return 2
    return 0


def best_layer(key: str, osm: list[dict], state: str):
    """Guide-only (03.5): OSM name match for a norm key, or None.
    Candidates are pre-filtered to the hinted state (mechanical QA); exact
    (score 3) beats containment (score 2); the winning tier must resolve to
    ONE distinct location (rounded 3 dp) — ambiguous same-name hits are
    rejected (guide: confirm or flag; we drop to Nominatim instead of guessing).
    Returns (score, lat, lon, source, county)."""
    pool = [o for o in osm if state_ok(state, o["lat"], o["lon"])]
    for score in (3, 2):
        hits = [o for o in pool if layer_score(key, o["name"]) == score]
        if not hits:
            continue
        if len({(round(o["lat"], 3), round(o["lon"], 3)) for o in hits}) > 1:
            return None  # ambiguous — do not guess
        return (score, hits[0]["lat"], hits[0]["lon"], "overpass", "")
    return None


def build_gazetteer(endpoints: dict[str, tuple[str, str]], starter: pd.DataFrame) -> dict[str, dict]:
    """endpoints: norm(name) -> (display name, state hint). Starter seeds always win.
    03.5 guide-only policy: sources are starter / Overpass / in-territory Nominatim."""
    gaz_path = PROC / "gazetteer.csv"
    gaz: dict[str, dict] = {}
    if gaz_path.exists():  # idempotent rerun: keep guide-allowed rows, retry the rest
        for _, r in pd.read_csv(gaz_path).iterrows():
            src, conf = r["source"], r["confidence"]
            if src in ("hifld", "state-centroid"):
                continue  # not in the Finding guide — re-resolve (likely unlocated)
            if src == "nominatim" and conf == "unconfirmed":
                continue  # old flag-but-keep bug: out-of-territory hit — re-resolve
            if not state_ok(str(r["state_hint"]), float(r["lat"]), float(r["lon"])):
                continue  # cross-state collision under the old lax rule — re-resolve
            gaz[norm(r["endpoint_name"])] = r.to_dict()

    for _, r in starter.iterrows():
        hint = "SC" if r["project_id"].startswith("DESC") else "GA"
        for nm, la, lo in ((r["name_a"], r["lat_a"], r["lon_a"]), (r["name_b"], r["lat_b"], r["lon_b"])):
            if isinstance(nm, str) and pd.notna(la) and pd.notna(lo):
                gaz[norm(nm)] = {"endpoint_name": nm, "state_hint": hint, "lat": float(la), "lon": float(lo),
                                 "source": "starter", "confidence": "confirmed", "checked_on": CHECKED_ON,
                                 "county": ""}

    # Guide geocode layers: Overpass substations + (for line endpoints) power lines
    # from the 03.5 pull — both are the guide's own "query ALL of a utility's
    # tagged infrastructure" method, bbox-scoped to SC/GA.
    osm: list[dict] = []
    seen: set[tuple] = set()
    for cache_name in ("overpass_subs.json", "overpass_power.json"):
        p = CACHE / cache_name
        if not p.exists():
            continue
        for el in json.loads(p.read_text()):
            c, tags = osm_coord(el), el.get("tags", {})
            if c and tags.get("name") and (tags["name"], round(c[0], 3)) not in seen:
                seen.add((tags["name"], round(c[0], 3)))
                osm.append({"name": tags["name"], "lat": c[0], "lon": c[1]})
    if not (CACHE / "overpass_subs.json").exists():
        # cold start only — pull once (cached thereafter)
        for el in fetch_overpass():
            c, tags = osm_coord(el), el.get("tags", {})
            if c and tags.get("name"):
                osm.append({"name": tags["name"], "lat": c[0], "lon": c[1]})
    print(f"Overpass named power features: {len(osm)} (guide layers: substations + lines)")

    # QA: starter seed vs live exact-name OSM hit — disagreement = eyeball (per plan C)
    for key, g in gaz.items():
        if g["source"] != "starter":
            continue
        live = next(((o["lat"], o["lon"]) for o in osm if norm(o["name"]) == key), None)
        if live:
            d = hav_mi(g["lat"], g["lon"], *live)
            if d > 1.5:
                print(f"QA BUG: starter '{g['endpoint_name']}' vs live OSM {d:.1f} mi apart")

    nom_calls = 0
    nom_memo: dict[str, tuple | None] = {}
    unlocated = []
    for key, (ep_name, state) in sorted(endpoints.items()):
        if key in gaz:
            continue
        top = best_layer(key, osm, state)
        if top:
            gaz[key] = {"endpoint_name": ep_name, "state_hint": state,
                        "lat": float(top[1]), "lon": float(top[2]), "source": top[3],
                        "confidence": "confirmed" if top[0] == 3 else "likely",
                        "checked_on": CHECKED_ON, "county": top[4]}
            continue
        # Nominatim fallback (in-territory only — out-of-territory = miss).
        # memo: many PDFs repeat endpoint names across projects — one live query each.
        if ep_name not in nom_memo:
            nom_calls += 1
            nom_memo[ep_name] = nominatim_geocode(ep_name, state)
        hit = nom_memo[ep_name]
        if hit:
            lat, lon, note = hit
            gaz[key] = {"endpoint_name": ep_name, "state_hint": state, "lat": lat, "lon": lon,
                        "source": "nominatim", "confidence": "likely",
                        "checked_on": CHECKED_ON, "county": "", "notes": note}
        else:
            # guide can't locate it — no gazetteer row; write_outputs drops the
            # project's geometry (or the whole project if no endpoint resolves)
            unlocated.append(ep_name)
    # Guide confirm step: reverse-geocode every non-starter endpoint once; a
    # definitive wrong-state reverse address drops the row (-> unlocated).
    rejected = []
    for key in [k for k, g in gaz.items() if g["source"] != "starter"]:
        g = gaz[key]
        if not reverse_in_state(float(g["lat"]), float(g["lon"]), str(g["state_hint"])):
            rejected.append(g["endpoint_name"])
            del gaz[key]
    unlocated.extend(rejected)
    print(f"Nominatim calls: {nom_calls} (+{len(_rev_memo)} reverse checks)")
    if unlocated:
        print(f"guide-unlocatable endpoints ({len(unlocated)}): {sorted(unlocated)}")
    return gaz


# ---------------------------------------------------------------- outputs

def write_outputs(desc: list[dict], gpc: list[dict], gaz: dict[str, dict]) -> None:
    rows = desc + gpc
    feats, centers, geoms_5070, unmapped = [], {}, {}, []
    to5070 = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)

    for r in rows:
        confs = []
        if r.get("_starter"):
            # starter rows: workbook coords + workbook center verbatim (golden fidelity)
            pts = [(la, lo) for la, lo in ((r["_la"], r["_lo"]), (r["_lb"], r["_lbo"])) if la is not None]
            assert pts, f"{r['project_id']}: starter row with no coords"
            center = r["_center"]
            confs = ["confirmed"] * len(pts)
        else:
            pts = []
            for nm in (r["endpoint_a"], r["endpoint_b"]):
                g = gaz.get(norm(nm)) if nm else None
                if g:
                    pts.append((g["lat"], g["lon"]))
                    confs.append(g["confidence"])
                    if not r["county"] and g.get("county"):
                        r["county"] = g["county"]
            # guide: one located point IS the center; zero located -> unmapped
            center = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else None

        if center is None:
            unmapped.append(r)
            continue

        if len(pts) == 2:
            geom = {"type": "LineString", "coordinates": [[pts[0][1], pts[0][0]], [pts[1][1], pts[1][0]]]}
        else:
            p = pts[0] if pts else center
            geom = {"type": "Point", "coordinates": [p[1], p[0]]}

        worst = "unconfirmed" if "unconfirmed" in confs else ("likely" if "likely" in confs else "confirmed")
        centers[r["project_id"]] = center
        if geom["type"] == "LineString":
            geoms_5070[r["project_id"]] = LineString([to5070.transform(lo, la) for la, lo in pts])
        else:
            geoms_5070[r["project_id"]] = Point(to5070.transform(center[1], center[0]))
        if worst != "confirmed":
            r["notes"] += f"; confidence={worst}"

        feats.append({"type": "Feature",
                      "properties": {"project_id": r["project_id"], "name": r["name"],
                                     "utility": r["utility"], "type": r["type"],
                                     "endpoint_a": r["endpoint_a"], "endpoint_b": r["endpoint_b"],
                                     "in_service_date": r["in_service_date"], "confidence": worst,
                                     "geometry_basis": "straight corridor (endpoint geocode)",
                                     "geometry_note": "corridor proximity, not surveyed distance"},
                      "geometry": geom})

    for r in unmapped:
        r["notes"] += "; UNMAPPED: no endpoint locatable by the Finding-guide method (excluded from map/pairs)"

    proj_cols = ["project_id", "name", "utility", "type", "endpoint_a", "endpoint_b", "voltage_kv",
                 "in_service_date", "status", "cost_usd", "county", "sponsor",
                 "source_file", "source_page", "notes"]
    pd.DataFrame(rows)[proj_cols].to_csv(PROC / "projects.csv", index=False)

    if unmapped:
        pd.DataFrame(unmapped)[proj_cols].to_csv(PROC / "unmapped_projects.csv", index=False)
    elif (PROC / "unmapped_projects.csv").exists():
        (PROC / "unmapped_projects.csv").unlink()

    gaz_cols = ["endpoint_name", "state_hint", "lat", "lon", "source", "confidence", "checked_on"]
    pd.DataFrame(list(gaz.values()))[gaz_cols].to_csv(PROC / "gazetteer.csv", index=False)

    (PROC / "gridlock_projects.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, indent=1))

    # pairs: center haversine everywhere; closest-point in EPSG:5070. Keep any pair
    # with min(center, closest) < 40 km so both the guide view and tier view are covered.
    # Unmapped projects have no center/geometry — skipped (03.5 guide-only policy).
    KM40_MI = 40 / 1.609344
    pairs = []
    for da in desc:
        if da["project_id"] not in centers:
            continue
        for gb in gpc:
            if gb["project_id"] not in centers:
                continue
            ca, cb = centers[da["project_id"]], centers[gb["project_id"]]
            d_center = hav_mi(*ca, *cb)
            d_closest = geoms_5070[da["project_id"]].distance(geoms_5070[gb["project_id"]]) / 1609.344
            if min(d_center, d_closest) >= KM40_MI:
                continue
            gap = abs((date.fromisoformat(da["in_service_date"])
                       - date.fromisoformat(gb["in_service_date"])).days)
            pairs.append({"project_id_a": da["project_id"], "project_id_b": gb["project_id"],
                          "distance_center_mi": round(d_center, 3),
                          "distance_closest_mi": round(d_closest, 3),
                          "time_gap_days": gap})
    pd.DataFrame(pairs).to_csv(PROC / "pairs_metrics.csv", index=False)

    print("\n--- build summary ---")
    print(f"projects.csv: {len(rows)} rows (DESC={len(desc)}, GPC={len(gpc)})")
    print(f"gazetteer: {len(gaz)} endpoints")
    gaz_df = pd.DataFrame(list(gaz.values()))
    print("confidence:", gaz_df["confidence"].value_counts().to_dict())
    print("sources:", gaz_df["source"].value_counts().to_dict())
    print(f"pairs_metrics: {len(pairs)} rows | geojson: {len(feats)} features | "
          f"unmapped: {len(unmapped)}")
    if unmapped:
        print(f"unmapped_projects.csv written ({len(unmapped)}): "
              f"{[r['project_id'] for r in unmapped]}")
    odd = gaz_df[gaz_df["confidence"] != "confirmed"]
    if len(odd):
        print(f"manual eyeball list ({len(odd)} non-confirmed endpoints):")
        for _, b in odd.iterrows():
            print(f"  {b['endpoint_name']!r} -> {b['lat']:.4f},{b['lon']:.4f} "
                  f"({b['source']}, {b['confidence']})")


def main() -> None:
    print("parsing DESC (44 pages)…")
    desc = parse_desc()
    assert len(desc) == 44, f"DESC rows = {len(desc)}, want 44"
    print("parsing GPC Table 2 (pages 177–191)…")
    gpc_all, failed = parse_gpc()
    starter = pd.read_excel(next(REL.rglob("Projects_Overlaps.xlsx")), sheet_name="projects")
    # sponsor=GPC per scope decision, PLUS starter GPC rows (workbook is ground
    # truth: GPC_2/GPC_3 carry sponsor=SAV in Table 2 but are starter rows)
    sgkeys = {norm(v) for v in starter.loc[
        starter["project_id"].astype(str).str.startswith("GPC"), "project_name"]}
    gpc = [r for r in gpc_all if r["sponsor"] == "GPC" or r["_src_key"] in sgkeys]
    sponsors = pd.Series([r["sponsor"] for r in gpc_all]).value_counts().to_dict()
    print(f"GPC Table 2 parsed={len(gpc_all)}, sponsors={sponsors}, unparsed={failed}")
    print(f"kept (GPC sponsor or starter row)={len(gpc)}, dropped={len(gpc_all) - len(gpc)}")
    assert 117 <= len(gpc) <= 127, f"GPC count {len(gpc)} outside 122±5"
    apply_starter(desc, starter, "DESC")
    apply_starter(gpc, starter, "GPC")

    # endpoint collection: starter rows contribute their (starter) endpoint names so
    # unseeded ones (Hooks Sub, PURRYSBURG) still get a live gazetteer entry;
    # starter row GEOMETRY uses workbook coords regardless.
    endpoints: dict[str, tuple[str, str]] = {}
    for r in desc + gpc:
        hint = "SC" if r["sponsor"] == "DESC" else "GA"
        for nm in (r["endpoint_a"], r["endpoint_b"]):
            if nm:
                endpoints.setdefault(norm(nm), (nm, hint))
    print(f"unique endpoints to resolve: {len(endpoints)} (+ starter seeds)")

    gaz = build_gazetteer(endpoints, starter)
    write_outputs(desc, gpc, gaz)
    print("\nbuild complete ->", PROC)


if __name__ == "__main__":
    main()
