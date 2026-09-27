"""Phase 04 frontend smoke self-check. Run: python scripts/check_04.py

Builds the frontend (tsc + vite) and greps the emitted bundle for the six
locked palette hexes plus the START-GATE 04-1 basemap style URL. Exits
non-zero (assert) on any failure; prints PASS per check.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"

# locked report palette (00 §3) — must survive minification into dist/
HEXES = {
    "DESC": "#2563EB",
    "GPC": "#059669",
    "touching": "#DC2626",
    "<1.6 km": "#F97316",
    "<8 km": "#FBBF24",
    "<40 km": "#FDE68A",
}
STYLE_URL = "https://tiles.openfreemap.org/styles/liberty"


def main() -> None:
    r = subprocess.run(
        "npm run build", cwd=FE, capture_output=True, text=True, shell=True
    )
    assert r.returncode == 0, f"build failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
    print("PASS npm run build (tsc -b + vite)")

    assets = [
        p
        for p in (FE / "dist").rglob("*")
        if p.is_file() and p.suffix in {".js", ".css", ".html"}
    ]
    assert assets, "no built assets under frontend/dist"
    blob = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in assets)

    for name, hexv in HEXES.items():
        assert re.search(re.escape(hexv), blob, re.IGNORECASE), (
            f"palette hex {hexv} ({name}) missing from dist/"
        )
    print(f"PASS palette hexes in dist ({len(HEXES)}/6): {', '.join(HEXES.values())}")

    assert STYLE_URL in blob, "basemap style URL missing from bundle"
    print(f"PASS basemap style ({STYLE_URL})")

    assert 'data-row' in blob, "ledger row anchors missing (map->row scroll)"
    print("PASS ledger row anchors present")

    print("ALL CHECKS PASS")


if __name__ == "__main__":
    main()
