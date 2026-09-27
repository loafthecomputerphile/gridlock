"""Convert the workspace Overpass download (ga_sc_transmission_lines.json) to
the cached GeoJSON overlay the map serves.

Run: uv run python backend/convert_overpass_lines.py

Input: ../ga_sc_transmission_lines.json (from fetch_ga_sc_lines.sh, Overpass
`out tags geom`). Output: data/processed/_cache/osm_ga_sc_lines.geojson.
Display only — never feeds scoring or endpoint location (guide-only policy).
"""
from __future__ import annotations

import json
import re

from .build_data import CACHE, ROOT

SRC = ROOT.parent / "ga_sc_transmission_lines.json"
OUT = CACHE / "osm_ga_sc_lines.geojson"


def kv_of(tags: dict) -> int:
    """Line voltage in kV (0 = tag missing). OSM convention is volts; a small
    first number means the tag was written directly in kV."""
    m = re.search(r"\d+", tags.get("voltage", ""))
    if not m:
        return 0
    v = int(m.group())
    return v // 1000 if v >= 1000 else v


def convert(els: list[dict]) -> list[dict]:
    feats = []
    for e in els:
        if e.get("type") != "way":
            continue
        pts = e.get("geometry") or []
        if len(pts) < 2:
            continue
        tags = e.get("tags") or {}
        feats.append({
            "type": "Feature",
            "properties": {
                "name": tags.get("name", ""),
                "voltage": tags.get("voltage", ""),
                "kv": kv_of(tags),
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [[p["lon"], p["lat"]] for p in pts],
            },
        })
    return feats


def main() -> None:
    els = json.loads(SRC.read_text(encoding="utf-8"))["elements"]
    feats = convert(els)
    assert feats, "no line features converted"
    assert all(len(f["geometry"]["coordinates"]) >= 2 for f in feats)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats}),
                   encoding="utf-8")
    kb = OUT.stat().st_size // 1024
    print(f"OSM lines: {len(feats)}/{len(els)} elements -> {OUT} ({kb} KB)")


if __name__ == "__main__":
    main()