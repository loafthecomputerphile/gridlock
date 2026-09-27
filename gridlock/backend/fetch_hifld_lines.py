"""HIFLD US Electric Power Transmission Lines — SC/GA bbox reference overlay.

Run: uv run python backend/fetch_hifld_lines.py

User-requested ("load this into the map"): the national HIFLD transmission
lines feature service, queried once for the build bbox and cached at
_cache/hifld_lines.geojson (offline-first, like overpass_power.json).
Display + pair linking only (START-GATE: overlay + link, no snap) — this data
never feeds scoring or endpoint location (guide-only policy stands).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .build_data import BBOX, CACHE

SERVICE = (
    "https://services2.arcgis.com/LYMgRMwHfrWWEg3s/arcgis/rest/services/"
    "HIFLD_US_Electric_Power_Transmission_Lines/FeatureServer/0/query"
)
OUT_CACHE = CACHE / "hifld_lines.geojson"
PAGE = 2000
FIELDS = "VOLTAGE,VOLT_CLASS,OWNER,STATUS,SUB_1,SUB_2"


def esri_to_geojson(path_feats: list[dict]) -> list[dict]:
    out = []
    for f in path_feats:
        paths = (f.get("geometry") or {}).get("paths") or []
        paths = [p for p in paths if len(p) >= 2]
        if not paths:
            continue
        geom = ({"type": "LineString", "coordinates": paths[0]} if len(paths) == 1
                else {"type": "MultiLineString", "coordinates": paths})
        out.append({"type": "Feature", "properties": f.get("attributes") or {},
                    "geometry": geom})
    return out


def fetch() -> list[dict]:
    envelope = json.dumps({**BBOX, "spatialReference": {"wkid": 4326}})
    feats: list[dict] = []
    offset = 0
    while True:
        q = urllib.parse.urlencode({
            "where": "1=1", "geometry": envelope,
            "geometryType": "esriGeometryEnvelope", "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": FIELDS, "returnGeometry": "true", "outSR": "4326",
            "resultOffset": offset, "resultRecordCount": PAGE, "f": "json",
        })
        req = urllib.request.Request(f"{SERVICE}?{q}",
                                     headers={"User-Agent": "gridlock-hackathon/0.1"})
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.loads(r.read())
        if "error" in j:
            raise RuntimeError(f"ArcGIS query error: {j['error']}")
        batch = j.get("features", [])
        feats.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return esri_to_geojson(feats)


def main() -> None:
    feats = fetch()
    OUT_CACHE.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    kb = OUT_CACHE.stat().st_size // 1024
    print(f"HIFLD lines: {len(feats)} features in bbox -> {OUT_CACHE} ({kb} KB)")


if __name__ == "__main__":
    main()
