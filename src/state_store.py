import json, sqlite3
from pathlib import Path

class StateStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS processed_events (event_id TEXT PRIMARY KEY, processed_at TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS viewer_state (viewer_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, updated_at TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS decisions (decision_id TEXT PRIMARY KEY, viewer_id TEXT NOT NULL, decision_json TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS actions (action_id TEXT PRIMARY KEY, viewer_id TEXT NOT NULL, action_json TEXT NOT NULL)")
        self.db.commit()

    def claim_event(self, event_id, processed_at):
        if not event_id:
            return True
        try:
            self.db.execute("INSERT INTO processed_events(event_id, processed_at) VALUES (?,?)", (str(event_id), processed_at))
            self.db.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_state(self, viewer_id):
        row = self.db.execute("SELECT state_json FROM viewer_state WHERE viewer_id=?", (str(viewer_id),)).fetchone()
        return json.loads(row[0]) if row else {}

    def put_state(self, viewer_id, state, updated_at):
        self.db.execute("INSERT INTO viewer_state(viewer_id,state_json,updated_at) VALUES (?,?,?) ON CONFLICT(viewer_id) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at",
                        (str(viewer_id), json.dumps(state), updated_at))
        self.db.commit()

    def save_decision(self, decision):
        d = decision if isinstance(decision, dict) else decision.to_dict()
        self.db.execute("INSERT OR REPLACE INTO decisions(decision_id,viewer_id,decision_json) VALUES (?,?,?)",
                        (d["decision_id"], str(d["viewer_id"]), json.dumps(d, default=str)))
        self.db.commit()

    def save_action(self, action):
        self.db.execute("INSERT OR IGNORE INTO actions(action_id,viewer_id,action_json) VALUES (?,?,?)",
                        (action["action_id"], str(action["viewer_id"]), json.dumps(action, default=str)))
        self.db.commit()

    def close(self):
        self.db.close()
