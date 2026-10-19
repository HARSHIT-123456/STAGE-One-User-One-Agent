class MockModelProvider:
    """No-network model adapter. Rule-based output is the default and never treated as evidence."""
    def __init__(self, faults=None, max_calls=8):
        self.faults = faults or {}
        self.max_calls = max_calls
        self.calls = 0

    def propose(self, context):
        if self.calls >= self.max_calls:
            raise RuntimeError("model call budget exceeded")
        self.calls += 1
        if self.faults.get("timeout"):
            raise TimeoutError("injected mock model timeout")
        if self.faults.get("broken_json"):
            return "{not valid json"
        return {"action": "NO_ACTION", "reason": "Mock provider defers to deterministic planner"}

class ReplayFaultProvider:
    """Deterministic adapter for the assignment's replay/model_faults.jsonl file.

    It reproduces the scripted response shape without making network calls or sleeping. A timeout
    is represented as TimeoutError immediately so replay remains fast and deterministic; the agent
    records the fallback instead of trusting a model claim.
    """
    def __init__(self, faults_by_trigger=None):
        self.faults_by_trigger = faults_by_trigger or {}

    def propose(self, trigger_event_id):
        fault = self.faults_by_trigger.get(trigger_event_id)
        if not fault:
            return None
        kind = fault.get('fault')
        if kind == 'timeout':
            raise TimeoutError(f"injected replay timeout ({fault.get('seconds', 'unknown')}s)")
        if kind == 'malformed_output':
            return fault.get('model_output')
        if kind == 'unsupported_claim':
            return fault.get('model_output')
        return {'fault': kind, 'model_output': fault.get('model_output')}
