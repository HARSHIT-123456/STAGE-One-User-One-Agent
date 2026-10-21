# Agent Behavior, Model Verification, and Pattern Scan

## What the agent does

For each eligible replay trigger, the agent loads the viewer's profile and event history available by the trigger's server delivery time, deduplicates event IDs, resolves the current app dialect, and selects at most one measurable goal. It proposes a personalized home page only when the viewer is in the randomized agent arm and the trigger is not stale or already served. The independent verifier checks that the action is not sent to holdout, every title exists and is available, dialects match, and rows contain at least three titles without duplicate content slugs. If checks fail or no safe action is available, it abstains and records why.

## Model verification

This implementation does not call an external LLM. The assignment's model faults are replayed deterministically to test failure handling. Timeout, malformed output, and unsupported-claim cases are recorded. A model proposal is never accepted as evidence for eligibility or safety; the deterministic policy and independent verifier remain authoritative. Each decision records the model-verification mode and the checks used.

## Three-pass pattern scan

The scanner creates `pattern_scan_report.json` and `pattern_scan_report.md`:

1. **Input loader:** required input files, missing-file checks, and file sizes.
2. **Agent/model/verifier logs:** decision/action counts, missing decision fields, model faults, claims accepted as evidence, verification blocks, and holdout publication violations.
3. **Outputs and zero counts:** action/outcome counts, duplicate/orphan action IDs, simulator policy-problem count, and explicit zero-count interpretation.

The scanner is rule-based and reproducible. It does not claim to be an ML anomaly detector. Expected guardrail blocks, such as refusing to publish to holdout, are distinguished from unexpected verification failures.

## Latest local validation

The current project test suite passes **10 tests**. One full synthetic replay produced 2,769 decisions, 715 published home-page actions, 1,504 goal-assigned outcome records, five injected model-fault records handled safely, zero model claims accepted as evidence, zero unexpected verification failures, and zero simulator policy problems. The agent-versus-holdout estimated difference was +0.94 percentage points with an approximate 95% interval from -1.80 to +3.67 percentage points. This is one synthetic run, not proof of production causal impact.


## Duplicate-event policy

- Same non-empty `event_id`: retain one record, preferring the earliest non-empty server `received_at` timestamp.
- Missing `event_id`: preserve distinct records; collapse only byte-equivalent JSON payloads after canonical key sorting.
- Output order is stable by `received_at` and then `event_id`.
- Duplicate removal is not treated as a model verification pass; it is deterministic input hygiene and should be covered by tests.

## UTC rule correction

G03's success signal correction takes effect at `2026-10-01T08:30:00Z` (08:30 UTC). Goals already active before that instant and whose deadline remains after it use `play_started` as the success signal. Timestamp inputs are normalized to UTC, including ISO-8601 values with offsets. Goals starting exactly at 08:30 UTC or ending exactly then are not treated as open across the correction.
