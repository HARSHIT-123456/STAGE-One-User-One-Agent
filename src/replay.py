import time
from datetime import datetime, timezone
from pathlib import Path
from .data_loader import load_pack
from .fact_resolver import resolve_viewer
from .goal_planner import choose_goal
from .action_planner import plan_action
from .verifier import verify
from .models import Decision
from .utils import parse_dt, iso, write_jsonl, read_csv_rows, read_jsonl, read_json

def load_arms(path):
    rows = read_csv_rows(path)
    arms = {}
    for r in rows:
        uid = r.get("viewer_id", r.get("user_id"))
        arm = r.get("arm", r.get("assignment", ""))
        if uid:
            arms[str(uid)] = str(arm).lower()
    return arms

def run_replay(data_dir, config_dir, replay_dir, out_dir):
    data_dir, config_dir, replay_dir, out_dir = map(Path, (data_dir, config_dir, replay_dir, out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    pack = load_pack(data_dir, replay_dir)
    goals = read_json(config_dir / "goals.json", {"goals":[]})
    arms = load_arms(replay_dir / "arms.csv")
    triggers = pack["triggers"] or pack["events"]
    # Only process app-open-like triggers; map actual event names after inspecting the pack.
    triggers = [e for e in triggers if str(e.get("event_type", e.get("event", ""))).lower() in ("app_open", "login", "app_opened")]
    decisions, actions, outcomes = [], [], []
    history = []
    for i, trigger in enumerate(triggers, 1):
        start_clock = time.perf_counter()
        uid = str(trigger.get("viewer_id", trigger.get("user_id", "")))
        received = parse_dt(trigger.get("received_at"))
        occurred = parse_dt(trigger.get("occurred_at"))
        if not uid or not received:
            decisions.append({"decision_id":f"D-{i:06d}","viewer_id":uid,"action":"NO_ACTION",
                              "no_action_reason":"Missing viewer_id or trustworthy received_at","status":"ABSTAINED"})
            continue
        age_s = max(0, (received - occurred).total_seconds()) if occurred else None
        state = resolve_viewer(uid, pack["profiles"], pack["events"])
        state["events"] = [e for e in pack["events"] if str(e.get("viewer_id", e.get("user_id", ""))) == uid]
        if age_s is not None and age_s > 24*3600:
            d = {"decision_id":f"D-{i:06d}","viewer_id":uid,"trigger":{"event_id":trigger.get("event_id"),"received_at":iso(received),"event_age_s":age_s},
                 "goal":None,"action":"NO_ACTION","no_action_reason":"Stale offline-buffered trigger","status":"ABSTAINED",
                 "checks":{"passed":["freshness_checked"],"failed":[]},"decided_in_ms":int((time.perf_counter()-start_clock)*1000)}
            decisions.append(d); continue
        goal = choose_goal(state, goals, received)
        plan = plan_action(state, goal, pack["catalogue"], received)
        dialect_fact = state["facts"].get("app_dialect", state["facts"].get("dialect", {}))
        d = Decision(decision_id=f"D-{i:06d}", viewer_id=uid,
            trigger={"event_id":trigger.get("event_id"),"event":"app_open","received_at":iso(received),"event_age_s":age_s},
            goal={"id":goal["id"],"deadline":goal["deadline"],"success_signal":goal["success_signal"]} if goal else None,
            action=plan["action"], dialect={"used":dialect_fact.get("value"),"source":dialect_fact.get("source"),"conflicts":state.get("conflicts",[])},
            content=plan["content"], confidence=0.65 if goal else 0.2,
            confidence_reason="Rule-based eligibility and catalogue checks; confidence is heuristic, not calibrated.",
            evidence=[{"source":"profiles_snapshot.csv","freshness":"snapshot-dependent"},{"source":"events.jsonl","freshness":"ordered by received_at"}],
            assumptions=[plan["reason"]], conflicts=state.get("conflicts",[]),
            decided_in_ms=int((time.perf_counter()-start_clock)*1000),
            deadline=goal.get("deadline") if goal else None, success_signal=goal.get("success_signal") if goal else None,
            no_action_reason=plan["reason"] if plan["action"]=="NO_ACTION" else None)
        verify(d.to_dict(), state, trigger, pack["catalogue"], arms, history, received)
        row = d.to_dict()
        # Verifier may mutate dict, so verify the same serialized decision.
        verify(row, state, trigger, pack["catalogue"], arms, history, received)
        decisions.append(row)
        if row.get("status") == "PUBLISHED":
            action = {"action_id":f"A-{i:06d}","viewer_id":uid,"decision_id":row["decision_id"],
                      "channel":row["action"],"content":row.get("content",[]),"published_at":iso(received),
                      "ist_day":received.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date().isoformat()}
            actions.append(action); history.append(action)
    write_jsonl(out_dir / "decisions.jsonl", decisions)
    write_jsonl(out_dir / "actions.jsonl", actions)
    write_jsonl(out_dir / "outcomes.jsonl", outcomes)
    latencies = [d.get("decided_in_ms",0) for d in decisions]
    latency = {"decision_count":len(decisions),"published_action_count":len(actions),
               "max_processing_ms":max(latencies, default=0),"within_60_seconds":all(x <= 60000 for x in latencies),
               "note":"Processing latency is measured locally; published_at is currently trigger received_at and must be adjusted to measured publication time for production-grade replay."}
    import json
    (out_dir / "latency_report.json").write_text(json.dumps(latency, indent=2), encoding="utf-8")
    return {"decisions":len(decisions),"actions":len(actions),"latency":latency}

def run_demo(out_dir):
    from datetime import datetime, timezone
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    demo = [{"decision_id":"DEMO-001","viewer_id":"DEMO-V1","trigger":{"event":"app_open","received_at":now,"event_age_s":2},
             "goal":None,"action":"NO_ACTION","no_action_reason":"Synthetic smoke test only; real goal rules/data not loaded",
             "confidence":0.1,"confidence_reason":"No actual assignment data provided","assumptions":["This is a synthetic demo, not an assignment result"],
             "checks":{"passed":["demo_mode"],"failed":[]},"decided_in_ms":1,"status":"ABSTAINED"}]
    write_jsonl(out_dir / "decisions.jsonl", demo)
    write_jsonl(out_dir / "actions.jsonl", [])
    write_jsonl(out_dir / "outcomes.jsonl", [])
    return {"demo":True,"message":"Synthetic smoke test complete; not an evaluation result."}
