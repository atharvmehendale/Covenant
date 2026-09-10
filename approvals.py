"""
Stores the human's Approve / Reject decisions for flagged documents.

The whole safety principle of this project is that the agent never applies a
fix on its own — a human decides. This file is where that human decision gets
recorded (with a timestamp), so it survives closing and reopening the
dashboard.

Recording a decision here does NOT modify any contract. It only remembers
what the human chose. Nothing is ever auto-applied.
"""

import json
import os
from datetime import datetime, timezone


def load_approvals(path: str) -> dict:
    """Reads all recorded decisions. Returns {} if nothing's been decided yet."""
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_approvals(path: str, approvals: dict):
    with open(path, "w") as f:
        json.dump(approvals, f, indent=2)


def record_decision(path: str, document: str, decision: str) -> dict:
    """
    Records a human decision ("APPROVED" or "REJECTED") for one document,
    stamped with the time it was made. Returns the updated set of decisions.
    """
    approvals = load_approvals(path)
    approvals[document] = {
        "status": decision,
        "decided_by": "human (via dashboard)",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    save_approvals(path, approvals)
    return approvals
