"""Step 2: search Exa from the spec and merge hits into one candidate per company.

Two kinds of queries:
  * seeds: find each seed company's own page, then search for pages like it
  * keywords: every keyword in every include type, biased to the thesis geography

A candidate comes from either the companies Exa extracts from the pages, or a
result that is itself a company's own site (news and social sites are skipped).
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

from .spec import Spec
from .text import plain

EXA_URL = "https://api.exa.ai/search"

# Pages on these sites describe companies but are not the company. Their
# companies still come through Exa's extraction.
NOT_COMPANY_SITES = {
    "linkedin.com", "youtube.com", "x.com", "twitter.com", "facebook.com", "instagram.com",
    "medium.com", "reddit.com", "wikipedia.org", "github.com", "crunchbase.com", "tracxn.com",
    "economictimes.indiatimes.com", "indiatimes.com", "livemint.com", "business-standard.com",
    "thehindu.com", "thehindubusinessline.com", "hindustantimes.com", "moneycontrol.com",
    "inc42.com", "yourstory.com", "entrackr.com", "vccircle.com", "startuppedia.in",
    "techcrunch.com", "forbes.com", "forbesindia.com", "businessinsider.com", "orfonline.org",
    "therobotreport.com", "news.ycombinator.com", "substack.com", "ycombinator.com",
    "arxiv.org", "researchgate.net", "tofler.in", "zaubacorp.com", "pitchbook.com",
}

EXTRACT_PROMPT = (
    "List each distinct company the pages describe as building or selling what the query asks for. "
    "Use the company's own name and its own website, never the news site. "
    "If a field is not stated on the pages, leave it empty. Do not guess."
)

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "website": {"type": "string"},
                    "what_they_do": {"type": "string"},
                    "city": {"type": "string"},
                    "evidence_url": {"type": "string"},
                },
                "required": ["name", "website", "what_they_do", "city", "evidence_url"],
            },
        }
    },
    "required": ["companies"],
}


def exa_search(query: str, extract: bool = True) -> dict:
    body = {"query": query, "type": "auto", "contents": {"highlights": True}}
    if extract:
        body["systemPrompt"] = EXTRACT_PROMPT
        body["outputSchema"] = EXTRACT_SCHEMA
    resp = requests.post(EXA_URL, headers={"x-api-key": os.environ["EXA_API_KEY"]}, json=body, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"Exa returned {resp.status_code} for '{query}': {resp.text[:300]}")
    return resp.json()


def domain(url: str) -> str:
    host = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    return host.removeprefix("www.")


def is_company_site(url: str) -> bool:
    d = domain(url)
    return bool(d) and not any(d == s or d.endswith("." + s) for s in NOT_COMPANY_SITES)


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


# ---------------------------------------------------------------------------
#  Queries
# ---------------------------------------------------------------------------

def seed_query(name: str, focus: str) -> Optional[str]:
    """Find the seed's own page, then turn what it says into a 'more like this' query."""
    data = exa_search(f"{name} {focus} startup", extract=False)
    token = _squash(name.split()[0])
    own = [r for r in data.get("results", []) if token and token in _squash(domain(r["url"]))]
    page = (own or [r for r in data.get("results", []) if is_company_site(r["url"])] or [None])[0]
    if page is None:
        return None
    blurb = " ".join(page.get("highlights") or [])[:300]
    return f"startups like {name}: {page.get('title', '')}. {blurb}"


def build_queries(spec: Spec) -> List[dict]:
    focus = spec.geography.focus
    queries = [{"origin": f"type:{t.id}", "query": f"{kw} startup {focus}"}
               for t in spec.include_types for kw in t.keywords]
    with ThreadPoolExecutor(max_workers=6) as pool:
        seed_qs = list(pool.map(lambda s: seed_query(s.name, focus), spec.seed_companies))
    for seed, q in zip(spec.seed_companies, seed_qs):
        if q:
            queries.append({"origin": f"seed:{seed.name}", "query": q})
        else:
            print(f"  Could not find a page for seed '{seed.name}'")
    return queries


# ---------------------------------------------------------------------------
#  Merge
# ---------------------------------------------------------------------------

