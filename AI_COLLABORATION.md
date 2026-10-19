# AI collaboration log

## Tool usage
- AI assistant: used to inspect the candidate brief and the supplied synthetic data pack, map file schemas, draft the pack-specific replay adapter, and review output formats.
- Python/CLI: used to inspect ZIP contents, compile modules, run the replay and official simulator, and inspect generated policy diagnostics.

## What was checked
- Read the Data Pack README, goal catalogue, intervention catalogue, messaging policy, event/profile/catalogue schemas, replay triggers/live/control/model-fault streams, pilot summary and simulator interface.
- Ran `python -m py_compile src/*.py`.
- Ran `python -m pytest -q`; tests cover event deduplication, stale/offline trigger age, current app-dialect precedence, holdout rejection, randomized-arm denominators, mock timeout fallback and the G03 rule correction.
- Ran `python -m src.main --pack-root . --out-dir sample_run --simulate` against the supplied pack and official simulator.
- Inspected simulator report for action acceptance and policy violations. For the checked seed, the simulator accepted all 715 home-page actions and reported zero policy problems.

## Corrections and rejected shortcuts
1. **Generic schema assumptions were rejected.** The supplied pack uses `user_id`, `event`, `deliver_at`, `preferred_dialect`, and an action schema with `type: home_page`, `hero_title_id`, and `rows`; the adapter was written for these actual fields.
2. **Model assertions were not accepted as evidence.** Scripted unsupported eligibility claims and malformed output are recorded but cannot override event/profile/catalogue checks. Timeout uses deterministic fallback.
3. **Served-versus-unserved uplift was rejected.** The pilot summary compares selected served viewers with everyone else. The report instead uses randomized `agent` and `holdout` assignment as the intention-to-treat denominator among goal-assigned viewers.
4. **Goals with unsupported success signals were skipped.** G10 has a null success event and G11 uses `tv_app_open`, which is absent from the supplied event vocabulary. G03's corrected rule is applied to goals that remain open at correction time.

## Human review still required
The candidate should review the source and reports, check the generated decisions for representative viewers, rerun with a second seed, and be ready to explain the goal priority order, limitations, causal measurement and fallback design in the technical discussion. This log is a factual record of checks performed in this workspace, not a claim that the system is production-ready.
