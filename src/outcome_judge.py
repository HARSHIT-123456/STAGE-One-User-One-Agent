from .utils import parse_dt

def judge_goal(goal, events, now):
    if not goal:
        return {"status":"inconclusive","reason":"No goal assigned"}
    signal = str(goal.get("success_signal") or "").lower()
    start = parse_dt(goal.get("started_at"))
    deadline = parse_dt(goal.get("deadline"))
    if not signal:
        return {"status":"inconclusive","reason":"No measurable success signal configured"}
    matching = []
    for e in events:
        typ = str(e.get("event_type", e.get("event", ""))).lower()
        at = parse_dt(e.get("received_at"))
        if typ == signal and at and (start is None or at >= start) and (deadline is None or at <= deadline):
            matching.append(e)
    if matching:
        return {"status":"succeeded","reason":"Success signal observed inside goal window","evidence":[e.get("event_id") for e in matching]}
    if deadline and now > deadline:
        return {"status":"failed","reason":"Deadline passed without observed success signal"}
    return {"status":"inconclusive","reason":"Goal window remains open or signal not yet observed"}
