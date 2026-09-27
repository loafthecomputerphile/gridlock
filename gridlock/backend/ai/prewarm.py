"""START-GATE 05-2: pre-generate pair briefs for the top-10 pairs (run while
online so the offline demo serves them `cached`).

Run: uv run python -m backend.ai.prewarm
"""
from __future__ import annotations

from backend.app import BY_ID, OVERLAPS
from backend.ai import briefs


def main() -> None:
    top = [r for r in OVERLAPS if r["tier"] != "excluded"][:10]
    ok = cached = failed = 0
    for row in top:
        out = briefs.brief_for(row["overlap_id"], OVERLAPS, BY_ID)
        tag = out.get("source") or out["status"]
        print(f"{row['overlap_id']:>6}  {row['project_a']}×{row['project_b']:<8}  "
              f"{out['status']:<13} {tag}")
        if out["status"] == "ok" and out.get("source") == "live":
            ok += 1
        elif out.get("source") == "cached":
            cached += 1
        else:
            failed += 1
    print(f"\npre-warm done: {ok} live, {cached} cached, {failed} failed "
          f"of {len(top)}")
    if failed:
        print("hint: set OPENROUTER_API_KEY (env or gridlock/.env) and re-run "
              "— failed pairs fall back to the 'unavailable' chip in the UI.")


if __name__ == "__main__":
    main()