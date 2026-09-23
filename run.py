"""Thesis to Pipeline.

    python run.py --thesis thesis.pdf

First run: reads the thesis, writes runs/<name>/spec.yaml, and stops so you can review it.
Next run (same command): loads your edited spec and carries on to search.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from pipeline.spec import check_spec, extract_spec, load_spec, save_spec


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "thesis"


def print_spec(spec) -> None:
    print(f"\nPattern: {spec.pattern}\n")
    print("Include:")
    for t in spec.include_types:
        print(f"  [{t.id}] {t.name}: {len(t.keywords)} keywords")
    print("Exclude:")
    for t in spec.exclude_types:
        print(f"  [{t.id}] {t.name}")
    print("Hard filters:")
    for f in spec.hard_filters:
        print(f"  ({f.kind}) {f.rule}")
    print("Seeds: " + ", ".join(s.name for s in spec.seed_companies))
    priced = [c.name for c in spec.other_named_companies if c.status == "already_priced"]
    if priced:
        print("Already priced: " + ", ".join(priced))
    if spec.open_questions:
        print("Open questions for you:")
        for q in spec.open_questions:
            print(f"  - {q}")


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Turn an investment thesis into a ranked list of startups.")
    ap.add_argument("--thesis", required=True, type=Path, help="thesis file (PDF or markdown)")
    ap.add_argument("--out", type=Path, help="run folder (default: runs/<thesis name>)")
    ap.add_argument("--regen", action="store_true", help="rebuild spec.yaml even if it exists")
    ap.add_argument("--yes", action="store_true", help="do not stop for spec review")
    args = ap.parse_args()

    if not args.thesis.exists():
        print(f"Thesis not found: {args.thesis}", file=sys.stderr)
        return 1
    out = args.out or Path("runs") / slug(args.thesis.stem)
    spec_path = out / "spec.yaml"

    # Step 1: thesis to spec
    if args.regen or not spec_path.exists():
        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            print("No Anthropic key found. Add ANTHROPIC_API_KEY to .env (see .env.example).", file=sys.stderr)
            return 1
        print(f"Reading {args.thesis.name} and building the search spec...")
        spec, meta = extract_spec(args.thesis)
        save_spec(spec, meta, spec_path)
        print(f"Wrote {spec_path} ({meta['input_tokens']} in, {meta['output_tokens']} out tokens)")
        print_spec(spec)
        for w in check_spec(spec):
            print(f"Warning: {w}")
        if not args.yes:
            print(f"\nReview and edit {spec_path}, then run the same command again.")
            return 0
    else:
        spec = load_spec(spec_path)
        print(f"Using your reviewed spec: {spec_path}")
        for w in check_spec(spec):
            print(f"Warning: {w}")

    # Step 2 onward: not built yet
    print("\nSearch (step 2) is not built yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
