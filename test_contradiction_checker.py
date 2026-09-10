"""
Automatic checks for the contradiction-checking logic.

Why this matters: the Scope 1/Scope 2 false-positive bug earlier only
got caught because I happened to run four documents by hand and read
the output closely. A test file like this catches that kind of mistake
every single time the code changes, automatically — which is what a
real product needs, since I won't always be reading every line of
output myself before you see it.

Run it with: python3 tests/test_contradiction_checker.py
It will print "ALL TESTS PASSED" or tell you exactly which check failed.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

from contradiction_checker import check_for_contradiction

POLICY = (
    "The Corporation formally pledges to achieve absolute Net-Zero emissions "
    "across all operations by 2035. This mandate strictly encompasses all "
    "direct operational footprints (Scope 1), purchased energy footprints "
    "(Scope 2), and all downstream supply-chain/product-use activities (Scope 3)."
)


def test_clean_document_is_not_flagged():
    clean_draft = (
        "This venture adopts the Corporation's full Net-Zero standard, "
        "covering Scope 1, Scope 2, and Scope 3 emissions across all project phases."
    )
    result = check_for_contradiction(POLICY, clean_draft)
    assert result["contradiction_found"] is False, "Clean document was wrongly flagged"
    assert result["dropped_scopes"] == [], f"Expected no dropped scopes, got {result['dropped_scopes']}"


def test_violating_document_is_flagged():
    bad_draft = (
        "Operational Net-Zero shall be defined exclusively as the mitigation "
        "of Scope 1 and Scope 2 emissions. Neither party shall bear financial "
        "or operational accountability for downstream Scope 3 product combustion emissions."
    )
    result = check_for_contradiction(POLICY, bad_draft)
    assert result["contradiction_found"] is True, "Violating document was not flagged"
    assert result["dropped_scopes"] == ["Scope 3"], f"Expected only Scope 3 dropped, got {result['dropped_scopes']}"


def test_reversed_order_violation_is_still_caught():
    # This is the exact phrasing that caused the earlier bug: the excluded
    # scope is named BEFORE the exclusion language, not after.
    bad_draft = (
        "Emissions reporting shall be limited to Scope 1 and Scope 2 sources only. "
        "Scope 3 downstream emissions shall not be subject to any reporting "
        "or accountability requirement under this venture."
    )
    result = check_for_contradiction(POLICY, bad_draft)
    assert result["contradiction_found"] is True, "Reversed-order exclusion was not caught"
    assert result["dropped_scopes"] == ["Scope 3"], (
        f"Expected only Scope 3 dropped, got {result['dropped_scopes']} "
        "— Scope 1/2 false positive bug may have returned"
    )


def test_scope1_and_scope2_are_not_falsely_blamed():
    # Guards specifically against the bug from earlier: a violation about
    # Scope 3 should never cause Scope 1 or Scope 2 to get flagged too.
    bad_draft = (
        "Emissions reporting shall be limited to Scope 1 and Scope 2 sources only. "
        "Scope 3 downstream emissions shall not be subject to any reporting "
        "or accountability requirement under this venture."
    )
    result = check_for_contradiction(POLICY, bad_draft)
    assert "Scope 1" not in result["dropped_scopes"], "Scope 1 falsely blamed"
    assert "Scope 2" not in result["dropped_scopes"], "Scope 2 falsely blamed"


def test_single_sentence_exclusion_does_not_blame_other_scopes_in_same_sentence():
    # Guards against a second version of the same underlying bug: this
    # time the false positive came from ONE sentence with multiple
    # comma-separated clauses, not multiple sentences. "shall exclude
    # Scope 3 ... limiting accountability to Scope 1 and Scope 2 only"
    # was wrongly flagging all three scopes before the clause-level fix.
    bad_draft = (
        "This venture shall exclude Scope 3 downstream emissions from all "
        "Net-Zero calculations, limiting accountability to Scope 1 and "
        "Scope 2 only."
    )
    result = check_for_contradiction(POLICY, bad_draft)
    assert result["contradiction_found"] is True, "Scope 3 exclusion was not caught"
    assert result["dropped_scopes"] == ["Scope 3"], (
        f"Expected only Scope 3 dropped, got {result['dropped_scopes']} "
        "— clause-crossing false positive may have returned"
    )


if __name__ == "__main__":
    tests = [
        test_clean_document_is_not_flagged,
        test_violating_document_is_flagged,
        test_reversed_order_violation_is_still_caught,
        test_scope1_and_scope2_are_not_falsely_blamed,
        test_single_sentence_exclusion_does_not_blame_other_scopes_in_same_sentence,
    ]

    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL: {test.__name__} — {e}")

    print()
    if failures == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"{failures} TEST(S) FAILED")
