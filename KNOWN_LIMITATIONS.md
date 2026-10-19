# Known limitations

- The agent publishes only personalised home pages. Push, WhatsApp and in-app messaging are not enabled, even though their policy and templates are loaded in the supplied pack.
- Goal selection uses a conservative priority ordering. It maps the supplied goal definitions to available event signals, but it is not a learned policy and does not optimize value or exploration.
- G07 unfinished-episode detection is an approximation based on available play/completion history and episode catalogue data; episode progress is not fully reconciled across every late/duplicate event edge case.
- Only one goal is assigned per viewer during this replay. It does not open a second goal after a goal succeeds or expires later in the 14-day simulator horizon.
- Dependency outages are represented in audit metadata and handled through the preloaded local cache; the code does not emulate an actual remote database's 8-second p95 or 20% timeout behavior.
- The mock model timeout is injected immediately rather than sleeping for the specified 45 seconds, so the replay remains runnable and stays within the 60-second budget. The timeout/fault is still visible in the decision audit and deterministic fallback is used.
- Confidence values are heuristic, not calibrated probabilities.
- The impact report is limited to viewers assigned a measurable goal and to one synthetic simulator seed. Confidence intervals are approximate; the effect estimate is not evidence of production impact.
- Durable state output is JSON per viewer for audit convenience; this is not a high-concurrency transactional state service.
- Review the decisions and generated reports manually before submission. The candidate is responsible for understanding and defending all code and claims.
