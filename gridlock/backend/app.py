"""Phase 03+05 API — canonical scoring engine + AI endpoints behind FastAPI.

Run (single-port demo): uv run uvicorn backend.app:app --port 8000
Endpoints: /api/health · /api/projects · /api/overlaps (?tier=&sort=score|distance|year&limit=)
           /api/pairs/{pair_id} · /api/export/overlaps.csv
           /api/ai/brief (POST) · /api/ai/query (POST)
           /  → built frontend (frontend/dist, SPA fallback) when present
`rank` is the canonical order (score desc, distance asc) and stays stable when
`sort` re-orders the response.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import shapely
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from pyproj import Transformer
from shapely.geometry import shape as shapely_shape
from shapely.ops import transform as shapely_transform

from . import engine
from .ai import briefs, nlquery

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

app = FastAPI(title="Gridlock Scoring API", version="0.5")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OVERLAPS = engine.build_overlaps()  # also writes data/processed/overlaps.csv


# ---------- models ----------
class Health(BaseModel):
    status: str
    phases_done: list[str]
    data_files: list[str]
    projects_total: int
    projects_located: int


class OverlapRow(BaseModel):
    rank: int
    overlap_id: str
    project_a: str
    project_b: str
    name_a: str
    name_b: str
    utilities: list[str]
    min_distance_km: float
    distance_center_mi: float
    tier: str
    year_a: int | None = None
    year_b: int | None = None
    shared_in_service_year: int | None = None
    time_gap: int | None = None
    score: int
    year_unknown: bool
    est_shared_row_acres: float  # phase 06 bonus, at DEFAULT_ROW_WIDTH_FT
    shortest_line: dict


class ProjectRow(BaseModel):
    project_id: str
    name: str
    utility: str
    type: str
    endpoint_a: str
    endpoint_b: str
    voltage_kv: str
    in_service_date: str
    status: str
    cost_usd: str
    county: str
    sponsor: str
    source_file: str
    source_page: str
    notes: str
    geometry_basis: str
    geometry_source: str
    confidence: str
    geometry: dict


class PairDetail(OverlapRow):
    project_a_detail: ProjectRow
    project_b_detail: ProjectRow
    hifld_ref: dict | None = None  # nearest HIFLD transmission line (overlay+link)


class BriefReq(BaseModel):
    pair_id: str


class QueryReq(BaseModel):
    text: str


def _load_projects() -> tuple[list[dict], int]:
    meta = pd.read_csv(PROC / "projects.csv", dtype=str, keep_default_na=False)
    feats = json.loads((PROC / "gridlock_projects.geojson").read_text(encoding="utf-8"))["features"]
    geo = {f["properties"]["project_id"]: f for f in feats}
    rows = []
    for _, r in meta.iterrows():
        f = geo.get(r["project_id"])  # unmapped (guide-only policy) — no geometry row
        if f is None:
            continue
        rows.append({**r.to_dict(),
                     "geometry_basis": f["properties"]["geometry_basis"],
                     "geometry_source": f["properties"].get("geometry_source", ""),
                     "confidence": f["properties"]["confidence"],
                     "geometry": f["geometry"]})
    return rows, len(meta)


PROJECTS, PROJECTS_TOTAL = _load_projects()
BY_ID = {p["project_id"]: p for p in PROJECTS}


# ---------- HIFLD reference overlay (user: "load this into the map") ----------
# Display + pair linking only (overlay+link gate) — never feeds scoring or
# endpoint location. nearest-line ref per pair, computed once at startup.
HIFLD_PATH = ROOT / "data" / "processed" / "_cache" / "hifld_lines.geojson"


def _load_hifld_refs() -> dict[str, dict]:
    if not HIFLD_PATH.exists():
        return {}
    feats = json.loads(HIFLD_PATH.read_text(encoding="utf-8"))["features"]
    to5070 = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    geoms = [shapely_transform(to5070.transform, shapely_shape(f["geometry"]))
             for f in feats]
    tree = shapely.STRtree(geoms)
    refs: dict[str, dict] = {}
    for r in OVERLAPS:
        seg = shapely_transform(to5070.transform, shapely_shape(r["shortest_line"]))
        i = tree.nearest(seg)
        p = feats[i]["properties"]
        v = p.get("VOLTAGE")
        refs[r["overlap_id"]] = {
            "voltage_class": p.get("VOLT_CLASS"),
            "voltage_v": v if isinstance(v, (int, float)) and v > 0 else None,
            "owner": p.get("OWNER"),
            "status": p.get("STATUS"),
            "sub_1": p.get("SUB_1"),
            "sub_2": p.get("SUB_2"),
            "dist_m": round(geoms[i].distance(seg), 1),
        }
    return refs


HIFLD_REFS = _load_hifld_refs()


# ---------- endpoints ----------
@app.get("/api/health", response_model=Health)
def health() -> Health:
    state = (ROOT / "docs" / "PROJECT-STATE.md").read_text(encoding="utf-8")
    done = re.findall(r"^\|\s*(\d{2})\s*\|\s*[\w.-]+\.md\s*\|[^|]*\|\s*done\s*\|", state, re.M)
    files = sorted(p.name for p in PROC.iterdir()
                   if p.is_file() and not p.name.startswith("."))
    return Health(status="ok", phases_done=done, data_files=files,
                  projects_total=PROJECTS_TOTAL, projects_located=len(PROJECTS))


@app.get("/api/projects", response_model=list[ProjectRow])
def projects() -> list[dict]:
    return PROJECTS


@app.get("/api/overlaps", response_model=list[OverlapRow])
def overlaps(
    tier: str | None = Query(default=None),
    sort: str = Query(default="score", pattern="^(score|distance|year)$"),
    limit: int | None = Query(default=None, ge=1),
) -> list[dict]:
    rows = OVERLAPS if tier is None else [r for r in OVERLAPS if r["tier"] == tier]
    if sort == "distance":
        rows = sorted(rows, key=lambda r: (r["distance_m"], -r["score"]))
    elif sort == "year":
        rows = sorted(rows, key=lambda r: (r["shared_in_service_year"] is None,
                                           r["shared_in_service_year"] or 0,
                                           -r["score"], r["distance_m"]))
    # sort == "score": canonical rank order, already applied
    return rows[:limit] if limit else rows


@app.get("/api/pairs/{pair_id}", response_model=PairDetail)
def pair(pair_id: str) -> dict:
    row = next((r for r in OVERLAPS if r["overlap_id"].lower() == pair_id.lower()), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown pair_id: {pair_id}")
    return {**row,
            "project_a_detail": BY_ID[row["project_a"]],
            "project_b_detail": BY_ID[row["project_b"]],
            "hifld_ref": HIFLD_REFS.get(row["overlap_id"])}


@app.get("/api/ref/hifld-lines")
def hifld_lines() -> Response:
    """Cached HIFLD transmission lines (SC/GA bbox) as GeoJSON for the map overlay."""
    if not HIFLD_PATH.exists():
        raise HTTPException(status_code=404,
                            detail="run backend.fetch_hifld_lines first")
    return Response(HIFLD_PATH.read_text(encoding="utf-8"),
                    media_type="application/geo+json")


@app.get("/api/ref/osm-lines")
def osm_lines() -> Response:
    """Cached OSM power=line overlay (GA/SC, Overpass) as GeoJSON for the map."""
    path = PROC / "_cache" / "osm_ga_sc_lines.geojson"
    if not path.exists():
        raise HTTPException(status_code=404,
                            detail="run backend.convert_overpass_lines first")
    return Response(path.read_text(encoding="utf-8"),
                    media_type="application/geo+json")


@app.get("/api/export/overlaps.csv")
def export() -> Response:
    body = (PROC / "overlaps.csv").read_text(encoding="utf-8")
    return Response(body, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="overlaps.csv"'})


# ---------- phase 05 AI ----------
@app.post("/api/ai/brief")
def ai_brief(req: BriefReq) -> dict:
    """Planner-prose pair brief. Always 200 — status carries live|cached|
    rate-limited|unavailable; never a stack trace to the UI."""
    known = any(r["overlap_id"].lower() == req.pair_id.lower() for r in OVERLAPS)
    if not known:
        raise HTTPException(status_code=404, detail=f"unknown pair_id: {req.pair_id}")
    out = briefs.brief_for(req.pair_id, OVERLAPS, BY_ID)
    return {k: out.get(k) for k in ("text", "source", "model", "status", "reason")}


@app.post("/api/ai/query")
def ai_query(req: QueryReq) -> dict:
    """NL table query — filter/sort/count ONLY, whitelist-validated; local
    keyword parser when the AI path fails; 422 when neither parses."""
    out = nlquery.run_query(req.text, OVERLAPS)
    if out["status"] == "rejected":
        raise HTTPException(status_code=422, detail=out)
    return {k: out[k] for k in ("parsed", "row_count", "rows", "source")}


# ---------- single-port ship: built frontend at / (registered last = lowest precedence) ----------
DIST = ROOT / "frontend" / "dist"

if (DIST / "index.html").exists():

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="unknown api route")
        target = (DIST / full_path).resolve()
        if full_path and target.is_file() and target.is_relative_to(DIST):
            return FileResponse(target)
        return FileResponse(DIST / "index.html")  # SPA fallback


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
