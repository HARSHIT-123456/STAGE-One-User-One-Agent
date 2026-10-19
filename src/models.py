from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class Fact:
    value: Any
    source: str
    observed_at: str | None = None
    received_at: str | None = None
    freshness: str = "unknown"

    def to_dict(self):
        return asdict(self)

@dataclass
class Decision:
    decision_id: str
    viewer_id: str
    trigger: dict
    goal: dict | None
    action: str
    dialect: dict
    content: list[str] = field(default_factory=list)
    confidence: float = 0.0
    confidence_reason: str = ""
    evidence: list[dict] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    checks: dict = field(default_factory=lambda: {"passed": [], "failed": []})
    decided_in_ms: int = 0
    deadline: str | None = None
    success_signal: str | None = None
    no_action_reason: str | None = None
    fallback_used: bool = False
    status: str = "PROPOSED"

    def to_dict(self):
        return asdict(self)
