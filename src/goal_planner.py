from datetime import timedelta
from .utils import parse_dt, iso

def _event_type(e):
    return str(e.get("event_type", e.get("event", ""))).lower()

def choose_goal(state, goals, now):
    """Conservative generic goal selector. Adapt rule keys to the supplied goals.json schema."""
    events = state.get("events", [])
    facts = state.get("facts", {})
    sub = str(facts.get("subscription_status", {}).get("value", "")).lower()
    signup = facts.get("signup_at", facts.get("signup_date", {})).get("value")
    candidates = goals if isinstance(goals, list) else goals.get("goals", [])
    for goal in candidates:
        gid = goal.get("id", goal.get("goal_id"))
        name = str(gid or "").lower()
        # Never select a goal explicitly marked unmeasurable.
        if goal.get("success_event") in (None, "", []):
            continue
        eligibility = str(goal.get("eligibility", "")).lower()
        if "paid" in name and ("paid" in sub or "active" in sub):
            continue
        if "signup" in eligibility and not signup:
            continue
        if "eligibility" in goal and isinstance(goal["eligibility"], dict):
            # Unknown structured conditions are not guessed.
            continue
        window = goal.get("window_days", goal.get("window", 3))
        try:
            days = int(window)
        except (ValueError, TypeError):
            days = 3
        deadline = now + timedelta(days=days)
        return {"id": gid or "unknown_goal", "deadline": iso(deadline),
                "success_signal": goal.get("success_event"), "rule": goal,
                "assumption": "Goal eligibility interpretation is conservative; inspect and map goals.json rules."}
    return None
