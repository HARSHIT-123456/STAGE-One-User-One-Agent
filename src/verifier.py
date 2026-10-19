from datetime import timezone
from zoneinfo import ZoneInfo
from .utils import parse_dt

IST = ZoneInfo("Asia/Kolkata")
MESSAGE_ACTIONS = {"PUSH", "WHATSAPP"}

def verify(decision, state, trigger, catalogue, arms, action_history, now):
    passed, failed = [], []
    viewer = str(decision["viewer_id"])
    if str(arms.get(viewer, "")).lower() == "holdout":
        failed.append("holdout_zero_action")
    else:
        passed.append("not_holdout")

    action = decision.get("action", "NO_ACTION")
    facts = state.get("facts", {})
    dialect = str(facts.get("app_dialect", facts.get("dialect", {})).get("value", ""))
    by_id = {str(t.get("title_id", t.get("id"))): t for t in catalogue}
    if action == "HOME_PAGE":
        valid = True
        slugs = []
        for tid in decision.get("content", []):
            t = by_id.get(str(tid))
            if not t:
                valid = False; failed.append(f"unknown_title:{tid}"); continue
            if dialect and str(t.get("dialect", t.get("language_variant", ""))) != dialect:
                valid = False; failed.append(f"wrong_dialect:{tid}")
            start, end = parse_dt(t.get("available_from")), parse_dt(t.get("available_until"))
            if (start and now < start) or (end and now >= end):
                valid = False; failed.append(f"title_unavailable:{tid}")
            slug = t.get("content_slug") or tid
            if slug in slugs:
                valid = False; failed.append(f"duplicate_content_slug:{slug}")
            slugs.append(slug)
        if len(decision.get("content", [])) < 3:
            valid = False; failed.append("homepage_fewer_than_3_titles")
        if valid: passed.append("homepage_content")
    elif action in MESSAGE_ACTIONS:
        consent_key = "notifications_opt_in" if action == "PUSH" else "whatsapp_opt_in"
        consent = facts.get(consent_key, {}).get("value", False)
        if str(consent).lower() not in ("true", "1", "yes"):
            failed.append("missing_message_consent")
        else:
            passed.append("message_consent")
        local = now.astimezone(IST)
        if local.hour >= 22 or local.hour < 8:
            failed.append("quiet_hours")
        else:
            passed.append("outside_quiet_hours")
        day = local.date().isoformat()
        already = any(a.get("viewer_id") == viewer and a.get("channel") in MESSAGE_ACTIONS and a.get("ist_day") == day for a in action_history)
        if already:
            failed.append("daily_message_cap")
        else:
            passed.append("daily_message_cap")
    else:
        passed.append("no_action")

    if failed:
        decision["checks"] = {"passed": passed, "failed": failed}
        decision["status"] = "REJECTED"
        decision["no_action_reason"] = "Verifier rejected proposed action: " + ", ".join(failed)
        decision["action"] = "NO_ACTION"
        decision["content"] = []
        return False
    decision["checks"] = {"passed": passed, "failed": []}
    decision["status"] = "PUBLISHED" if action != "NO_ACTION" else "ABSTAINED"
    return True