def merge(runs: List[dict]) -> List[dict]:
    """One candidate per company, with every query and page that found it.

    A company is keyed by its own domain. When Exa names a company without its own
    site (only a news or LinkedIn page), it is keyed by name and folded into the
    matching domain afterwards."""
    cands: Dict[str, dict] = {}

    def add(name, website, what, city, origin, url, title, highlight):
        own = website if website and is_company_site(website) else ""
        key = domain(own) if own else "name:" + _squash(name)
        if key == "name:":
            return
        c = cands.setdefault(key, {"name": "", "website": f"https://{domain(own)}" if own else "",
                                   "domain": domain(own) if own else "", "what_they_do": "",
                                   "city": "", "found_by": [], "evidence": []})
        c["name"] = c["name"] or name
        c["what_they_do"] = c["what_they_do"] or what
        c["city"] = c["city"] or city
        if origin not in c["found_by"]:
            c["found_by"].append(origin)
        if url and all(e["url"] != url for e in c["evidence"]):
            c["evidence"].append({"url": url, "title": title, "highlight": highlight})

    for run in runs:
        results = {r["url"]: r for r in run["results"]}
        for co in run["companies"]:
            src = results.get(co.get("evidence_url"), {})
            add(co.get("name", ""), co.get("website", ""), co.get("what_they_do", ""), co.get("city", ""),
                run["origin"], co.get("evidence_url", ""), src.get("title", ""),
                (src.get("highlights") or [""])[0])
        for r in run["results"]:
            if is_company_site(r["url"]):
                title = r.get("title") or ""
                name = re.split(r"\s[|:\-]\s", title)[-1].strip() if " | " in title else ""
                add(name, r["url"], "", "", run["origin"], r["url"], title, (r.get("highlights") or [""])[0])

    # Fold name-only entries into the domain entry for the same company.
    for key in [k for k in cands if k.startswith("name:")]:
        sq = key[5:]
        match = next((c for k, c in cands.items() if not k.startswith("name:") and
                      (_squash(c["name"]) == sq or sq.startswith(_squash(c["domain"].split(".")[0])))), None)
        if match:
            extra = cands.pop(key)
            match["found_by"] += [o for o in extra["found_by"] if o not in match["found_by"]]
            match["evidence"] += [e for e in extra["evidence"] if e["url"] not in {x["url"] for x in match["evidence"]}]
            for f in ("what_they_do", "city"):
                match[f] = match[f] or extra[f]

    out = list(cands.values())
    for c in out:
        c["name"] = c["name"] or c["domain"].split(".")[0].capitalize()
    out.sort(key=lambda c: (-len(c["found_by"]), -len(c["evidence"]), c["name"].lower()))
    return plain(out)


# ---------------------------------------------------------------------------
#  Run
# ---------------------------------------------------------------------------

def run_search(spec: Spec, out: Path) -> tuple[List[dict], int]:
    raw_path, cand_path = out / "search.json", out / "candidates.json"
    if raw_path.exists():
        print(f"Using saved search results: {raw_path} (delete it to search again)")
        runs = json.loads(raw_path.read_text(encoding="utf-8"))["runs"]
    else:
        print("Finding seed company pages...")
        queries = build_queries(spec)
        print(f"Running {len(queries)} Exa searches...")

        def one(q):
            data = exa_search(q["query"])
            return {**q,
                    "results": [{k: r.get(k) for k in ("url", "title", "publishedDate", "highlights")}
                                for r in data.get("results", [])],
                    "companies": ((data.get("output") or {}).get("content") or {}).get("companies", []),
                    "cost": (data.get("costDollars") or {}).get("total", 0)}

        with ThreadPoolExecutor(max_workers=6) as pool:
            runs = list(pool.map(one, queries))
        cost = sum(r["cost"] for r in runs) + 0.007 * len(spec.seed_companies)
        raw_path.write_text(json.dumps({"cost_dollars": round(cost, 3), "runs": runs}, indent=1), encoding="utf-8")
        print(f"Saved {raw_path} (about ${cost:.2f} of Exa credit)")

    cands = merge(runs)
    cand_path.write_text(json.dumps(cands, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {cand_path}: {len(cands)} candidate companies")
    return cands, len(runs) + len(spec.seed_companies)
