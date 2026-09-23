# Thesis to Pipeline

Upload an investment thesis, get a ranked list of Indian startups that fit it, with evidence.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # add ANTHROPIC_API_KEY
.venv/bin/python run.py --thesis theses/my-thesis.pdf
```

## How it works

1. **Thesis to spec.** Claude reads the thesis (PDF or markdown) and writes `runs/<name>/spec.yaml`:
   the investable pattern, company types to include and exclude, hard filters, 20 to 40
   search keywords grouped by type, and the seed companies the thesis names. The run stops
   here so you can review and edit the spec. Run the same command again to continue.
2. **Search** (not built yet). Exa find-similar from each seed, keyword search biased to India.
3. **Score and page** (not built yet). Deterministic 0 to 100 score from the spec. No LLM in scoring.
4. **Enrich and extra sources** (not built yet). GitHub, accelerator lists, funding news.

## Status

| Step | State |
|---|---|
| 1. Thesis to spec.yaml | built |
| 2. Exa search | next |
| 3. Scoring and page | |
| 4. Enrichment and extra sources | |
