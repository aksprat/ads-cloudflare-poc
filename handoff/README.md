# Agent Led Growth Initiatives: handoff

Source for the "Agent Led Growth Initiatives" mock dashboard and the analysis behind it.

- Mock (published): https://claude.ai/artifact/Dd9gq2xuyybSMQKHbMPiD6
- Use cases doc: https://claude.ai/artifact/SLu6cqha3hmPfh1C7B6Qy8
- Ranked one-pager: https://claude.ai/artifact/1LrasUAgDKu9C52JAExHS6

## Layout

```
handoff/
  scripts/   aggregation and build scripts (Python 3, standard library only)
  results/   intermediate output of the aggregation (out/, out2/) and 18 JSON datasets (data/)
  mock/      mock_template.html, mock_data.json, edge-log-intelligence.html (the assembled page)
```

## Quick rebuild (no raw logs needed)

The page is `mock_template.html` with `mock_data.json` injected at the `/*DATA*/` placeholder.

```sh
cd handoff/results
python3 ../scripts/build_mock.py   # results/out/*.json  ->  mock/mock_data.json
python3 ../scripts/build_html.py   # template + data     ->  mock/edge-log-intelligence.html
```

Run `build_mock.py` from `results/`, because it reads `out/` by relative path.
To edit the design or charts, change `mock/mock_template.html`, then run `build_html.py`.
To publish, use the Artifact tool with the assembled HTML file (edit access to the artifact is needed to update it in place).

## Full rebuild from the raw logs

The three passes stream the 25 sample files (about 35 GB) and write per-file JSON. They use hashed IPs only; no raw IPs are written.

```sh
export LOGS_DIR=/path/to/folder/with/the/*.log.gz   # default is two levels above scripts/
python3 -I scripts/day.py 6     # pass 1: client classes, API, MCP, page views, crawlers  -> results/out
python3 -I scripts/day2.py 6    # pass 2: MCP IP funnel, 401/429 concentration, referrals -> results/out2
python3 -I scripts/day3.py 6    # pass 3: JA3 per family, docs 404s, p95 by colo         -> results/out3
```

The argument is the number of worker processes. The first sample, `20261110T143829Z_20261110T143930Z_bb2c8e23`, is an uncompressed NDJSON file that the scripts append to the `.log.gz` list, so it must be in `LOGS_DIR` too.
`results/out3` is not included (14 MB); regenerate it with `day3.py` if you need `val.py`.

Then, from `results/`:

```sh
python3 ../scripts/build_data.py   # the 18 datasets in results/data (used by the Data-type artifact)
python3 ../scripts/build_mock.py   # mock data
python3 ../scripts/build_html.py   # assembled page
```

`merge.py`, `merge2.py` and `val.py` are the ad hoc validation analyses behind the use-case verdicts. Run them from `results/` too.

## Things to know before developing further

- **Only the Hourly view is measured.** It uses 25 sampled minutes, one per hour on 2026-11-10 (there is no 23:00 sample). The Daily (91 days) and Monthly (13 weeks) series are synthetic and labelled "Illustrative". Replace them with real aggregates once the three months of per-minute logs are in ADS.
- **Fields not in the logs:** JA4, VerifiedBotCategory, request headers (`RequestHeaders` is empty in every row) and any account or token ID. Use case F (developer journey and conversion) needs an account or token key added before it can be built.
- **Definitions matter:** telemetry (OTLP) is 86% of requests and do-agent is far larger than AI clients. Exclude or separate both in any "agent" metric, and keep a 401 on MCP discovery separate from a failure (it is the expected OAuth challenge).
- **Sizing:** the sample implies about 23.4B rows and 3.3 TB compressed per month, against the 17 TB per month in the proposal. Treat that gap as an open question.
- **Page internals:** each section carries its own Monthly/Daily/Hourly switch. `gOf(el)` finds the section's granularity, `drawChart(el)` draws a chart for it and `renderSection(sec)` redraws the section.
