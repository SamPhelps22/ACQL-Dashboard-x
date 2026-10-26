# Operation Sunday agent system

This is a small orchestration layer over the repository's existing research and validation code, not a replacement model or a new always-on service. Three Claude Code subagents have narrow responsibilities:

1. [Backtesting & Model Validation](../../.claude/agents/backtesting-model-validation.md) is the independent statistical gate.
2. [Autonomous Research Lab](../../.claude/agents/autonomous-research-lab.md) owns bounded hypotheses and isolated candidate work.
3. [Analytics & Insights](../../.claude/agents/analytics-insights.md) interprets validated evidence and proposes the next questions.

Agent definitions live in `.claude/agents/`. They run only when invoked; they do not create a daemon, schedule work, or call/spawn each other. The owner/orchestrator passes versioned artifacts in order. Use a separate git worktree for candidate implementation and do not run concurrent writers against the same experiment directory.

## Repository audit and architecture proposal

The audit covered the desktop app, generated/public website, data load and storage, production model, forecast ledger, feeds, history, research package, backtests, pool logic, and targeted tests. A broader repository map and prior audit are in [the 2026-10-24 system audit](../audit-2026-10-24/operation-sunday-audit.md); the current Lab data inventory is in [the 2026-10-26 Lab note](../lab-2026-10-26.md).

```text
commissioner spreadsheets ── sources/repository ──> ACQL dashboard and pool outcomes
ESPN / odds / schedule / injury feeds ──────────────> SQLite snapshots and forecasts
market + model inputs ── model/pricing,predictions ─> production Deadeye
forecastlog + oddslock ────────────────────────────> eligible, deadline-locked record

Prediction Tracker + nflverse history ── training/data,features,walkforward
                                         ├─ study/evaluate/strategylab
                                         ├─ lablocks: one-time, hash-chained forecasts
                                         └─ reports, hypothesis queue, scorecards

Research agent (isolated worktree) -> frozen record/candidate
       -> Validation agent (independent) -> Analytics agent -> owner decision
```

### Existing components to reuse

- `acql/training/study.py`, `walkforward.py`, `features.py`, `evaluate.py`, `probability.py`, and `strategylab.py` already provide chronological model comparisons, market/Deadeye baselines, probability metrics, uncertainty, model families, leakage checks, holdout selection, and separate probability/ACQL objectives.
- `acql/training/lablocks.py` locks experiment forecasts once before the configured deadline, refuses an existing lock or a late lock, marks files read-only, hash-chains them, and verifies edits/additions. `acql/training/record.py` separates deadline cards from late or rebuilt records.
- `acql/model/forecastlog.py` rejects late/missing timestamps from eligible scores and leaves duplicate eligible forecasts out. `acql/feeds/oddslock.py` applies the local Thursday deadline (default Thursday 6:00 p.m., configurable) or earlier first kickoff; a week with a result is also locked. `acql/model/pricing.py` and `predictions.py` preserve the locked week's values.
- `acql/model/backtest.py`, `pool/weekplan.py`, and the pool scoring modules encode game-credit and pool rules. The historical pool backtest's inferred lines and simulated roster remain proxies, not exact ACQL results.
- `acql/lab/` is the private interactive Lab; it is distinct from the research/validation package. The public page is assembled/static output in `acql/ui/pool_page/`; no public website or live prediction path is part of this agent work.

The existing protocol's gates are preferable to a rewrite: locked test weeks, preregistered criteria, multiple-test correction, common-game comparisons, leak checks, and human-only promotion. The missing ingredients are repeatable agent boundaries, a uniform cross-agent hand-off record, a persistent queue/report location, and more prospective Thursday evidence.

### Minimal implementation and safety decisions

- Use three specialized Claude Code definitions; a human orchestrates the sequence to prevent circular calls and uncontrolled spawning.
- Store exchange artifacts under `docs/operation-sunday-agents/experiments/<experiment-id>/`. The JSON Schema covers experiment, validation, and analytics records. `acql.training.agent_record` checks the record and fail-closed promotion prerequisites; it never writes or promotes production.
- Keep candidate code in a separately assigned research worktree and research-only path. Current forecasting, live data, existing forecast locks, and public pages remain owned by production maintainers.
- Reuse the current chronological and scoring evaluators; no duplicate model pipeline, external service, new package, or source-data refresh is introduced.
- Budget defaults are in the machine-readable [workflow config](./workflow-config.json): at most three hypotheses screened, one full experiment per invocation, 30 minutes compute per experiment, and one concurrent experiment. The owner may change these values there; raising limits is an explicit orchestration choice.

## Orchestration workflow

### 0. Before a run

Read this document, the current forecast/cutoff protocol, existing experiment queue/results, and uncommitted work. Confirm the intended candidate path/worktree, experiment ID, data availability, and per-run limits. Never treat `git status` changes from another user as disposable.

### 1. Research and preregistration

Invoke `autonomous-research-lab` with one explicit research question and budget. It audits existing findings, selects a falsifiable hypothesis, and creates the experiment record before the candidate sees validation outcomes. A no-network history audit can be run with:

```powershell
.venv\Scripts\python.exe -m acql.training audit --no-books
```

The record must name Deadeye, market-only, and current production model baselines as available, declare the target and ACQL rules, freezes candidate/data/code references, lists the planned subgroup comparisons and uncertainty method, and records feature timestamps. If source time is unavailable, the agent labels it unknown and cannot make deadline claims.

