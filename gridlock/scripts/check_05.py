"""Phase 05 smoke self-check. Run: uv run python scripts/check_05.py

Adapter unit paths (mocked 200 / 429->fallback / timeout->unavailable, no real
network), disk-cache hit on the second brief call with the network blocked,
NL query happy-path + local fallback + malicious-prompt rejection (never
executed), `/` serves the built index.html (SPA fallback), /api/health 200.
Exits non-zero (assert) on any failure; prints PASS per check.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# `/` can only serve index.html if it exists BEFORE backend.app is imported
# (the SPA route is registered conditionally) — build first if needed.
if not (ROOT / "frontend" / "dist" / "index.html").exists():
    r = subprocess.run("npm run build", cwd=ROOT / "frontend",
                       capture_output=True, text=True, shell=True)
    assert r.returncode == 0, f"build failed:\n{r.stderr[-2000:]}"

import backend.ai.adapter as ad  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import OVERLAPS, app  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="gridlock_check05_"))


class FakeResp:
    def __init__(self, code: int, payload: dict | None = None):
        self.status_code = code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def _content(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


def _blocked(*_a, **_k):
    raise AssertionError("network blocked")


def _timed_out(*_a, **_k):
    raise ad.httpx.TimeoutException("simulated 15s timeout")


def _settle(cache_name: str, key: str | None = "test-key") -> None:
    ad.CACHE_DIR = TMP / cache_name
    ad._api_key = lambda: key


def main() -> None:
    # ---------- adapter unit: live / fallback / unavailable ----------
    _settle("live")
    ad._post_json = lambda url, h, p: FakeResp(200, _content("LIVE"))
    out = ad.complete("hello", payload={"t": "live"})
    assert out["status"] == "ok" and out["source"] == "live", out
    assert out["model"] == ad.PRIMARY_MODEL and out["text"] == "LIVE", out
    print(f"PASS adapter live path (model={out['model']})")

    _settle("fallback")
    attempts: list[str] = []

    def mixed(url, h, p):
        attempts.append(p["model"])
        if p["model"] == ad.PRIMARY_MODEL:
            return FakeResp(429)
        return FakeResp(200, _content("FALLBACK"))

    ad._post_json = mixed
    real_sleep, ad.time.sleep = ad.time.sleep, lambda s: None  # no backoff delay
    try:
        out = ad.complete("hello", payload={"t": "429"})
    finally:
        ad.time.sleep = real_sleep
    assert out["status"] == "ok" and out["model"] == ad.FALLBACK_MODEL, out
    n_primary = attempts.count(ad.PRIMARY_MODEL)
    assert n_primary == 3, f"primary attempts = {n_primary}, want 3 (1 + 2 retries on 429)"
    print(f"PASS adapter 429->fallback ({n_primary} primary attempts, then {out['model']})")

    _settle("timeout")
    ad._post_json = _timed_out  # both models time out -> chain degrades
    out = ad.complete("hello", payload={"t": "timeout"})
    assert out["status"] == "unavailable" and out["text"] is None, out
    print("PASS adapter timeout->unavailable (no stack trace, text=None)")

    _settle("nokey", key=None)
    ad._post_json = _blocked  # no key -> must not even attempt the network
    out = ad.complete("hello", payload={"t": "nokey"})
    assert out["status"] == "unavailable" and "OPENROUTER_API_KEY" in out.get("reason", ""), out
    print("PASS adapter degraded without key (no HTTP attempted)")

    c = TestClient(app)

    # ---------- brief: live -> cached -> cached with network blocked ----------
    top = next(r for r in OVERLAPS if r["tier"] != "excluded")
    _settle("brief")
    ad._post_json = lambda url, h, p: FakeResp(200, _content(
        "The two projects run roughly %.2f km apart and their build windows %s."
        % (top["min_distance_km"], "align" if top["shared_in_service_year"] else "differ")))
    r1 = c.post("/api/ai/brief", json={"pair_id": top["overlap_id"]})
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert j1["status"] == "ok" and j1["source"] == "live" and j1["text"], j1
    r2 = c.post("/api/ai/brief", json={"pair_id": top["overlap_id"]})
    assert r2.json()["source"] == "cached", r2.json()
    ad._post_json = _blocked  # network now blocked — cache must still serve
    r3 = c.post("/api/ai/brief", json={"pair_id": top["overlap_id"]})
    j3 = r3.json()
    assert j3["source"] == "cached" and j3["text"] == j1["text"], j3
    print(f"PASS brief live->cached->cached-offline ({top['overlap_id']})")

    r4 = c.post("/api/ai/brief", json={"pair_id": "NOPE_99"})
    assert r4.status_code == 404, r4.status_code
    print("PASS brief unknown pair -> 404")

    # ---------- NL query: AI happy-path (live, then cached) ----------
    # guide-only fix left 0 crossing pairs — use the most common real tier so
    # the happy path always asserts against actual rows
    from collections import Counter
    tiers = Counter(r["tier"] for r in OVERLAPS if r["tier"] != "excluded")
    demo_tier = tiers.most_common(1)[0][0]
    n_tier = tiers[demo_tier]
    assert n_tier > 0, tiers
    _settle("query_live")
    ad._post_json = lambda url, h, p: FakeResp(200, _content(json.dumps(
        {"filters": [{"col": "tier", "op": "eq", "value": demo_tier}],
         "sort": {"col": "score", "dir": "desc"}, "intent": "filter"})))
    r = c.post("/api/ai/query", json={"text": f"only the {demo_tier} pairs please"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["source"] == "live" and j["row_count"] == n_tier, (j["source"], j["row_count"])
    assert all(x["tier"] == demo_tier for x in j["rows"])
    assert j["parsed"]["sort"] == {"col": "score", "dir": "desc"}
    r = c.post("/api/ai/query", json={"text": f"only the {demo_tier} pairs please"})
    assert r.json()["source"] == "cached", r.json()
    print(f"PASS NL query AI path (live->cached, {n_tier} {demo_tier} rows)")

    # ---------- NL query: AI down -> local keyword parser ----------
    _settle("query_local", key=None)
    ad._post_json = _blocked
    r = c.post("/api/ai/query", json={"text": f"{demo_tier} pairs with 2026 service year"})
    assert r.status_code == 200, r.text
    j = r.json()
    want = [x for x in OVERLAPS
            if x["tier"] == demo_tier and x["shared_in_service_year"] == 2026]
    assert j["source"] == "local" and j["row_count"] == len(want), (j["source"], j["row_count"], len(want))
    assert j["row_count"] > 0, "2026+demo_tier slice unexpectedly empty"
    assert j["parsed"]["filters"], j["parsed"]
    r = c.post("/api/ai/query", json={"text": f"how many {demo_tier} pairs"})
    assert r.json()["parsed"]["intent"] == "count", r.json()
    r = c.post("/api/ai/query", json={"text": "sort by distance"})
    rows_sorted = r.json()["rows"]
    dists = [x["min_distance_km"] for x in rows_sorted]
    assert dists == sorted(dists), "local sort not applied"
    print("PASS NL query local fallback (filter + count + sort, source=local)")

    # ---------- malicious / free-form -> rejected, never executed ----------
    # (a) model returns a non-whitelisted column (SQL-ish injection attempt)
    _settle("query_evil")
    ad._post_json = lambda url, h, p: FakeResp(200, _content(json.dumps(
        {"filters": [{"col": "projects; DROP TABLE", "op": "eq", "value": 1}],
         "sort": None, "intent": "filter"})))
    r = c.post("/api/ai/query", json={"text": "drop table projects"})
    assert r.status_code == 422, (r.status_code, r.text)
    assert r.json()["detail"]["status"] == "rejected", r.json()
    # (b) model refuses a free-form question outright
    ad._post_json = lambda url, h, p: FakeResp(200, _content('{"reject": true}'))
    r = c.post("/api/ai/query", json={"text": "what is the airspeed velocity of an unladen swallow?"})
    assert r.status_code == 422, (r.status_code, r.text)
    # (c) nothing was executed: the table still answers afterwards
    assert len(c.get("/api/overlaps").json()) == len(OVERLAPS)
    print("PASS malicious NL prompts rejected (422), table intact")

    # ---------- single-port: `/` serves built index.html ----------
    idx = (ROOT / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
    r = c.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html"), r.status_code
    assert '<div id="root"' in r.text and "/assets/index-" in r.text, "not the built index.html"
    assert r.text == idx, "/ body != dist/index.html"
    r = c.get("/some/spa/deep/route")
    assert r.status_code == 200 and '<div id="root"' in r.text, "SPA fallback broken"
    r = c.get("/api/not-a-route")
    assert r.status_code == 404, "unknown /api path must 404, not serve index.html"
    print("PASS `/` serves built index.html (SPA fallback, /api/* untouched)")

    # ---------- health still 200 ----------
    r = c.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok", r.text
    print("PASS /api/health 200")

    print("ALL CHECKS PASS")


if __name__ == "__main__":
    main()