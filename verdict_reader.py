"""
READING THE REASONER'S VERDICT

The real Reasoner agent states its judgment in plain language, the way a lawyer
would — "the draft narrows the commitment by excluding Scope 3" — not as a
machine-readable flag. Something has to turn that prose into a reliable
flagged/clear decision, because the log, the dashboard status and the
Approve/Reject flow all need a definite answer.

That is this module's only job. It lives on its own so there is exactly ONE
definition of how a verdict is read, shared by every caller: the fixed-order
review path in orchestrator.py and the real-document verification test. Two
copies of this logic drifting apart would mean the same reasoning could be
graded differently depending on which route a document took.

Note what is deliberately NOT here: subject vocabulary. None of the phrases
below mention emissions, privacy, or any other topic. They describe the SHAPE of
a verdict — "does not contradict", "the draft permits" — which is why the same
reader works on a climate commitment and a data-privacy commitment without
being changed.

The full reasoning text is always kept and shown to the human alongside the
verdict, so this reading is never the last word.
"""

import re

# Words that flip the meaning of a clearance phrase. "the draft is not
# consistent with the policy" contains the clearance phrase "consistent with
# the", so without this check a negated sentence would be read as a pass.
NEGATION_NEAR = re.compile(r"\b(?:not|never|nor|cannot|n't|fails? to|failed to)\b")


def _states_plainly(text: str, phrase: str) -> bool:
    """
    True if `phrase` appears in `text` as whole words AND is not negated by
    something in the 20 characters just before it.

    Whole words matter: "inconsistent" contains "consistent", and reading that
    as a clearance would clear a document the agent was actually criticising.
    """
    for match in re.finditer(r"\b" + re.escape(phrase) + r"\b", text):
        window = text[max(0, match.start() - 20):match.start()]
        if not NEGATION_NEAR.search(window):
            return True
    return False


def looks_like_contradiction(reasoning: str):
    """
    Reads the Reasoner's prose and returns True (flagged), False (clear), or
    None (unclear — treated as "not proven", never as a pass).

    Clearance phrases are checked FIRST, because a clean verdict often still
    contains the word "contradict" inside a negated sentence -- e.g. "no
    language in the draft narrows, contradicts, or omits ..." -- which a naive
    keyword scan would misread as a contradiction.
    """
    text = (reasoning or "").lower()

    clear_signals = (
        "no contradiction", "does not contradict", "do not contradict",
        "no conflict", "does not conflict", "fully consistent",
        "is consistent with", "are consistent with", "consistent with the",
        "aligns with", "no language in the draft", "does not narrow",
        "no issue", "no violation",
        "nothing in the draft", "nothing in this draft",
        # Same idea, wording a reviewer is just as likely to use:
        "honors the", "honours the", "upholds the", "mirrors the policy",
        "matches the policy", "does not weaken", "does not permit",
        "no narrowing", "does not expand",
    )
    for signal in clear_signals:
        if _states_plainly(text, signal):
            return False

    flag_signals = (
        "contradicts the", "is a contradiction", "does contradict",
        "conflicts with", "therefore conflicts", "the draft drops",
        "the draft narrows", "the draft excludes", "the draft omits",
        "quietly drops", "yes - the draft", "yes, the draft", "yes – the draft",
        "constitutes a contradiction", "narrows the scope",
        # Ways a reviewer describes a promise being given away, in any subject:
        "the draft permits", "the draft authorizes", "the draft authorises",
        "the draft weakens", "the draft expands", "walks back",
        "broader than the policy", "beyond what the policy",
        "directly contradicts",
        # Negated clearances. Safe to treat as flags here because every
        # clearance phrase above was already checked, negation-aware.
        "inconsistent with", "not consistent with", "does not align",
        "not aligned with",
    )
    for signal in flag_signals:
        if signal in text:
            return True

    # Fallback: a bare mention, only reached if no clearance phrase matched.
    if "contradict" in text or "conflict" in text:
        return True
    return None
