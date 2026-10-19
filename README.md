# One User, One Agent — pack-integrated implementation

This repository is adapted to the supplied `one_user_one_agent_pack`. It includes the original synthetic data pack and the official outcome simulator so the replay can be run without manually moving files around.

## Requirements
- Python 3.10+ (3.11 or 3.12 recommended)
- No external packages are required for the replay or simulator.

## Run on Windows (PowerShell)
From the `STAGE-One-User-One-Agent` project folder:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m src.main --pack-root . --out-dir sample_run --simulate
```

If `py -3.12` is not installed, use `py -m venv .venv` and activate it. No API key is required.

## Run in Git Bash
```bash
python -m venv .venv
source .venv/Scripts/activate
python -m src.main --pack-root . --out-dir sample_run --simulate
```

The command runs the supplied trigger replay, writes simulator actions in the required schema, runs `simulator/simulate_outcomes.py`, and judges goal outcomes from the generated outcome event stream.

## Main outputs
- `sample_run/decisions.jsonl` — one auditable decision per trigger, including abstentions.
- `sample_run/actions.jsonl` — action schema consumed by the official simulator; holdout viewers receive no action.
- `sample_run/viewer_state/*.json` — per-viewer active goal and decision/action history.
- `sample_run/outcomes.jsonl` — goal-specific outcome judgments from simulator events.
- `sample_run/latency_report.json` — processing time and replay counts.
- `sample_run/impact_report.json` and `.md` — randomized-arm intention-to-treat comparison among viewers assigned a measurable goal.
- `sample_run/simulator_output/` — simulator outcome events and simulator report.
- `sample_run/simulator_quality_report.json` — simulator policy diagnostics.

## Design choices
- The current app dialect from the trigger is preferred over the stale profile dialect and campaign link; conflicts are recorded.
- Profile rows are resolved by latest `updated_at`; event evidence is deduplicated by `event_id` and bounded by server receipt time.
- The agent chooses one measurable goal per viewer. Goals G10 and G11 are not selected because the supplied event stream does not contain a reliable success event for them. G03 uses the corrected `play_started` success signal.
- Only personalized home pages are published in this version. Messages are deliberately not used, avoiding consent, quiet-hours, template, and daily-frequency risks while retaining a real intervention.
- A page is built from available titles in the active app dialect. Catalogue descriptions are treated as untrusted data, never instructions.
- The independent verifier checks holdout assignment, dialect, availability, row size, and duplicate content slugs.
- Injected model faults are recorded and never treated as evidence. The implementation is deterministic and needs no external LLM or personal API key.
- The supplied simulator is run with a reproducible seed. The report is one synthetic run and should not be represented as production impact.

## Important limitations
This is a practical take-home implementation, not a production-ready lifecycle platform. See `KNOWN_LIMITATIONS.md` for exact limitations. Review the source and generated outputs before submission; you remain responsible for the code and for explaining the design in the technical discussion.



# STAGE-One-User-One-Agent

A Python-based prototype of a goal-directed AI agent for an OTT streaming platform.

## Overview

The project processes viewer events and available evidence to select measurable goals, decide whether to intervene, validate actions against policy constraints, and evaluate outcomes using a randomized holdout group.

## Key Features

- Viewer goal selection and decision-making
- Evidence conflict resolution
- Safe action validation and no-action decisions
- Duplicate and late event handling
- Dependency-failure handling
- Event replay and simulated action evaluation
- Randomized holdout and intention-to-treat impact analysis
- Automated tests

## Technology Stack

- Python
- pytest
- JSONL event data and JSON reports
- Command-line execution

## Run the Project

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the simulation:

```bash
python -m src.main --pack-root . --out-dir sample_run --simulate
```

Run the tests:

```bash
python -m pytest -v
```

## Current Test Results

The current test suite passes all 8 tests.

The sample simulation produced 2,769 decisions, 715 published homepage actions, and zero detected policy problems in the simulator quality report.

The estimated agent-versus-holdout success-rate difference was +0.94 percentage points, with an approximate 95% confidence interval of -1.80 to +3.67 percentage points. This is a single synthetic simulation, not evidence of a proven production impact.

## Limitations

This is a prototype evaluated using the supplied data and simulator. Results should not be interpreted as proof of real-world business impact.