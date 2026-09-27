"""Phase 05 provider adapter — OpenRouter behind a provider-neutral interface.

Run-time contract (swap provider later: same signature):
    complete(prompt, system=..., payload=...) -> {"status", "text", "model", "source"}
    status: "ok" | "rate-limited" | "unavailable"  — never a stack trace.
    source: "live" | "cached" | None

Key handling (START-GATE 05-1): OPENROUTER_API_KEY via env var or ROOT/.env;
app runs degraded without it. Cache (START-GATE 05-4): disk JSON, permanent for
the run — read-first on every call, write-through on success. Key =
sha256(model + PROMPT_VERSION + payload).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "processed" / "ai_cache"

API_URL = "https://openrouter.ai/api/v1/chat/completions"
PRIMARY_MODEL = "meta-llama/llama-3.3-70b-instruct:free"  # locked (00 §2)
FALLBACK_MODEL = "meta-llama/llama-3.1-8b-instruct:free"  # secondary free model
PROMPT_VERSION = "v1"  # bump when prompts change (invalidates cache)
TIMEOUT_S = 15.0
RETRIES_429 = 2  # retries with backoff, for 429 only


def _api_key() -> str | None:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    env = ROOT / ".env"
    if env.exists():  # tiny parser — no python-dotenv dependency
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def _cache_path(payload: dict) -> Path:
    blob = json.dumps({"model": PRIMARY_MODEL, "v": PROMPT_VERSION, **payload},
                      sort_keys=True)
    return CACHE_DIR / (hashlib.sha256(blob.encode("utf-8")).hexdigest() + ".json")


def _post_json(url: str, headers: dict, payload: dict) -> httpx.Response:
    """Single HTTP seam so check_05 can mock live/429/timeout without a network."""
    with httpx.Client(timeout=TIMEOUT_S) as client:
        return client.post(url, headers=headers, json=payload)


def _call(model: str, key: str, system: str, prompt: str) -> dict:
    """One model's attempt chain: initial + RETRIES_429 with backoff on 429 only."""
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else [])
        + [{"role": "user", "content": prompt}],
    }
    status = "unavailable"
    for attempt in range(1 + RETRIES_429):
        try:
            r = _post_json(API_URL, headers, body)
        except (httpx.TimeoutException, httpx.TransportError):
            return {"status": "unavailable"}  # timeout/connect → next model
        if r.status_code == 200:
            try:
                text = r.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError):
                return {"status": "unavailable"}
            return {"status": "ok", "text": text}
        if r.status_code == 429:
            status = "rate-limited"  # retries exhausted → report rate-limited
            if attempt < RETRIES_429:
                time.sleep(0.5 * 2**attempt)
                continue
            return {"status": status}
        return {"status": "unavailable"}  # 5xx / 4xx → next model, no retry
    return {"status": status}


def complete(prompt: str, *, system: str = "",
             payload: dict | None = None) -> dict[str, Any]:
    """Provider-neutral completion. payload = the cache key's data view of the
    prompt (pass structured facts, not the rendered string, if you want stable
    keys). Read-first cache; primary → fallback model; degraded without a key."""
    body = payload if payload is not None else {"prompt": prompt, "system": system}
    cpath = _cache_path(body)
    if cpath.exists():
        try:
            cached = json.loads(cpath.read_text(encoding="utf-8"))
            return {**cached, "source": "cached"}
        except (json.JSONDecodeError, OSError):
            pass  # corrupt cache entry → regenerate

    key = _api_key()
    if not key:
        return {"status": "unavailable", "text": None, "model": None,
                "source": None, "reason": "no OPENROUTER_API_KEY"}

    best = "unavailable"
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        out = _call(model, key, system, prompt)
        if out["status"] == "ok":
            res = {"status": "ok", "text": out["text"], "model": model, "source": "live"}
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cpath.write_text(json.dumps(res, ensure_ascii=False, indent=1),
                             encoding="utf-8")
            return res
        best = out["status"] if out["status"] == "rate-limited" else best
    return {"status": best, "text": None, "model": None, "source": None}


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply (fences tolerated)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):] if "{" in t else t
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    for i, ch in enumerate(t[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None