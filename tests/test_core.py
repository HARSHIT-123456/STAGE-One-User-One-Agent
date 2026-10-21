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

def test_deduplication_keeps_distinct_idless_events_and_removes_exact_copies():
    from src.data_loader import deduplicate_events
    rows = [
        {"user_id": "u1", "event": "app_open", "received_at": "2026-10-01T08:30:00Z"},
        {"user_id": "u1", "event": "app_open", "received_at": "2026-10-01T08:30:00Z"},
        {"user_id": "u1", "event": "play_started", "received_at": "2026-10-01T08:31:00Z"},
    ]
    result = deduplicate_events(rows)
    assert len(result) == 2
    assert {row["event"] for row in result} == {"app_open", "play_started"}


def test_replay_deduplication_preserves_idless_rows_and_earliest_duplicate():
    from src.real_replay import dedupe_events
    rows = [
        {"event_id": "e1", "received_at": "2026-10-01T08:31:00Z", "event": "late"},
        {"event_id": "e1", "received_at": "2026-10-01T08:30:00Z", "event": "early"},
        {"user_id": "u1", "event": "app_open", "received_at": "2026-10-01T08:30:00Z"},
    ]
    result = dedupe_events(rows)
    assert len(result) == 2
    assert next(row for row in result if row.get("event_id") == "e1")["event"] == "early"
    assert any(row.get("event") == "app_open" for row in result)

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

def test_pattern_scan_reports_three_passes_and_zero_interpretation(tmp_path):
    import json
    from src.pattern_scan import scan_run
    root = tmp_path / 'pack'
    out = tmp_path / 'run'
    (root / 'data').mkdir(parents=True)
    (root / 'replay').mkdir()
    (root / 'config').mkdir()
    for name in ('data/events.jsonl', 'data/profiles_snapshot.csv', 'data/catalogue.csv',
                 'data/episodes.csv', 'replay/arms.csv', 'replay/triggers.jsonl',
                 'replay/live_events.jsonl', 'replay/control_events.jsonl', 'config/goals.json'):
        (root / name).write_text('', encoding='utf-8')
    out.mkdir()
    (out / 'decisions.jsonl').write_text(json.dumps({
        'decision_id':'D-1','user_id':'u1','trigger':{},'action':'NO_ACTION','status':'ABSTAINED',
        'checks':{'passed':[],'failed':[]},'arm':'agent',
        'model_verification':{'proposal_used_as_evidence':False}
    }) + '\n', encoding='utf-8')
    (out / 'actions.jsonl').write_text('', encoding='utf-8')
    (out / 'outcomes.jsonl').write_text('', encoding='utf-8')
    report = scan_run(root, out)
    assert set(report['passes']) == {'1_input_loader','2_agent_and_model_verification','3_outputs_and_zero_log_inspection'}
    assert report['passes']['2_agent_and_model_verification']['decision_count'] == 1
    assert report['passes']['3_outputs_and_zero_log_inspection']['zero_checks']['zero_decisions'] is False
    assert (out / 'pattern_scan_report.md').exists()


def test_pattern_scan_detects_model_claim_accepted_as_evidence(tmp_path):
    import json
    from src.pattern_scan import scan_run
    root = tmp_path / 'pack'; out = tmp_path / 'run'
    (root / 'data').mkdir(parents=True); (root / 'replay').mkdir(); (root / 'config').mkdir(); out.mkdir()
    for name in ('data/events.jsonl', 'data/profiles_snapshot.csv', 'data/catalogue.csv',
                 'data/episodes.csv', 'replay/arms.csv', 'replay/triggers.jsonl',
                 'replay/live_events.jsonl', 'replay/control_events.jsonl', 'config/goals.json'):
        (root / name).write_text('', encoding='utf-8')
    row={'decision_id':'D-1','user_id':'u1','trigger':{},'action':'NO_ACTION','status':'ABSTAINED',
         'checks':{'passed':[],'failed':[]},'model_fault':{'fault':'unsupported_claim','proposal_accepted_as_evidence':True}}
    (out/'decisions.jsonl').write_text(json.dumps(row)+'\n',encoding='utf-8')
    (out/'actions.jsonl').write_text('',encoding='utf-8')
    (out/'outcomes.jsonl').write_text('',encoding='utf-8')
    report=scan_run(root,out)
    assert any(f['code']=='MODEL_CLAIM_USED_AS_EVIDENCE' for f in report['findings'])


def test_g03_rule_correction_uses_exact_0830_utc_instant():
    from src.real_replay import G03_RULE_CORRECTION_AT, g03_success_signal
    from datetime import timedelta

    correction = G03_RULE_CORRECTION_AT
    assert correction.isoformat() == "2026-10-01T08:30:00+00:00"
    # A goal open across the correction receives the corrected success signal.
    assert g03_success_signal("2026-10-01T08:00:00Z", "2026-10-01T09:00:00Z") == "play_started"
    # Equivalent offset timestamps are normalized to the same UTC instant.
    assert g03_success_signal("2026-10-01T10:00:00+02:00", "2026-10-01T11:00:00+02:00") == "play_started"
    # Goals starting at or ending exactly on the correction are not considered open across it.
    assert g03_success_signal(correction, correction + timedelta(hours=1), "app_open") == "app_open"
    assert g03_success_signal(correction - timedelta(hours=1), correction, "app_open") == "app_open"
    # Goals fully after the correction retain their configured signal.
    assert g03_success_signal(correction + timedelta(minutes=1), correction + timedelta(hours=1), "play_started") == "play_started"
