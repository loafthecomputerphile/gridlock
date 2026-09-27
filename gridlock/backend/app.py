"""Phase 03 API — canonical scoring engine behind FastAPI.

Run: uv run uvicorn backend.app:app --port 8000
Endpoints: /api/health · /api/projects · /api/overlaps (?tier=&sort=score|distance|year&limit=)
           /api/pairs/{pair_id} · /api/export/overlaps.csv
`rank` is the canonical order (score desc, distance asc) and stays stable when
`sort` re-orders the response.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from . import engine

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

app = FastAPI(title="Gridlock Scoring API", version="0.3")
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
    confidence: str
    geometry: dict


class PairDetail(OverlapRow):
    project_a_detail: ProjectRow
    project_b_detail: ProjectRow


def _load_projects() -> list[dict]:
    meta = pd.read_csv(PROC / "projects.csv", dtype=str, keep_default_na=False)
    feats = json.loads((PROC / "gridlock_projects.geojson").read_text(encoding="utf-8"))["features"]
    geo = {f["properties"]["project_id"]: f for f in feats}
    rows = []
    for _, r in meta.iterrows():
        f = geo[r["project_id"]]
        rows.append({**r.to_dict(),
                     "geometry_basis": f["properties"]["geometry_basis"],
                     "confidence": f["properties"]["confidence"],
                     "geometry": f["geometry"]})
    return rows


PROJECTS = _load_projects()
BY_ID = {p["project_id"]: p for p in PROJECTS}


# ---------- endpoints ----------
@app.get("/api/health", response_model=Health)
def health() -> Health:
    state = (ROOT / "docs" / "PROJECT-STATE.md").read_text(encoding="utf-8")
    done = re.findall(r"^\|\s*(\d{2})\s*\|\s*[\w.-]+\.md\s*\|[^|]*\|\s*done\s*\|", state, re.M)
    files = sorted(p.name for p in PROC.iterdir()
                   if p.is_file() and not p.name.startswith("."))
    return Health(status="ok", phases_done=done, data_files=files)


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
            "project_b_detail": BY_ID[row["project_b"]]}


@app.get("/api/export/overlaps.csv")
def export() -> Response:
    body = (PROC / "overlaps.csv").read_text(encoding="utf-8")
    return Response(body, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="overlaps.csv"'})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
