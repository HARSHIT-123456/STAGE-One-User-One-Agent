from pathlib import Path
import csv
from .utils import read_jsonl

def read_csv_rows(path):
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def deduplicate_events(events):
    # Keep the copy with the earliest trustworthy server received_at for stable replay ordering.
    # Duplicate payload conflicts are retained in duplicate audit metadata by the caller if desired.
    by_id = {}
    no_id = []
    for event in events:
        event_id = event.get("event_id")
        if not event_id:
            no_id.append(event)
            continue
        previous = by_id.get(str(event_id))
        if previous is None:
            by_id[str(event_id)] = event
        else:
            old_time = str(previous.get("received_at") or "9999")
            new_time = str(event.get("received_at") or "9999")
            if new_time < old_time:
                by_id[str(event_id)] = event
    result = list(by_id.values()) + no_id
    return sorted(result, key=lambda e: str(e.get("received_at") or ""))

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
