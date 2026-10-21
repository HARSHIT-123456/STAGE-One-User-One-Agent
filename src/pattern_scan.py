"""Three-pass, deterministic audit of input, decision, and action logs.

This is a transparent rule-based scanner, not an ML anomaly detector. It reports counts
and examples so a reviewer can see what the agent loaded, decided, verified, and published.
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
from .utils import read_jsonl


def _read_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def scan_run(pack_root, out_dir):
    root, out = Path(pack_root), Path(out_dir)
    decisions_path, actions_path = out / "decisions.jsonl", out / "actions.jsonl"
    decisions = read_jsonl(decisions_path) if decisions_path.exists() else []
    actions = read_jsonl(actions_path) if actions_path.exists() else []

    # Pass 1: loader/input integrity. Report missing files instead of silently implying a clean load.
    required = ["data/events.jsonl", "data/profiles_snapshot.csv", "data/catalogue.csv",
                "data/episodes.csv", "replay/arms.csv", "replay/triggers.jsonl",
                "replay/live_events.jsonl", "replay/control_events.jsonl", "config/goals.json"]
    missing_inputs = [name for name in required if not (root / name).is_file()]
    loaded = {name: ((root / name).stat().st_size if (root / name).is_file() else None) for name in required}

    # Pass 2: decision/model verification. Model output is only a proposal; a publish must have
    # passed the independent deterministic checks and may never be in the randomized holdout arm.
    status_counts = Counter(str(d.get("status", "MISSING")).upper() for d in decisions)
    action_counts = Counter(str(d.get("action", "MISSING")).upper() for d in decisions)
    failed_check_counts = Counter()
    expected_guardrail_counts = Counter()
    unexpected_verification_failures = Counter()
    missing_decision_fields = []
    model_faults = []
    model_claims_accepted = 0
    holdout_published = []
    for d in decisions:
        did = d.get("decision_id", "unknown")
        for field in ("decision_id", "user_id", "trigger", "action", "status", "checks"):
            if field not in d:
                missing_decision_fields.append({"decision_id": did, "field": field})
        checks = d.get("checks") or {}
        failed_check_counts.update(checks.get("failed", []))
        for check in checks.get("failed", []):
            if check == "holdout_zero_action":
                expected_guardrail_counts.update([check])
            else:
                unexpected_verification_failures.update([check])
        fault = d.get("model_fault")
        if fault:
            model_faults.append({"decision_id": did, "fault": fault.get("fault"),
                                 "handled_safely": fault.get("handled_safely"),
                                 "proposal_accepted_as_evidence": fault.get("proposal_accepted_as_evidence")})
            if fault.get("proposal_accepted_as_evidence") is True:
                model_claims_accepted += 1
        if str(d.get("action", "")).upper() != "NO_ACTION" and str(d.get("arm", "")).lower() == "holdout":
            holdout_published.append(did)

    action_ids = [a.get("action_id") for a in actions]
    duplicate_action_ids = sorted(k for k, n in Counter(action_ids).items() if k and n > 1)
    decision_ids = {d.get("decision_id") for d in decisions}
    orphan_actions = [a.get("action_id", "unknown") for a in actions if a.get("decision_id") not in decision_ids]
    published_decisions = sum(1 for d in decisions if str(d.get("action", "")).upper() != "NO_ACTION")

    # Pass 3: outcomes/zero-count interpretation. Zero is surfaced explicitly, never labelled
    # as an error without context (e.g. zero policy failures is expected; zero inputs is not).
    quality = _read_json(out / "simulator_quality_report.json")
    outcome_rows = read_jsonl(out / "outcomes.jsonl") if (out / "outcomes.jsonl").exists() else []
    zeros = {
        "zero_input_files_missing": len(missing_inputs) == 0,
        "zero_decisions": len(decisions) == 0,
        "zero_published_actions": len(actions) == 0,
        "zero_model_faults": len(model_faults) == 0,
        "zero_unexpected_verification_failures": sum(unexpected_verification_failures.values()) == 0,
        "zero_simulator_policy_problems": quality.get("policy_problem_count") == 0 if quality else None,
        "zero_outcome_rows": len(outcome_rows) == 0,
    }
    report = {
        "scanner": "three_pass_pattern_scan",
        "scanner_version": "1.0.0",
        "description": "Pass 1 checks input-loader files; Pass 2 inspects decision, model-fault and verifier logs; Pass 3 checks action/outcome counts and interprets zero counts.",
        "passes": {
            "1_input_loader": {"required_files": len(required), "missing_files": missing_inputs, "file_sizes_bytes": loaded},
            "2_agent_and_model_verification": {
                "decision_count": len(decisions), "status_counts": dict(status_counts),
                "action_counts": dict(action_counts), "verification_failure_counts": dict(failed_check_counts),
                "expected_guardrail_counts": dict(expected_guardrail_counts),
                "unexpected_verification_failure_counts": dict(unexpected_verification_failures),
                "missing_decision_fields": missing_decision_fields[:100], "model_fault_count": len(model_faults),
                "model_faults_sample": model_faults[:50], "model_claims_accepted_as_evidence": model_claims_accepted,
                "holdout_published_decision_ids": holdout_published, "published_decisions": published_decisions,
            },
            "3_outputs_and_zero_log_inspection": {
                "action_log_count": len(actions), "outcome_log_count": len(outcome_rows),
                "duplicate_action_ids": duplicate_action_ids, "orphan_actions": orphan_actions,
                "simulator_policy_problem_count": quality.get("policy_problem_count") if quality else None,
                "zero_checks": zeros,
            },
        },
        "findings": [],
    }
    findings = report["findings"]
    if missing_inputs: findings.append({"severity": "ERROR", "code": "INPUT_FILES_MISSING", "count": len(missing_inputs)})
    if not decisions: findings.append({"severity": "ERROR", "code": "NO_DECISIONS", "count": 0})
    if missing_decision_fields: findings.append({"severity": "WARNING", "code": "DECISION_FIELDS_MISSING", "count": len(missing_decision_fields)})
    if model_claims_accepted: findings.append({"severity": "ERROR", "code": "MODEL_CLAIM_USED_AS_EVIDENCE", "count": model_claims_accepted})
    if holdout_published: findings.append({"severity": "ERROR", "code": "HOLDOUT_ACTION_DETECTED", "count": len(holdout_published)})
    if duplicate_action_ids or orphan_actions: findings.append({"severity": "ERROR", "code": "ACTION_LOG_INTEGRITY", "count": len(duplicate_action_ids) + len(orphan_actions)})
    if quality and quality.get("policy_problem_count", 0): findings.append({"severity": "ERROR", "code": "SIMULATOR_POLICY_PROBLEMS", "count": quality.get("policy_problem_count")})
    if not findings: findings.append({"severity": "INFO", "code": "NO_AUDIT_FINDINGS", "count": 0})

    out.mkdir(parents=True, exist_ok=True)
    (out / "pattern_scan_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Three-Pass Pattern Scan", "", report["description"], "",
             "## Pass 1 — Input loader", f"- Required input files: {len(required)}", f"- Missing input files: {len(missing_inputs)}"]
    if missing_inputs: lines += [f"  - `{name}`" for name in missing_inputs]
    lines += ["", "## Pass 2 — Agent decisions, model and verifier logs",
              f"- Decisions inspected: {len(decisions)}", f"- Published actions referenced by decisions: {published_decisions}",
              f"- Model fault records: {len(model_faults)}", f"- Model claims accepted as evidence: {model_claims_accepted}",
              f"- Expected guardrail blocks (e.g. holdout): {sum(expected_guardrail_counts.values())}", f"- Unexpected verification failures: {sum(unexpected_verification_failures.values())}", f"- Holdout action violations: {len(holdout_published)}", "",
              "## Pass 3 — Output logs and zero-count inspection", f"- Action records: {len(actions)}", f"- Outcome records: {len(outcome_rows)}"]
    for key, value in zeros.items(): lines.append(f"- `{key}`: {value}")
    lines += ["", "## Findings"]
    lines += [f"- **{f['severity']}** `{f['code']}` — count: {f['count']}" for f in findings]
    lines += ["", "A zero count is a measurement, not automatically a failure: for example, zero simulator policy problems is desirable, while zero decisions may indicate a failed or empty replay.", ""]
    (out / "pattern_scan_report.md").write_text("\n".join(lines), encoding="utf-8")
    return report
