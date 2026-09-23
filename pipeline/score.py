"""Step 3: score every candidate with fixed rules from the spec, then write the outputs.

Scoring uses no LLM. The LLM only writes the one-line "why it fits" and
"what to verify next" for the shortlist, from the evidence it is given.

Score, 0 to 100:
  Found by the search   up to 30   10 per include type or seed query that surfaced it
  Keyword fit           up to 20   4 per spec keyword that appears in its own words
  Geography             15         the thesis geography appears in its city or pages
  Evidence              up to 15   5 per separate page that mentions it
  Own website           10         it has a company site, not only news mentions
  Named in the thesis   10         the thesis names it as a target (a seed)

Excluded from the shortlist, whatever the score:
  already priced        named as funded in the thesis, or a Series A to E round on its pages
  incumbent/comparable  named as such in the thesis
  outside geography     no sign of the thesis geography anywhere
  not a company         every page is a news or blog article and no company was named
"""


from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import List

from .llm import chat_json
from .spec import Spec
from .text import plain

SHORTLIST_SIZE = 15
SCORE_RULES = [
    ("Found by the search", "up to 30", "10 for each include type or seed query that surfaced it"),
    ("Keyword fit", "up to 20", "4 for each spec keyword that appears in its own words"),
    ("Geography", "15", "the thesis geography appears in its city or pages"),
    ("Evidence", "up to 15", "5 for each separate page that mentions it"),
    ("Own website", "10", "it has a company site, not only news mentions"),
    ("Named in the thesis", "10", "the thesis names it as a target"),
]
PRICED_ROUND = re.compile(r"\bseries\s+[a-e]\b", re.I)
FUNDING_NEWS = re.compile(r"\b(raised|raises|funding round|seed round|pre-seed)\b", re.I)
ARTICLE_URL = re.compile(r"/20\d\d/|/[a-z0-9]+(-[a-z0-9]+){4,}/?$", re.I)


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _keyword_hit(keyword: str, words: set) -> bool:
    key = [w for w in re.findall(r"[a-z0-9]+", keyword.lower()) if len(w) > 3]
    return bool(key) and sum(w in words for w in key) >= max(1, round(len(key) * 2 / 3))


def _same_company(name: str, c: dict) -> bool:
    n = _squash(name)
    first = _squash(name.split()[0]) if name.split() else ""
    return n == _squash(c["name"]) or (len(first) > 4 and (first in _squash(c["name"]) or first in _squash(c["domain"])))


def score_candidates(spec: Spec, cands: List[dict]) -> List[dict]:
    seed_types = {s.name: s.type_id for s in spec.seed_companies}
    geo_terms = [spec.geography.focus] + spec.geography.search_bias_terms

    for c in cands:
        text = " ".join([c["name"], c["what_they_do"], c["city"]] +
                        [e["title"] + " " + (e["highlight"] or "") for e in c["evidence"]])
        words = _words(text)

        kw_hits = [kw for t in spec.include_types for kw in t.keywords if _keyword_hit(kw, words)]
        geo = any(g.lower() in text.lower() for g in geo_terms if g)
        c["seed"] = any(_same_company(s.name, c) for s in spec.seed_companies)
        parts = {
            "found_by": min(30, 10 * len(c["found_by"])),
            "keyword_fit": min(20, 4 * len(kw_hits)),
            "geography": 15 if geo else 0,
            "evidence": min(15, 5 * len(c["evidence"])),
            "own_website": 10 if c["domain"] else 0,
            "named_in_thesis": 10 if c["seed"] else 0,
        }
        c["score"] = sum(parts.values())
        c["score_parts"] = parts

        # Its type: most keyword hits plus search hits; ties go to the type listed first in the spec.
        found = [o.split(":", 1)[1] for o in c["found_by"] if o.startswith("type:")]
        found += [seed_types[o.split(":", 1)[1]] for o in c["found_by"]
                  if o.startswith("seed:") and o.split(":", 1)[1] in seed_types]
        weight = {t.id: found.count(t.id) + sum(_keyword_hit(kw, words) for kw in t.keywords)
                  for t in spec.include_types}
        best = max(spec.include_types, key=lambda t: weight[t.id], default=None)
        c["type"] = best.name if best and weight[best.id] else ""

        c["funding"], c["excluded"] = "no round found", ""
        named = next((n for n in spec.other_named_companies if _same_company(n.name, c)), None)
        priced = PRICED_ROUND.search(text)
        if named and named.status == "already_priced":
            c["funding"], c["excluded"] = f"already priced: {named.note}", "already priced"
        elif named and named.status in ("incumbent", "comparable"):
            c["excluded"] = named.status
        elif priced:
            c["funding"], c["excluded"] = f"already priced: {priced.group(0)} on its pages", "already priced"
        elif FUNDING_NEWS.search(text):
            c["funding"] = "funding news found, check the stage"
        if not c["excluded"] and not geo:
            c["excluded"] = f"no sign of {spec.geography.focus}"
        if not c["excluded"] and not c["what_they_do"] and all(ARTICLE_URL.search(e["url"]) for e in c["evidence"]):
            c["excluded"] = "not a company (news or blog article)"

    cands.sort(key=lambda c: (-c["score"], c["name"].lower()))
    return cands


