from pathlib import Path
import csv
import json
from .utils import read_jsonl

def read_csv_rows(path):
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def deduplicate_events(events):
    """Deduplicate IDs and exact copies while preserving distinct ID-less events.

    For a reused event_id, retain the row with the earliest server received_at
    timestamp. For rows without IDs, only identical serialized payloads are merged.
    """
    unique = {}
    for event in events:
        event_id = str(event.get("event_id") or "").strip()
        if event_id:
            key = ("event_id", event_id)
        else:
            fingerprint = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
            key = ("payload", fingerprint)
        previous = unique.get(key)
        if previous is None:
            unique[key] = event
            continue
        old_time = str(previous.get("received_at") or "9999")
        new_time = str(event.get("received_at") or "9999")
        if new_time < old_time:
            unique[key] = event
    return sorted(unique.values(), key=lambda event: (str(event.get("received_at") or ""), str(event.get("event_id") or "")))

def load_pack(data_dir, replay_dir=None):
    data_dir = Path(data_dir)
    replay_dir = Path(replay_dir) if replay_dir else None
    events = read_jsonl(data_dir / "events.jsonl")
    profiles = read_csv_rows(data_dir / "profiles_snapshot.csv")
    catalogue = read_csv_rows(data_dir / "catalogue.csv")
    episodes = read_csv_rows(data_dir / "episodes.csv")
    triggers = []
    if replay_dir:
        for name in ("triggers.jsonl", "events.jsonl", "trigger_events.jsonl"):
            candidate = replay_dir / name
            if candidate.exists():
                triggers = read_jsonl(candidate)
                break
    return {
        "events": deduplicate_events(events),
        "profiles": profiles,
        "catalogue": catalogue,
        "episodes": episodes,
        "triggers": deduplicate_events(triggers),
    }
