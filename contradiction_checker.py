"""
This is the "brain" that spots contradictions.

It doesn't use AI to guess whether two documents disagree — it uses simple,
provable rules. That matters for the hackathon demo: a judge can see exactly
WHY it flagged something, instead of just trusting a black box.

How it works, in plain terms:
1. Read the company's public promise (the "rulebook" document).
2. Read the new document being checked (the "draft" document).
3. Pull out what each one says "Net-Zero" actually covers (Scope 1? 2? 3?).
4. Compare the two. If the draft covers LESS than the rulebook promises,
   that's a contradiction — flag it.
"""

import re
import os


def extract_scope_coverage(text: str) -> set[str]:
    """
    Looks at a chunk of text and figures out which emissions "scopes"
    (Scope 1, Scope 2, Scope 3) it says are included.

    This is deliberately simple pattern-matching, not an AI guess —
    that's what makes the result checkable and demoable.
    """
    covered = set()
    if re.search(r"scope\s*1", text, re.IGNORECASE):
        covered.add("Scope 1")
    if re.search(r"scope\s*2", text, re.IGNORECASE):
        covered.add("Scope 2")
    if re.search(r"scope\s*3", text, re.IGNORECASE):
        covered.add("Scope 3")
    return covered


def scope_is_excluded(text: str, scope: str) -> bool:
    """
    Checks whether the text explicitly says a scope is NOT included.

    Checks one CLAUSE at a time (splitting on commas and sentence
    endings), not the whole sentence or document at once. Two earlier
    bugs both came from the same root cause: a loose pattern reaching
    across an unrelated clause to falsely connect exclusion language
    to a scope it wasn't actually about — first across sentences, then
    across comma-separated clauses within one sentence. Clause-level
    checking closes both.
    """
    clauses = re.split(r"(?<=[.;,])\s+", text)

    exclusion_patterns = [
        rf"neither party shall bear.*{scope}",
        rf"excluding.*{scope}",
        rf"shall not.*{scope}",
        rf"shall exclude.*{scope}",
        rf"no.*accountability for.*{scope}",
        rf"{scope}.*shall not be subject to",
    ]

    for clause in clauses:
        if scope.lower() not in clause.lower():
            continue
        for pattern in exclusion_patterns:
            if re.search(pattern, clause, re.IGNORECASE):
                return True
    return False


def check_for_contradiction(policy_text: str, draft_text: str) -> dict:
    """
    Compares a company's public policy against a new draft document
    and reports any scopes that the policy promises but the draft drops.
    """
    policy_scopes = extract_scope_coverage(policy_text)
    draft_scopes = extract_scope_coverage(draft_text)

    dropped_scopes = policy_scopes - draft_scopes
    # Also catch cases where the scope word appears in the draft, but only
    # to explicitly say it's excluded (like the Scope 3 clause here).
    for scope in list(policy_scopes):
        if scope not in dropped_scopes and scope_is_excluded(draft_text, scope):
            dropped_scopes.add(scope)

    return {
        "policy_promises": sorted(policy_scopes),
        "draft_covers": sorted(draft_scopes - dropped_scopes),
        "dropped_scopes": sorted(dropped_scopes),
        "contradiction_found": len(dropped_scopes) > 0,
    }


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "corporate_bylaws.txt")) as f:
        policy = f.read()
    with open(os.path.join(script_dir, "joint_venture_draft.txt")) as f:
        draft = f.read()

    result = check_for_contradiction(policy, draft)

    print("=== CONTRADICTION CHECK RESULT ===")
    print(f"Public policy promises:  {result['policy_promises']}")
    print(f"New draft actually covers: {result['draft_covers']}")
    print(f"Scopes quietly dropped:   {result['dropped_scopes']}")
    print(f"CONTRADICTION FOUND: {result['contradiction_found']}")