# ---------------------------------------------------------------------------
#  The LLM's only job: one line each for the shortlist
# ---------------------------------------------------------------------------

NOTES_SYSTEM = """You write short notes for an investor's shortlist. For each company you get \
what the search found about it. Write:
why_it_fits: one sentence on how it matches the thesis pattern, using only the evidence given.
verify_next: one short sentence on the most important thing still unverified (stage, \
founders' location, whether it sells proof or hours, and so on).
Plain English. Never use em dashes or en dashes. If the evidence is thin, say so."""

NOTES_SCHEMA = {
    "type": "object",
    "properties": {"notes": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "why_it_fits": {"type": "string"},
                       "verify_next": {"type": "string"}},
        "required": ["id", "why_it_fits", "verify_next"]}}},
    "required": ["notes"],
}


def write_notes(spec: Spec, shortlist: List[dict]) -> None:
    if not os.getenv("OPENROUTER_API_KEY"):
        print("No OpenRouter key, so the shortlist notes use the search summary instead.")
        for c in shortlist:
            c["why_it_fits"], c["verify_next"] = c["what_they_do"], ""
        return
    items = [{"id": i, "name": c["name"], "what_they_do": c["what_they_do"], "city": c["city"],
              "type": c["type"], "funding": c["funding"],
              "evidence": [f"{e['title']}: {e['highlight'][:300]}" for e in c["evidence"][:3]]}
             for i, c in enumerate(shortlist)]
    user = f"Thesis pattern: {spec.pattern}\n\nCompanies:\n{json.dumps(items, indent=1, ensure_ascii=False)}"
    parsed, _ = chat_json(NOTES_SYSTEM, user, NOTES_SCHEMA, "notes", max_tokens=8000)
    notes = {n["id"]: plain(n) for n in parsed["notes"]}
    for i, c in enumerate(shortlist):
        n = notes.get(i, {})
        c["why_it_fits"] = n.get("why_it_fits") or c["what_they_do"]
        c["verify_next"] = n.get("verify_next", "")


# ---------------------------------------------------------------------------
#  Outputs: shortlist.md and candidates.csv
# ---------------------------------------------------------------------------

def _cell(s: str) -> str:
    return (s or "").replace("|", "/").replace("\n", " ").strip()


def _link(c: dict) -> str:
    return f"[{_cell(c['name'])}]({c['website']})" if c["website"] else _cell(c["name"])


def write_outputs(spec: Spec, cands: List[dict], shortlist: List[dict], out: Path, meta: dict) -> None:
    lines = [
        f"# Shortlist: {spec.thesis_title}", "",
        f"**Pattern:** {spec.pattern}", "",
        f"{len(cands)} companies found by {meta['searches']} searches. "
        f"Top {len(shortlist)} that pass the hard filters, ranked by score. "
        "Every company in [candidates.csv](candidates.csv).", "",
        "| # | Company | City | Type | Score | Why it fits | Funding | What to verify next | Evidence |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, c in enumerate(shortlist, 1):
        ev = " ".join(f"[{j}]({e['url']})" for j, e in enumerate(c["evidence"][:3], 1))
        name = _link(c) + (" (seed)" if c["seed"] else "")
        lines.append(f"| {i} | {name} | {_cell(c['city'])} | {_cell(c['type'])} | {c['score']} | "
                     f"{_cell(c['why_it_fits'])} | {_cell(c['funding'])} | {_cell(c['verify_next'])} | {ev} |")

    priced = [c for c in cands if c["excluded"] == "already priced"]
    if priced:
        lines += ["", "## Found, but already priced", "",
                  "These fit the pattern but have raised a priced round, so they are left off the shortlist.", ""]
        lines += [f"- {_link(c)}: {_cell(c['funding'])} (score {c['score']})" for c in priced]

    lines += ["", "## How the score works", "",
              "Fixed rules from the spec, no LLM. Score out of 100:", "",
              "| Part | Points | Rule |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in SCORE_RULES]
    lines += ["", "A company is left off the shortlist, whatever its score, if it has already raised a priced "
              "round, is an incumbent, shows no sign of the thesis geography, or is only a news article. "
              "(seed) marks the companies the thesis names as targets. "
              "The one-line notes are written by an LLM from the evidence links and flag what is unverified."]
    (out / "shortlist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with open(out / "candidates.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "name", "website", "city", "type", "score", "status", "funding",
                    "what_they_do", "found_by", "evidence_urls"])
        for i, c in enumerate(cands, 1):
            status = "shortlist" if c in shortlist else (f"excluded: {c['excluded']}" if c["excluded"] else "below cut")
            w.writerow([i, c["name"], c["website"], c["city"], c["type"], c["score"], status, c["funding"],
                        c["what_they_do"], "; ".join(c["found_by"]), " ".join(e["url"] for e in c["evidence"])])


def run_score(spec: Spec, cands: List[dict], out: Path, searches: int) -> List[dict]:
    cands = score_candidates(spec, cands)
    shortlist = [c for c in cands if not c["excluded"]][:SHORTLIST_SIZE]
    write_notes(spec, shortlist)
    write_outputs(spec, cands, shortlist, out, {"searches": searches})
    print(f"Wrote {out / 'shortlist.md'} and {out / 'candidates.csv'}")
    return shortlist