### 2. Candidate experiment

Implement only in the assigned isolated worktree. Use the existing `python -m acql.training lab run --protocol 2` workflow for the strategy lab and its documented one-time lock/verify/score operations. Use the narrower `bench` or existing preregistered workflow only when its limits match the hypothesis. Do not run the network `fetch`/pull commands without explicit authorization. Persist failures and generated reports; bind the result to its dataset fingerprint and code version.

Before a candidate forecast is recorded, verify the actual week's configured deadline. Do not backdate, overwrite, or reconstruct a locked forecast. Existing week locks are immutable.

### 3. Independent validation

After Research is done, invoke `backtesting-model-validation` in a separate agent turn with the frozen record and candidate artifact. It checks identical games, cutoff, scoring rules, and baseline versions; reruns/reviews the chronological evaluation; applies precommitted sample and acceptance criteria; and writes `validation.json` and `validation.md`. The validator may reject. A successful research run is not success unless the independent evidence passes.

For new records:

```powershell
.venv\Scripts\python.exe -m acql.training.agent_record validate docs\operation-sunday-agents\experiments\<experiment-id>\record.json
.venv\Scripts\python.exe -m acql.training.agent_record validate docs\operation-sunday-agents\experiments\<experiment-id>\validation.json
.venv\Scripts\python.exe -m acql.training.agent_record promotion-check docs\operation-sunday-agents\experiments\<experiment-id>\record.json docs\operation-sunday-agents\experiments\<experiment-id>\validation.json
```

`promotion-check` is expected to block without an owner approval file; even a clear run only reports prerequisites and never applies a production change.

### 4. Analytics and next queue

Only after independent validation, invoke `analytics-insights` with the record, validation, and report. It writes `insights.md`, distinguishing validated claims, descriptive patterns, speculation, sample limitations, and next falsifiable ideas. The orchestrator adds future items to [initial-backlog.md](./initial-backlog.md) only after reviewing the evidence.

### 5. Production gate

Production promotion is outside the three agents' authority. A maintainer must review the candidate diff, accepted independent validation, same-game/deadline/scoring/baseline parity, feature-time audit, sufficient distinct weeks, regression tests, and explicit owner approval. Require a separate production PR/review. Never overwrite a Thursday forecast or deploy/publish/send communications as part of research.

## Record ownership and exchange

Each experiment directory has one writer per stage; stages run sequentially:

| Artifact | Writer | Readers |
|---|---|---|
| `record.json` (preregistration and research results) | Research Lab | Validator, Analytics, owner |
| `validation.json`, `validation.md` | Validation Agent only | Analytics, owner |
| `insights.md` | Analytics Agent only | Research Lab, owner |
| candidate source and report outputs | Research Lab in isolated worktree; generated backtest files in `data/training/` | Validator, owner |

Use the schema's `experiment_record_sha256` to bind the validation to the exact canonical experiment record. Preserve each experiment as its own versioned directory; never reuse an ID or overwrite the locked-forecast evidence. Generated reports in `data/training/` are local runtime output and should not be treated as versioned hand-offs unless explicitly copied into the experiment directory.

## Setup

1. Open the repository in Claude Code. The three `.claude/agents/*.md` definitions are available by their names above.
2. Use the repository's existing environment. On Windows, this checkout has `.venv\Scripts\python.exe`; elsewhere, use the project's configured Python. No dependency install is required for the agent-record checker.
3. Read the current [baseline report](./baseline-report.md), [initial backlog](./initial-backlog.md), and [workflow config](./workflow-config.json) before the first research run.
4. Allocate a unique experiment directory and (for code work) isolated git worktree. Keep research and validation turns separate.
5. Run the safety tests with `.venv\Scripts\python.exe tests\test_agent_record.py` and the existing targeted tests listed in the baseline report.

## Sample workflow and current limitations

The [sample experiment](experiments/meta-learner-midweek-holdout-20261023/record.json) and its [independent validation record](experiments/meta-learner-midweek-holdout-20261023/validation.json) show a complete negative holdout decision: the development-favored stack was rejected after worse reported holdout results. The [analytics interpretation](experiments/meta-learner-midweek-holdout-20261023/insights.md) then turns the evidence into a bounded next step. Its historical midweek timing and prior holdout exposure are explicitly flagged; it does not meet a prospective Thursday promotion gate.

The agent system is functional as an invoked, bounded, sequential workflow. It is not a scheduled autonomous service; the agents do not call one another; no independent prospective candidate has enough immutable locked weeks to validate on this audit date. The existing data archive also does not provide complete feature-publication timestamps. The smallest next real experiment is to continue the existing lab's immutable Thursday locks until preregistered sample requirements are met, not to promote the historical example.

## Audit/change log

- Initial status showed user edits in `acql/lab/server.py`, `acql/ui/app.py`, two pool-page files, and `tests/test_lab.py`. They were inspected and not overwritten. During the audit they appeared in commit `53ac938` and no longer showed as worktree edits; this task did not create that commit. A separate edit to `acql/ui/redzone.py` was present at the final worktree check and was left untouched.
- No production prediction, model pricing, score, deadline, existing forecast, lock, public website, data source, or deployment behavior was changed.
- The local audit command wrote its standard runtime log under ignored `data/training/`; no historical source data was refreshed or downloaded.
