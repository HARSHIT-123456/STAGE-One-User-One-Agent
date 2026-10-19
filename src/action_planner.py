from datetime import timedelta
from .utils import parse_dt, iso

def available_at(title, now):
    start = parse_dt(title.get("available_from"))
    end = parse_dt(title.get("available_until"))
    return (start is None or start <= now) and (end is None or now < end)

def plan_action(state, goal, catalogue, now, intervention_rules=None):
    if not goal:
        return {"action":"NO_ACTION","content":[],"reason":"No eligible measurable goal"}
    facts = state.get("facts", {})
    dialect = str(facts.get("app_dialect", facts.get("dialect", {})).get("value", ""))
    titles = []
    seen_slugs = set()
    for t in catalogue:
        td = str(t.get("dialect", t.get("language_variant", "")))
        slug = t.get("content_slug") or t.get("title_id") or t.get("id")
        if dialect and td != dialect:
            continue
        if not available_at(t, now) or slug in seen_slugs:
            continue
        if slug:
            seen_slugs.add(slug)
        tid = t.get("title_id", t.get("id"))
        if tid:
            titles.append(str(tid))
        if len(titles) >= 4:
            break
    # Conservative default: no message. Homepage needs at least 3 valid titles.
    if len(titles) >= 3:
        return {"action":"HOME_PAGE","content":titles[:10],"reason":"Eligible goal and at least three available titles matched to app dialect"}
    return {"action":"NO_ACTION","content":[],"reason":"Fewer than three valid titles for a compliant homepage"}
