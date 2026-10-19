from .utils import parse_dt

def _latest(rows, time_field="received_at"):
    return sorted(rows, key=lambda r: parse_dt(r.get(time_field)).timestamp() if parse_dt(r.get(time_field)) else -1)[-1] if rows else None

def resolve_viewer(viewer_id, profiles, events):
    profiles = [p for p in profiles if str(p.get("viewer_id", p.get("user_id", ""))) == str(viewer_id)]
    events = [e for e in events if str(e.get("viewer_id", e.get("user_id", ""))) == str(viewer_id)]
    profile = _latest(profiles, "snapshot_date") or (profiles[-1] if profiles else {})
    facts, conflicts = {}, []

    def set_fact(name, value, source, at=None):
        if value is not None and value != "":
            facts[name] = {"value": value, "source": source, "observed_at": at, "freshness": "source_timestamped" if at else "unknown"}

    # Profile is a baseline. Event updates override status-like facts when their event type is recognized.
    for key in ("signup_at", "signup_date", "subscription_status", "app_dialect", "dialect",
                "notifications_opt_in", "whatsapp_opt_in", "viewer_id"):
        if profile.get(key) not in (None, ""):
            set_fact(key, profile[key], "profiles_snapshot.csv", profile.get("snapshot_date"))

    dialect_events = [e for e in events if e.get("app_dialect")]
    if dialect_events:
        latest_dialect = _latest(dialect_events, "received_at")
        app_dialect = latest_dialect.get("app_dialect")
        profile_dialect = profile.get("dialect", profile.get("app_dialect"))
        if profile_dialect and app_dialect != profile_dialect:
            conflicts.append({"fact":"dialect","profile":profile_dialect,"event_app_dialect":app_dialect,"resolution":"latest event app_dialect; actual app setting is authoritative"})
        set_fact("app_dialect", app_dialect, f"event:{latest_dialect.get('event_id','unknown')}", latest_dialect.get("received_at"))

    # Explicit opt-out is sticky unless a later explicit opt-in event exists.
    consent_events = [e for e in events if str(e.get("event_type", e.get("event", ""))).lower() in
                      ("notification_opt_out", "notification_opt_in", "whatsapp_opt_out", "whatsapp_opt_in")]
    for e in sorted(consent_events, key=lambda r: parse_dt(r.get("received_at")).timestamp() if parse_dt(r.get("received_at")) else -1):
        typ = str(e.get("event_type", e.get("event", ""))).lower()
        if typ == "notification_opt_out": set_fact("notifications_opt_in", False, f"event:{e.get('event_id')}", e.get("received_at"))
        if typ == "notification_opt_in": set_fact("notifications_opt_in", True, f"event:{e.get('event_id')}", e.get("received_at"))
        if typ == "whatsapp_opt_out": set_fact("whatsapp_opt_in", False, f"event:{e.get('event_id')}", e.get("received_at"))
        if typ == "whatsapp_opt_in": set_fact("whatsapp_opt_in", True, f"event:{e.get('event_id')}", e.get("received_at"))

    return {"viewer_id": str(viewer_id), "facts": facts, "conflicts": conflicts,
            "events": events, "profile_rows_seen": len(profiles)}
