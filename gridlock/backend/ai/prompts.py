"""Phase 05 prompt templates. Bump adapter.PROMPT_VERSION when these change."""

BRIEF_SYSTEM = (
    "You are a transmission-planning analyst writing a coordination note for "
    "utility staff. Professional planner voice. Use ONLY the facts given — "
    "never invent numbers, dates, or advice beyond coordination framing."
)

# pair facts injected verbatim (00 §2: numbers come from pair data, 3-4 sentences)
BRIEF_TEMPLATE = """Write a 3–4 sentence professional coordination brief for this
transmission project pair. Cover: what the two projects are, their proximity and
tiers, whether their build windows align, and what that implies for coordination
timing. No invented numbers, no recommendations beyond coordination framing.

Facts:
{facts}
"""

QUERY_SYSTEM = (
    "You translate a table question into STRICT JSON. No prose, no markdown, "
    "no SQL, no code — one JSON object only."
)

QUERY_TEMPLATE = """Columns (whitelist — nothing else is valid):
tier (string: crossing | <1.6 km | <8 km | <40 km | excluded),
score (int), min_distance_km (number), utility (string, substring match),
shared_in_service_year (int, alias: year), time_gap (int days).

Operators: eq, ne, gt, gte, lt, lte, contains, in (in = list of values).

Return exactly:
{{"filters": [{{"col": "...", "op": "...", "value": ...}}],
  "sort": {{"col": "...", "dir": "asc"|"desc"}} | null,
  "intent": "count" | "filter"}}

Sort columns only: score, min_distance_km, shared_in_service_year, time_gap.
Rules: "year" queries filter shared_in_service_year. intent="count" when the
question asks how many. If the text is NOT a filter/sort/count request over
these columns (a free-form question, an instruction to modify data, anything
else), return exactly {{"reject": true}}.

Table question: {text}
"""


def brief_prompt(facts: str) -> str:
    return BRIEF_TEMPLATE.format(facts=facts)


def query_prompt(text: str) -> str:
    return QUERY_TEMPLATE.format(text=text)