"""Step 1: turn a thesis into a structured search spec (spec.yaml).

The LLM reads the thesis once and fills a fixed schema. The spec is the only
thing later steps read, so a human can review and edit it before any search runs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel

from .ingest import thesis_text
from .llm import chat_json
from .text import plain


# ---------------------------------------------------------------------------
#  Schema
# ---------------------------------------------------------------------------

class IncludeType(BaseModel):
    id: str                 # short snake_case id, e.g. "capture_hardware"
    name: str
    description: str        # what a company of this type does, in one or two sentences
    keywords: List[str]     # search phrases a company of this type would use about itself


class ExcludeType(BaseModel):
    id: str
    name: str
    reason: str             # why the thesis rules this type out


class HardFilter(BaseModel):
    id: str
    rule: str               # the filter in plain English
    kind: Literal["geography", "funding", "stage", "company_type", "other"]
    evidence_needed: str    # what a researcher must find to mark pass or fail


class SeedCompany(BaseModel):
    name: str
    type_id: str            # one of include_types[].id
    website: Optional[str]  # only if the thesis states it
    why: str


class NamedCompany(BaseModel):
    name: str
    status: Literal["already_priced", "incumbent", "comparable", "other"]
    note: str


class Geography(BaseModel):
    focus: str                    # e.g. "India"
    search_bias_terms: List[str]  # place names or phrases to bias web search


class Spec(BaseModel):
    thesis_title: str
    pattern: str                  # the investable pattern, one sentence
    geography: Geography
    include_types: List[IncludeType]
    exclude_types: List[ExcludeType]
    hard_filters: List[HardFilter]
    seed_companies: List[SeedCompany]
    other_named_companies: List[NamedCompany]
    open_questions: List[str]     # places the thesis is ambiguous; the reviewer should decide


# ---------------------------------------------------------------------------
#  Extraction
# ---------------------------------------------------------------------------

SYSTEM = """You turn a venture investment thesis into a search spec. A program will use \
the spec to find early-stage startups that fit the thesis, so every field must be \
concrete enough to search for or check.

Fill the schema as follows.

pattern: the investable pattern in one sentence. Say what kind of company, doing what, \
where, at what stage.

include_types: the company types the thesis says to back. Usually 2 to 5. For each, write \
6 to 12 keywords. Keywords are short search phrases (2 to 5 words) that such a company \
would use on its own website, job posts or launch news, for example "egocentric data \
capture" or "teleoperation platform for robots". Across all include types there must be \
20 to 40 keywords in total. Do not put the country in the keywords; geography is handled \
separately.

exclude_types: company types the thesis rules out or says not to back, even if they sit \
in the same market (for example, companies that sell labour hours, robot makers, \
incumbents). Give the reason from the thesis.

hard_filters: pass or fail rules a candidate must meet: geography (founders or operations), \
funding (for example no priced institutional round), stage, company type. Only include \
rules the thesis states or clearly implies. For each, say what evidence a researcher needs \
to decide pass or fail.

seed_companies: the 3 to 5 companies the thesis names as targets to back. Link each to an \
include type id. Leave website empty unless the thesis gives it.

other_named_companies: every other company the thesis names, with a status. Use \
"already_priced" for startups the thesis says have raised a priced round (they must be \
excluded from a shortlist), "incumbent" for large companies, "comparable" for foreign or \
reference companies.

geography.search_bias_terms: 5 to 10 place names or phrases that bias web search toward \
the thesis geography (cities, "Indian startup", and so on).

open_questions: anything ambiguous that a human reviewer should decide before search, \
for example whether a borderline company type is in or out.

Rules for all text: plain English, short sentences, no jargon the thesis does not use. \
Never use em dashes or en dashes; use commas, colons or full stops. Use only what the \
thesis says. Do not invent companies, numbers or websites."""


def extract_spec(thesis_path: Path) -> tuple[Spec, dict]:
    """Ask the model on OpenRouter for the spec. Returns the spec and a small metadata dict."""
    user = (f"<thesis title=\"{thesis_path.stem}\">\n{thesis_text(thesis_path)}\n</thesis>\n\n"
            "Build the search spec for this thesis.")
    parsed, data = chat_json(SYSTEM, user, Spec.model_json_schema(), "spec")
    spec = Spec.model_validate(plain(parsed))
    usage = data.get("usage", {})
    meta = {
        "thesis": str(thesis_path),
        "model": data.get("model"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "request_id": data.get("id"),
    }
    return spec, meta


# ---------------------------------------------------------------------------
#  Checks, save, load
# ---------------------------------------------------------------------------

def check_spec(spec: Spec) -> List[str]:
    """Return plain-English warnings. Warnings do not block; the reviewer decides."""
    warnings = []
    n_kw = sum(len(t.keywords) for t in spec.include_types)
    if not 20 <= n_kw <= 40:
        warnings.append(f"{n_kw} keywords in total; the target is 20 to 40.")
    if not 3 <= len(spec.seed_companies) <= 5:
        warnings.append(f"{len(spec.seed_companies)} seed companies; the target is 3 to 5.")
    type_ids = {t.id for t in spec.include_types}
    for s in spec.seed_companies:
        if s.type_id not in type_ids:
            warnings.append(f"Seed '{s.name}' points to unknown type '{s.type_id}'.")
    ids = [t.id for t in spec.include_types] + [t.id for t in spec.exclude_types]
    if len(ids) != len(set(ids)):
        warnings.append("Type ids are not unique across include and exclude lists.")
    return warnings


HEADER = """\
# Search spec for: {title}
# Built from {thesis} by {model} on {date}.
#
# Review and edit this file before the search runs. Anything you change here is
# what the search, filters and scoring will use. Then run the same command again.
"""


def save_spec(spec: Spec, meta: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(spec.model_dump(), sort_keys=False, allow_unicode=True, width=100)
    header = HEADER.format(title=spec.thesis_title, thesis=Path(meta["thesis"]).name,
                           model=meta["model"], date=meta["created_at"][:10])
    path.write_text(header + "\n" + body, encoding="utf-8")
    path.with_name("spec.meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def load_spec(path: Path) -> Spec:
    return Spec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
