# Gridlock

Energy-project overlap explorer: score, map, and brief overlapping utility transmission/IRP projects (DESC × Georgia Power × Dominion).

**Phase status:** 01 foundation — see [docs/PROJECT-STATE.md](docs/PROJECT-STATE.md) for the phase tracker, locked decisions, and changelog.

## Layout

- `backend/` — FastAPI app + data pipeline (phases 02–03)
- `frontend/` — Vite / React / TypeScript app (phase 04)
- `data/release/` — verbatim copy of the challenge release folder (ground truth)
- `data/processed/` — canonical CSVs/GeoJSON (phase 02)
- `scripts/` — smoke self-checks (`check_01.py`, …)

## Quick start

```bash
uv sync                      # Python env (3.12)
cd frontend && npm install   # frontend deps
uv run python scripts/check_01.py
```
