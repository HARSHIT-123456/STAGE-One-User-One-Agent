import math
from collections import defaultdict

def _rate(values):
    return sum(values) / len(values) if values else 0.0

def compare_arms(arms, outcomes):
    """Intention-to-treat: include every randomized user, even if agent took no action."""
    outcome_by_user = {}
    for o in outcomes:
        uid = str(o.get("viewer_id", o.get("user_id", "")))
        outcome_by_user.setdefault(uid, []).append(o)
    groups = defaultdict(list)
    for uid, arm in arms.items():
        rows = outcome_by_user.get(str(uid), [])
        success = any(str(r.get("status", "")).lower() == "succeeded" or r.get("success") is True for r in rows)
        groups[str(arm).lower()].append(1 if success else 0)
    treatment = groups.get("agent", groups.get("treatment", []))
    control = groups.get("holdout", groups.get("control", []))
    p1, p0 = _rate(treatment), _rate(control)
    uplift = p1 - p0
    # Wald 95% CI for difference in proportions; descriptive and unreliable for tiny samples/extreme rates.
    se = math.sqrt((p1*(1-p1)/len(treatment) if treatment else 0) + (p0*(1-p0)/len(control) if control else 0))
    return {"agent_n":len(treatment),"holdout_n":len(control),"agent_success_rate":p1,
            "holdout_success_rate":p0,"itt_uplift":uplift,"ci95":[uplift-1.96*se,uplift+1.96*se],
            "method":"intention-to-treat; all randomized users included"}
