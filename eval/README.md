# eval/ — Multi-Agent Pipeline Evaluation Harness

## Purpose

The `eval/` directory contains a fixed evaluation set used to measure the pipeline's correctness, retry behaviour, and failure-mode handling in a repeatable way.  
Running the harness gives you three concrete metrics:

| Metric | What it proves |
|--------|---------------|
| **Pass rate** | Agents call the right tools and produce the expected verdict (pass / fail / exhausted) |
| **Retry rate** | The CodeGen → Reviewer retry loop fires when it should |
| **Duration (p50 / max)** | End-to-end latency stays within the "a few minutes" NFR |

---

## Prerequisites

All services must be running before executing the harness:

| Service | Default port |
|---------|-------------|
| Webapp backend | 8020 |
| Planner agent | 8010 |
| RAG agent | 8011 |
| DB agent | 8012 |
| DB executor | 8013 |
| CodeGen agent | 8014 |
| Reviewer agent | 8015 |

Start all agents (example using the startup scripts):

```bash
# Linux / macOS
bash scripts/start_all.sh

# Windows PowerShell
.\scripts\start_all.ps1
```

Or start each agent individually (see each agent's `README.md` for the exact `uvicorn` command).

---

## Running the evaluation

```bash
# From the repo root — default target is http://localhost:8020
python eval/run_eval.py

# Override the backend URL
python eval/run_eval.py --base-url http://localhost:8020

# Extend per-case timeout (seconds) for slow hardware
python eval/run_eval.py --timeout 600
```

The script prints one line per case as it completes, then writes `eval/results.csv` and prints a summary block.

---

## The 12 test cases

### Happy-path cases (E01–E06)

| ID | Description | Agents | What it tests |
|----|-------------|--------|--------------|
| E01 | List open tasks for a user | Planner → RAG → DB | Basic DB query with RAG schema context |
| E02 | REST endpoint: search tasks by project | Planner → RAG → CodeGen → Reviewer | CodeGen passes review on first attempt |
| E03 | Health-check endpoint with projects summary | Planner → RAG → CodeGen → Reviewer | CodeGen must read projects schema from RAG |
| E04 | SQL migration: add `archived_at` to projects | Planner → DB | DB migration without CodeGen |
| E05 | Task model fields and status values | Planner → RAG | Pure RAG retrieval, no code generated |
| E06 | React task-card component | Planner → CodeGen → Reviewer | Frontend JSX generation + review |

### Retry-trigger cases (E07–E08)

These cases contain requests the Reviewer is **expected to reject**, exercising the retry loop.

| ID | Description | Trigger | Expected outcome |
|----|-------------|---------|-----------------|
| E07 | Python function using `eval()`, no docstring | SEC001 (eval) + REQ001 (missing docstring) | `exhausted` — proves retry loop fires |
| E08 | Utility using `exec()`, no type hints | SEC002 (exec, critical) | `exhausted` — security rule blocks on retry |

### Adversarial cases (E09–E12)

| ID | Description | Expected outcome | What is tested |
|----|-------------|-----------------|----------------|
| E09 | "Make the app better" (vague) | `pass` | Planner handles ambiguous input gracefully |
| E10 | DROP TABLE tasks | `fail` | DB Agent blocks destructive DDL |
| E11 | DELETE all users (no WHERE) | `fail` | DB Agent flags unbounded DELETE |
| E12 | Empty feature request (`""`) | HTTP 422 | Pydantic `min_length=1` rejects before pipeline |

> **"pass" for adversarial cases** means the pipeline behaved *correctly* for the adversarial input — e.g. blocking a dangerous query or returning 422 for an empty request.  
> A `fail` expected_verdict for E10/E11 means the DB Agent *should* return a blocked/error status; the eval harness marks those as a harness-pass when the DB Agent does so.

---

## results.csv columns

| Column | Type | Description |
|--------|------|-------------|
| `id` | string | Case identifier (E01–E12) |
| `feature_request` | string | The raw input sent to the pipeline |
| `agents_called` | pipe-separated string | Unique agent names detected in the run's step log, e.g. `planner-agent\|rag-agent\|db-agent` |
| `retry_count` | integer | Number of steps where `attempt_number > 1` (i.e. how many retries fired) |
| `final_verdict` | string | Verdict extracted from the last Reviewer step, or `overall_status` if no Reviewer was involved |
| `total_duration_ms` | integer | Wall-clock ms from pipeline start to completion, as recorded in the run log |
| `pass` | boolean | `True` if `final_verdict == expected_verdict` (or `overall_status == "success"` for non-adversarial cases) |

---

## Interpreting the summary output

After all cases complete, the script prints:

```
====================================================
  EVALUATION SUMMARY
====================================================
  Total cases   : 12
  Pass          : 10
  Fail          : 2
  Pass rate     : 83.3%
  Avg duration  : 4210 ms
  p50 duration  : 3850 ms       ← median end-to-end latency
  Max duration  : 18420 ms      ← worst-case (usually a retry case)
  Retry rate    : 16.7% (2/12 cases)
====================================================
```

- **p50 duration** is the median — half of cases finish faster than this.  
- **Max duration** is typically one of E07/E08 because those cases go through two CodeGen + Reviewer round-trips.  
- **Retry rate** should be ≥ 16 % (at least E07 and E08) when the retry loop is working correctly.

---

## Committing results

After a full successful run, commit `eval/results.csv` as evidence:

```bash
git add eval/results.csv
git commit -m "eval: add run results from Phase 6"
```
