# Architecture — One User, One Agent

## Ownership and state
A single per-viewer goal is selected from the supplied goal catalogue and retained for that viewer during the replay. `viewer_state/<user_id>.json` records the profile snapshot, selected goal, decision IDs and action IDs. Decisions are append-only JSONL audit records. Duplicate trigger event IDs are idempotently abstained from.

## Decision flow
`triggers.jsonl` (ordered by `deliver_at`) -> incorporate only live events delivered by that time -> resolve current dialect and conflicts -> freshness gate -> choose one measurable goal -> propose a personalised home page -> independent verifier -> publish action or record no action -> run supplied simulator -> judge outcome signals -> compare randomized arms.

## Evidence and conflicts
- `received_at`/`deliver_at` is used as the server-side ordering clock.
- Event history is deduplicated by `event_id` and bounded to events received by the decision time.
- The current trigger's `app_dialect` wins over `preferred_dialect` in the daily snapshot and dialect embedded in a campaign link. Conflicts remain in the decision.
- Profile rows are resolved by the latest `updated_at`; profile values are treated as a daily baseline, not live truth.
- The title catalogue is treated as data, never as instructions. Availability, dialect and `content_slug` uniqueness are independently verified.

## Goal planning
The implementation maps supplied goals to observable event signals. G10 is skipped because its success signal is null. G11 is skipped because `tv_app_open` is absent from the supplied event vocabulary. G03 initially follows the supplied rule, then the 08:30Z correction changes the signal to `play_started`; the outcome judge applies the correction to goals still open at correction time. Only one goal is assigned per viewer for this replay.

## Actions and safety
Only `home_page` actions are enabled in this implementation. This avoids introducing unnecessary messaging risk while still producing a real intervention consumed by the official simulator. A page contains a dialect-matched hero and/or a row with at least three available titles. The independent verifier rejects holdout actions, unknown/unavailable/wrong-dialect titles, too-small rows and duplicate content slugs. The official simulator reports zero policy problems for the checked run.

## Faults, latency and recovery
The replay mock provider injects the specified `unsupported_claim`, malformed-output and timeout faults. Model proposals are never accepted as evidence; the deterministic planner is the fallback and no external model is required. Dependency outage/degradation windows are recorded in decision metadata; because this version preloads the synthetic pack into a local read-only snapshot, it continues from that cache during the data-store degradation window. Processing time is measured locally and publication timestamps are set to trigger delivery time plus measured processing time.

## Measurement
The official `simulator/simulate_outcomes.py` is run against generated actions. Goal outcomes are judged from its `outcome_events.jsonl` within the goal's deadline. The report compares randomized `agent` and `holdout` arms on an intention-to-treat basis among viewers assigned a measurable goal; users are retained in their randomized arm even when no action is published. The result is one synthetic seed and is not a production causal claim.

## Scaling path
For production, partition the queue by user ID, persist goal state in a transactional store, add event-time watermarks and a durable outbox, bound external dependencies with deadlines/circuit breakers, and preserve a synchronous independent verifier before any publish call.
