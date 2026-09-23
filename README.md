# Thesis to Pipeline

Give it an investment thesis. Get back a ranked list of Indian startups that fit it, with evidence links for every one.

I wrote a thesis on robot training data, then built this to find the companies it points to,
instead of searching by hand.

## Results

| Thesis | Shortlist | Every candidate | Search spec |
|---|---|---|---|
| Robot training data (India) | [shortlist.md](runs/robot-training-data/shortlist.md) | [candidates.csv](runs/robot-training-data/candidates.csv) | [spec.yaml](runs/robot-training-data/spec.yaml) |

## How it works

```
thesis.pdf -> 1. spec.yaml   -> 2. search -> 3. score          -> shortlist.md + candidates.csv
              (LLM reads the     (Exa)        (fixed rules,
               thesis)                         no LLM)
```

1. **Thesis to spec.** An LLM reads the thesis and writes a search spec: the investable pattern in one
   sentence, company types to include and exclude, hard filters, 20 to 40 search keywords, and the
   companies the thesis names. I review and edit the spec before anything is searched.
2. **Search.** Exa runs one search per keyword, plus a "more like this" search from each company the
   thesis names as a target. Results are merged into one row per company, with every page that
   mentions it.
3. **Score.** Every company gets a score out of 100 from fixed rules: how many searches found it,
   keyword fit, geography, number of evidence pages, own website, and whether the thesis names it.
   Companies that have already raised a priced round are found but kept off the shortlist. The LLM
   is used only to write a one-line "why it fits" and "what to verify next" for the top 15.

The scoring has no LLM in it on purpose: the same inputs always give the same ranking, and every
point can be traced to a rule and a link.

## Tools used

| Tool | Used for |
|---|---|
| [Claude Code](https://claude.com/claude-code) | Building the whole pipeline, from my one-page brief |
| [Exa](https://exa.ai) | Web search, and pulling company names out of the pages it finds |
| [OpenRouter](https://openrouter.ai), Nemotron 3 Super (free) | Reading the thesis into a spec, and the one-line notes |

## Code

```
run.py               one command: python run.py --thesis thesis.pdf
pipeline/spec.py     step 1, thesis to spec.yaml
pipeline/search.py   step 2, Exa search and merge
pipeline/score.py    step 3, scoring rules and outputs
pipeline/llm.py      OpenRouter call with a strict JSON schema
```

To run it yourself: `pip install -r requirements.txt`, put `OPENROUTER_API_KEY` and `EXA_API_KEY` in
`.env` (see `.env.example`), then `python run.py --thesis your-thesis.pdf`. The first run stops after
writing the spec so you can edit it. Run the same command again to search and score.
