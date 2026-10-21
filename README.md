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
- Profile rows are resolved by latest `updated_at`; event evidence is deduplicated by `event_id` and bounded by server receipt time. Duplicate IDs retain the earliest server `received_at`; ID-less events are preserved unless their complete payload is an exact duplicate.
- The agent chooses one measurable goal per viewer. Goals G10 and G11 are not selected because the supplied event stream does not contain a reliable success event for them. G03's rule correction is applied at **2026-10-01 08:30:00 UTC** to goals already open across that instant; timezone-aware boundary tests cover this behavior.
- Only personalized home pages are published in this version. Messages are deliberately not used, avoiding consent, quiet-hours, template, and daily-frequency risks while retaining a real intervention.
- A page is built from available titles in the active app dialect. Catalogue descriptions are treated as untrusted data, never instructions.
- The independent verifier checks holdout assignment, dialect, availability, row size, and duplicate content slugs.
- Injected model faults are recorded and never treated as evidence. The implementation is deterministic and needs no external LLM or personal API key.
- The supplied simulator is run with a reproducible seed. The report is one synthetic run and should not be represented as production impact.

## Important limitations
This is a practical take-home implementation, not a production-ready lifecycle platform. See `KNOWN_LIMITATIONS.md` for exact limitations. Review the source and generated outputs before submission; you remain responsible for the code and for explaining the design in the technical discussion.

## Agent audit and pattern scan (new)
Every full pack replay now writes two additional artifacts:
- `pattern_scan_report.json` — machine-readable, three-pass audit.
- `pattern_scan_report.md` — human-readable explanation for a reviewer.

The scanner performs three passes:
1. **Input loader inspection:** confirms required data/config/replay files exist and reports their sizes.
2. **Agent/model verification inspection:** summarizes decisions and action types, missing audit fields, injected model faults, verifier checks, and any model claims incorrectly accepted as evidence. The model proposal is not treated as evidence; deterministic rules and independent checks remain authoritative.
3. **Output and zero-count inspection:** checks action/outcome counts, duplicate or orphan action IDs, holdout violations, simulator policy diagnostics, and explicitly explains zero counts. A zero count is not automatically an error: zero policy violations is good, while zero decisions may indicate an empty run.

Run the complete pipeline, including the scanner:

```bash
python -m src.main --pack-root . --out-dir sample_run --simulate
```

The scan is deterministic and rule-based, not a learned anomaly detector. It is intended to make agent behavior and verification easier to inspect during code review.

## Continuous integration
GitHub Actions runs the test suite on pushes and pull requests using Python 3.12. Run the same check locally with `python -m pytest -v`.
