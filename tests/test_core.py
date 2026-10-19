from datetime import datetime, timezone
from src.data_loader import deduplicate_events
from src.fact_resolver import resolve_viewer
from src.verifier import verify
from src.impact_report import compare_arms

def test_deduplicate_event_id():
    events = [{"event_id":"x","received_at":"2026-01-01T00:00:00Z"},
              {"event_id":"x","received_at":"2026-01-02T00:00:00Z"},
              {"event_id":"y","received_at":"2026-01-01T00:00:00Z"}]
    out = deduplicate_events(events)
    assert len([e for e in out if e["event_id"]=="x"]) == 1

def test_app_dialect_conflict_is_visible():
    profiles = [{"viewer_id":"u1","dialect":"d1","snapshot_date":"2026-01-01"}]
    events = [{"viewer_id":"u1","event_id":"e1","app_dialect":"d3","received_at":"2026-01-02T00:00:00Z"}]
    state = resolve_viewer("u1", profiles, events)
    assert state["facts"]["app_dialect"]["value"] == "d3"
    assert state["conflicts"]

def test_holdout_rejected():
    decision = {"viewer_id":"u1","action":"HOME_PAGE","content":["t1","t2","t3"],"checks":{}}
    state = {"facts":{"app_dialect":{"value":"d1"}}}
    cat = [{"title_id":f"t{i}","dialect":"d1","content_slug":f"s{i}"} for i in (1,2,3)]
    ok = verify(decision,state,{},cat,{"u1":"holdout"},[],datetime.now(timezone.utc))
    assert not ok
    assert decision["action"] == "NO_ACTION"
    assert "holdout_zero_action" in decision["checks"]["failed"]

def test_itt_includes_unserved_users():
    arms = {"a":"agent","b":"agent","c":"holdout","d":"holdout"}
    outcomes = [{"viewer_id":"a","status":"succeeded"}]
    report = compare_arms(arms,outcomes)
    assert report["agent_n"] == 2
    assert report["holdout_n"] == 2
    assert report["itt_uplift"] == 0.5

def test_real_pack_duplicate_and_late_trigger_handling():
    from src.real_replay import dedupe_events, estimate_trigger_age_seconds
    events = [
        {"event_id":"same","received_at":"2026-10-01T00:00:02Z"},
        {"event_id":"same","received_at":"2026-10-01T00:00:03Z"},
        {"event_id":"other","received_at":"2026-10-01T00:00:04Z"},
    ]
    assert len(dedupe_events(events)) == 2
    fresh = {"occurred_at":"2026-10-01T00:00:00Z","sent_at":"2026-10-01T00:00:05Z"}
    stale = {"occurred_at":"2026-09-28T00:00:00Z","sent_at":"2026-09-29T00:00:00Z"}
    assert estimate_trigger_age_seconds(fresh) == 5
    assert estimate_trigger_age_seconds(stale) > 600

def test_real_pack_app_dialect_conflict_prefers_current_setting():
    from src.real_replay import dialect_for
    dialect, source, conflicts = dialect_for(
        {"app_dialect":"d3","properties":{"deeplink":"ott://c/cmp1/d5/title/T001"}},
        {"preferred_dialect":"d1"})
    assert dialect == 'd3'
    assert source == 'trigger.app_dialect'
    assert len(conflicts) == 2

def test_replay_fault_provider_fails_safely():
    from src.model_provider import ReplayFaultProvider
    provider = ReplayFaultProvider({"e1":{"fault":"timeout","seconds":45},
                                    "e2":{"fault":"unsupported_claim","model_output":{"eligible":True}}})
    try:
        provider.propose('e1')
        assert False, 'timeout should be injected'
    except TimeoutError:
        pass
    proposal = provider.propose('e2')
    assert proposal == {"eligible":True}  # caller must treat this as proposal, not evidence

def test_corrected_goal_rule_is_explicit():
    from src.real_replay import eligibility_goal
    from datetime import datetime, timezone, timedelta
    now = datetime(2026,10,1,9,0,tzinfo=timezone.utc)
    profile = {"signup_at":(now-timedelta(days=1)).isoformat(),"subscription_status":"unknown","updated_at":now.isoformat()}
    history = [
        {"event_id":"p","user_id":"u","event":"play_started","received_at":(now-timedelta(hours=1)).isoformat(),"properties":{"title_id":"t"}},
        {"event_id":"c","user_id":"u","event":"episode_completed","received_at":(now-timedelta(hours=2)).isoformat(),"properties":{"title_id":"t","episode_id":"e"}},
        {"event_id":"o","user_id":"u","event":"app_open","received_at":(now-timedelta(minutes=2)).isoformat(),"properties":{}},
    ]
    goal = eligibility_goal(profile, history, [], {}, now, {"version":"test"}, set())
    assert goal['id'] == 'G03'
    assert goal['success_signal'] == 'app_open'
    corrected = eligibility_goal(profile, history, [], {}, now, {"version":"test"}, {'G03'})
    assert corrected['id'] == 'G03'
    assert corrected['success_signal'] == 'play_started'
