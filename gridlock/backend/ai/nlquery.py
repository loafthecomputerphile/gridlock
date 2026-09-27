"""Feature 2 — NL table query: filter/sort/count ONLY (phase 05).

Model output is validated against a whitelist; anything outside it (free-form
SQL/JS, unknown cols/ops) falls to the local keyword parser, and if that can't
recognize the text either the request is rejected. Nothing is ever executed.
"""
from __future__ import annotations

import re
from typing import Any

from . import adapter, prompts

# whitelist — the ONLY columns ops/sort may touch (year aliases shared_in_service_year)
FILTER_COLS = {"tier", "score", "min_distance_km", "utility",
               "shared_in_service_year", "time_gap"}
SORT_COLS = {"score", "min_distance_km", "shared_in_service_year", "time_gap"}
OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "in"}
ALIASES = {"year": "shared_in_service_year"}


def validate(parsed: Any) -> dict | None:
    """Sanitize a model/local parse. Returns a clean dict or None (→ fallback/reject)."""
    if not isinstance(parsed, dict) or parsed.get("reject"):
        return None
    raw_filters = parsed.get("filters")
    if not isinstance(raw_filters, list):
        return None
    filters = []
    for f in raw_filters:
        if not isinstance(f, dict):
            return None
        col = ALIASES.get(f.get("col"), f.get("col"))
        op, value = f.get("op"), f.get("value")
        if col not in FILTER_COLS or op not in OPS:
            return None
        if op == "in":
            if not isinstance(value, list) or not value:
                return None
        elif not isinstance(value, (str, int, float)) or isinstance(value, bool):
            return None
        if col in {"score", "shared_in_service_year", "time_gap"} and op != "contains":
            if isinstance(value, str):
                return None  # numeric col, non-numeric literal
        if col == "tier" and op in {"gt", "gte", "lt", "lte"}:
            return None  # tier is categorical
        filters.append({"col": col, "op": op, "value": value})
    sort = parsed.get("sort")
    if sort is not None:
        if (not isinstance(sort, dict) or sort.get("col") not in SORT_COLS
                or sort.get("dir") not in {"asc", "desc"}):
            return None
        sort = {"col": sort["col"], "dir": sort["dir"]}
    intent = parsed.get("intent")
    if intent not in {"count", "filter"}:
        return None
    return {"filters": filters, "sort": sort, "intent": intent}


def _match(row: dict, f: dict) -> bool:
    col, op, value = f["col"], f["op"], f["value"]
    v = row.get(col)
    if col == "utility":  # utility is a list on the row — substring match any
        hay = " ".join(row.get("utilities") or []).lower()
        needle = str(value).lower()
        return (needle in hay) if op in {"eq", "contains"} else hay.find(needle) < 0
    if v is None:
        return False
    if op in {"eq", "contains"}:
        return str(v).lower() == str(value).lower() if op == "eq" else str(value).lower() in str(v).lower()
    if op == "ne":
        return str(v).lower() != str(value).lower()
    if op == "in":
        return any(str(v).lower() == str(x).lower() for x in value)
    if isinstance(v, str) or isinstance(value, str):
        return False  # gt/lt on non-numeric → no match, never a crash
    return {"gt": v > value, "gte": v >= value, "lt": v < value, "lte": v <= value}[op]


def apply(rows: list[dict], parsed: dict) -> list[dict]:
    out = [r for r in rows if all(_match(r, f) for f in parsed["filters"])]
    if parsed.get("sort"):
        col = parsed["sort"]["col"]
        desc = parsed["sort"]["dir"] == "desc"
        out = sorted(out, key=lambda r: (r.get(col) is None, r.get(col) or 0), reverse=desc)
    return out


def local_parse(text: str) -> dict | None:
    """Keyword parser (same whitelist) — the AI-down fallback. None = reject."""
    t = text.lower().strip()
    filters: list[dict] = []
    intent = "count" if re.search(r"\b(count|how many)\b", t) else "filter"
    recognized = False

    m = re.search(r"tier\s*(?:<|within|in)\s*(1\.6|8|40)", t)
    if m:  # tier<8 → everything at or inside that radius, crossing included
        tiers = {1.6: ["crossing", "<1.6 km"], 8: ["crossing", "<1.6 km", "<8 km"],
                 40: ["crossing", "<1.6 km", "<8 km", "<40 km"]}[float(m.group(1))]
        filters.append({"col": "tier", "op": "in", "value": tiers})
        recognized = True
    elif "crossing" in t or "touching" in t or re.search(r"\btouch\b", t):
        filters.append({"col": "tier", "op": "eq", "value": "crossing"})
        recognized = True
    else:
        for tier in ("<1.6 km", "<8 km", "<40 km", "excluded"):
            if tier in t:
                filters.append({"col": "tier", "op": "eq", "value": tier})
                recognized = True
                break

    m = re.search(r"score\s*(>=|<=|>|<|=)\s*(\d+)", t)
    if m:
        op = {">": "gt", "<": "lt", ">=": "gte", "<=": "lte", "=": "eq"}[m.group(1)]
        filters.append({"col": "score", "op": op, "value": int(m.group(2))})
        recognized = True

    m = re.search(r"(?:dist(?:ance)?|km)\s*(>=|<=|>|<|=)\s*([\d.]+)", t)
    if m:
        op = {">": "gt", "<": "lt", ">=": "gte", "<=": "lte", "=": "eq"}[m.group(1)]
        filters.append({"col": "min_distance_km", "op": op, "value": float(m.group(2))})
        recognized = True

    if not any(f["col"] == "tier" for f in filters):
        if "georgia power" in t or re.search(r"\bgpc\b", t):
            filters.append({"col": "utility", "op": "contains", "value": "Georgia Power"})
            recognized = True
        elif re.search(r"\bdesc\b", t) or "dominion" in t:
            filters.append({"col": "utility", "op": "contains",
                            "value": "Dominion" if "dominion" in t else "DESC"})
            recognized = True

    for m in re.finditer(r"\b(20\d\d)\b", t):  # bare year → service year
        filters.append({"col": "shared_in_service_year", "op": "eq", "value": int(m.group(1))})
        recognized = True

    sort = None
    m = re.search(r"sort\s*by\s*(score|distance|dist|year|gap)", t)
    if m:
        col = {"score": "score", "distance": "min_distance_km", "dist": "min_distance_km",
               "year": "shared_in_service_year", "gap": "time_gap"}[m.group(1)]
        sort = {"col": col, "dir": "desc" if "desc" in t else "asc"}
        recognized = True

    if not recognized:
        return None
    return validate({"filters": filters, "sort": sort, "intent": intent})


def run_query(text: str, rows: list[dict]) -> dict[str, Any]:
    """AI first (live or cached), local keyword parser as fallback, else reject."""
    parsed, source = None, "local"
    out = adapter.complete(
        prompts.query_prompt(text),
        system=prompts.QUERY_SYSTEM,
        payload={"feature": "query", "v": adapter.PROMPT_VERSION, "text": text},
    )
    if out["status"] == "ok" and out.get("text"):
        j = adapter.extract_json(out["text"])
        parsed = validate(j) if j is not None else None
        if parsed is not None:
            source = out["source"] or "live"
    if parsed is None:
        parsed = local_parse(text)
        source = "local"
    if parsed is None:
        return {"status": "rejected",
                "detail": "not a filter/sort/count question over the table columns"}
    result = apply(rows, parsed)
    return {"status": "ok", "parsed": parsed, "row_count": len(result),
            "rows": result, "source": source}