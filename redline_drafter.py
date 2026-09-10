"""
This is the piece that turns a detected contradiction into two things
a real compliance officer would actually want:

1. A PROPOSED redline — suggested replacement wording for the bad clause.
   By default this is just a suggestion, not something auto-applied.
   Whether it is auto-applied is controlled by the "auto_apply_redline"
   setting in config.json — NOT by a constant in this file. config.json
   is the single source of truth for that setting, so there is only ever
   one place to look.

2. An escalation memo — a short, plain-English message to the Chief
   Compliance Officer explaining what was found and why it matters.
"""

import json
import os


def auto_apply_enabled() -> bool:
    """
    Reads the "auto_apply_redline" setting from config.json, so that file is
    the single source of truth instead of a constant hardcoded here.

    Deliberately defensive and fail-safe: if config.json is missing,
    unreadable, or malformed, we return False. The safe default is always
    "propose, don't apply" — a config problem must never cause the agent to
    start acting on its own.

    Read fresh on each call (rather than cached at import) so editing
    config.json takes effect on the next scan without restarting.
    """
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(config_path) as f:
            return bool(json.load(f).get("auto_apply_redline", False))
    except (OSError, ValueError):
        return False


def draft_redline(check_result: dict, original_clause: str) -> dict:
    """
    Builds a suggested replacement for a clause that dropped a scope
    the public policy promised.
    """
    dropped = check_result["dropped_scopes"]
    if not dropped:
        return {"needs_redline": False}

    dropped_list = " and ".join(dropped)
    suggested_text = (
        f"must fully account for and mitigate {', '.join(check_result['policy_promises'])} "
        f"to remain fully aligned with the Corporation's public Code of Conduct."
    )

    return {
        "needs_redline": True,
        "original_clause": original_clause,
        "problem": f"This clause omits {dropped_list}, which the public policy requires.",
        "suggested_replacement": suggested_text,
        "status": "AUTO_APPLIED" if auto_apply_enabled() else "PENDING_HUMAN_APPROVAL",
    }


def draft_escalation_memo(check_result: dict, redline: dict) -> str:
    """
    Writes a short memo a compliance officer could actually read and act on.
    """
    if not check_result["contradiction_found"]:
        return "No contradiction found. No escalation needed."

    dropped = ", ".join(check_result["dropped_scopes"])

    memo = f"""Subject: Compliance Alert — Policy Contradiction Detected

A new document was reviewed against the Corporation's public sustainability policy.

WHAT WAS FOUND:
The draft redefines "Net-Zero" in a way that drops {dropped}, which the public
policy explicitly requires.

WHY IT MATTERS:
Signing this as written creates a gap between what the company has publicly
promised and what this agreement actually commits to — a real risk if it
becomes public.

SUGGESTED FIX (pending your approval — nothing has been changed yet):
"{redline['suggested_replacement']}"

Status: {redline['status']}
"""
    return memo


if __name__ == "__main__":
    from contradiction_checker import check_for_contradiction

    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "corporate_bylaws.txt")) as f:
        policy = f.read()
    with open(os.path.join(script_dir, "joint_venture_draft.txt")) as f:
        draft = f.read()

    check_result = check_for_contradiction(policy, draft)
    redline = draft_redline(check_result, draft)
    memo = draft_escalation_memo(check_result, redline)

    print("=== PROPOSED REDLINE ===")
    print(f"Problem: {redline['problem']}")
    print(f"Suggested replacement: {redline['suggested_replacement']}")
    print(f"Status: {redline['status']}")
    print()
    print("=== ESCALATION MEMO ===")
    print(memo)
