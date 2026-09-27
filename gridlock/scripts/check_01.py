"""Phase 01 smoke self-check. Run: uv run python scripts/check_01.py

Exits non-zero (assert) if any check fails; prints PASS per check.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check_imports():
    import fastapi, geopandas, shapely, pdfplumber, geopy, pandas, pyproj  # noqa: F401
    print("PASS imports (fastapi, geopandas, shapely, pdfplumber, geopy, pandas, pyproj)")

def check_release_files():
    files = [p for p in (ROOT / "data" / "release").rglob("*") if p.is_file()]
    assert len(files) == 6, f"expected exactly 6 release files, found {len(files)}: {files}"
    print("PASS data/release contains exactly 6 files")

def check_frontend_build():
    r = subprocess.run(
        ["npm", "run", "build"], cwd=ROOT / "frontend",
        capture_output=True, text=True, shell=True,  # shell: npm is npm.cmd on Windows
    )
    assert r.returncode == 0, f"npm run build failed:\n{r.stdout}\n{r.stderr}"
    print("PASS frontend npm run build")

def check_uvicorn():
    r = subprocess.run(
        [sys.executable, "-m", "uvicorn", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"uvicorn --help failed:\n{r.stderr}"
    print("PASS uv run uvicorn --help")

if __name__ == "__main__":
    check_imports()
    check_release_files()
    check_frontend_build()
    check_uvicorn()
    print("ALL CHECKS PASS")
