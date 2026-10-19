# Replay impact report

- Agent arm: 64/758 goal-assigned viewers succeeded (8.4%).
- Holdout arm: 56/746 goal-assigned viewers succeeded (7.5%).
- Difference (agent − holdout): 0.94 percentage points.
- Approximate 95% CI: [-1.80, 3.67] percentage points.

**Interpretation caution:** This replay is one synthetic simulator run and only goal-assigned viewers are in this goal-specific estimate. Do not interpret as a production causal effect; inspect simulator policy problems and assignment balance.

## Why the pilot headline is not causal
The supplied pilot summary compares 217 served viewers with 3,674 other users, even though the assignment file contains randomized agent and holdout arms. Served status is post-randomization and strongly selected; users who received an action may differ in engagement, eligibility, or ability to be served. Use the randomized arm as the denominator (intention-to-treat), not served-versus-unserved.
