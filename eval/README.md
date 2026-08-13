# eval/ — Phase 4 evaluation harness

Built in Phase 4 (originally scoped for Phase 5 in the master brief; moved
up because Phase 4's own deliverable requires it). See `eval/REPORT.md`
for results and `PROGRESS.md` (repo root) for the full phase writeup.

```
eval/
├── benchmark.json          40-item labeled question -> (gold SQL | expected
│                            rejection) benchmark. Built by build_benchmark.py.
├── build_benchmark.py       regenerates benchmark.json (source of truth is
│                            this script, not hand-edited JSON)
├── run_eval.py               the eval harness -- runs the real agent graph
│                            against every benchmark item, scores it, writes
│                            eval/reports/{label}_summary.json + _items.json
│                            and eval/logs/{label}.jsonl + _nodes.jsonl
├── generate_report.py        builds eval/REPORT.md from two run_eval.py runs
├── REPORT.md                  the human-readable before/after eval report
├── reports/                   raw JSON output per run (summary + per-item)
└── logs/                      per-run structured logs: item-level (*.jsonl)
                              and full node-by-node agent traces (*_nodes.jsonl)
```

## Running it yourself

```bash
# 1. Phases 1-3 setup first (seeded DB, embeddings, readonly role -- see
#    root README.md / PROGRESS.md), then:

# 2. Baseline pass
LLM_PROVIDER=mock TOP_K_CONTEXT=5 python eval/run_eval.py --label before --verbose

# 3. Tuned pass
LLM_PROVIDER=mock_tuned TOP_K_CONTEXT=8 python eval/run_eval.py --label after --verbose

# 4. Regenerate the report from both
python eval/generate_report.py

# 5. With a real API key (recommended before quoting any accuracy number):
LLM_PROVIDER=anthropic python eval/run_eval.py --label real_claude --verbose
```

`--label` can be anything; `generate_report.py` currently reads `before`
and `after` specifically -- edit it (or pass a third label through) to
compare additional runs, e.g. a real-model run against the mock baseline.

**Read `eval/REPORT.md`'s "What this does and doesn't prove" section
before quoting any number from this harness anywhere, especially a
resume.** Short version: the harness and benchmark are real; the
`mock`/`mock_tuned` numbers are not evidence of real NL2SQL accuracy,
because no API key is available in this sandbox to run it against a real
model.
