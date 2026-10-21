# Three-Pass Pattern Scan

Pass 1 checks input-loader files; Pass 2 inspects decision, model-fault and verifier logs; Pass 3 checks action/outcome counts and interprets zero counts.

## Pass 1 — Input loader
- Required input files: 9
- Missing input files: 0

## Pass 2 — Agent decisions, model and verifier logs
- Decisions inspected: 2769
- Published actions referenced by decisions: 715
- Model fault records: 5
- Model claims accepted as evidence: 0
- Expected guardrail blocks (e.g. holdout): 1325
- Unexpected verification failures: 0
- Holdout action violations: 0

## Pass 3 — Output logs and zero-count inspection
- Action records: 715
- Outcome records: 1504
- `zero_input_files_missing`: True
- `zero_decisions`: False
- `zero_published_actions`: False
- `zero_model_faults`: False
- `zero_unexpected_verification_failures`: True
- `zero_simulator_policy_problems`: True
- `zero_outcome_rows`: False

## Findings
- **INFO** `NO_AUDIT_FINDINGS` — count: 0

A zero count is a measurement, not automatically a failure: for example, zero simulator policy problems is desirable, while zero decisions may indicate a failed or empty replay.
