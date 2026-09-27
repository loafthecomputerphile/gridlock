"""Feature 1 — pair brief: planner-prose over injected pair facts (phase 05)."""
from __future__ import annotations

from typing import Any

from . import adapter, prompts


def _facts(row: dict, by_id: dict[str, dict]) -> str:
    """Pair facts only (00 §2) — names, hues, distance, tier, score, windows,
    time gap, confidence, geometry basis."""
    a, b = by_id[row["project_a"]], by_id[row["project_b"]]
    return "\n".join(f"- {k}: {v}" for k, v in {
        "project_a": f"{row['project_a']} — {row['name_a']}",
        "project_b": f"{row['project_b']} — {row['name_b']}",
        "utilities": " × ".join(row["utilities"]),
        "min_separation_km": round(row["min_distance_km"], 2),
        "center_to_center_mi": round(row["distance_center_mi"], 2),
        "tier": row["tier"],
        "score": row["score"],
        "in_service_years": f"{row['year_a']} / {row['year_b']}",
        "shared_in_service_year": row["shared_in_service_year"],
        "time_gap_days": row["time_gap"],
        "confidence_a/b": f"{a['confidence']} / {b['confidence']}",
        "geometry_basis_a/b": f"{a['geometry_basis']} / {b['geometry_basis']}",
    }.items())


def brief_for(pair_id: str, overlaps: list[dict],
              by_id: dict[str, dict]) -> dict[str, Any]:
    row = next((r for r in overlaps if r["overlap_id"].lower() == pair_id.lower()), None)
    if row is None:
        return {"status": "unavailable", "text": None, "model": None,
                "source": None, "reason": f"unknown pair_id: {pair_id}"}
    facts = _facts(row, by_id)
    out = adapter.complete(
        prompts.brief_prompt(facts),
        system=prompts.BRIEF_SYSTEM,
        payload={"feature": "brief", "v": adapter.PROMPT_VERSION, "facts": facts},
    )
    return out