"""
THE REASONER AGENT

Second of three specialized agents (Reader -> Reasoner -> Writer).

Its ONLY job: take what the Reader already extracted from the policy
document AND the draft document, and decide whether they contradict.
It doesn't re-read raw documents itself (that's the Reader's job,
already done) and it doesn't write the final memo (that's the
Writer's job, next). It just judges.

Why this is worth separating from the Reader: judging "do these two
things actually conflict" is a different, harder kind of thinking than
"what does this document say." Keeping them separate means each agent
has one clear job instead of juggling both at once.

FAKE_MODE: same pattern as the Reader. When True, this runs on our
existing rule-based contradiction_checker.py logic instead of a real
model call, for testing offline. It is False by default — the real AI
path is the one that runs.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contradiction_checker import check_for_contradiction

FAKE_MODE = False  # Real AI is working now — this stays False.
# Only set to True temporarily if you need to test offline without an API call.

REASONER_SYSTEM_PROMPT = """You are the Reasoner — part of a compliance review team.

You will be given two things:
1. Facts extracted from a company's public policy document.
2. Facts extracted from a new draft document being reviewed.

Your ONLY job is to judge whether the draft document contradicts a
commitment made in the policy document. Specifically:
- Does the draft quietly drop, narrow, or redefine something the
  policy promises?
- If yes, state exactly what was dropped or changed, and quote the
  specific language from each document that shows the conflict.
- If no, say clearly that no contradiction was found.

SILENCE IS NOT A CONTRADICTION. Apply this rule strictly, because it is
the line between the two situations you must never confuse:
- The draft ACTIVELY narrows the promise — it excludes, carves out,
  waives, caps, redefines, or makes conditional something the policy
  covers ("excluding Scope 3", "shall not apply to", "only Scope 1 and
  2", "may monetize"). THAT IS A CONTRADICTION. Flag it.
- The draft is merely SILENT on a detail the policy states — it says
  nothing at all about a deadline, a figure, or a sub-clause, while
  adopting the policy standard it does mention. THAT IS NOT A
  CONTRADICTION, even though the omission may be worth a human noting.
  Not mentioning a deadline is not the same as denying it.

If a draft adopts a standard in full and simply doesn't restate every
detail of it, say no contradiction was found. Do not reason your way from
"the draft omits X" to "the draft therefore narrows X" — an omission and
a carve-out are different things, and treating them the same produces
inconsistent verdicts on identical wording.

Be precise and skeptical, like a sharp compliance lawyer. Do not flag
something as a contradiction unless the draft text actually supports
it — don't guess or assume bad intent that isn't in the text.
"""


def reason_about_contradiction_fake(policy_reader_output: dict, draft_reader_output: dict) -> dict:
    """
    Stand-in for the real Reasoner agent. Reuses our existing
    deterministic contradiction-checking logic, feeding it the raw
    text the Reader already extracted.
    """
    policy_text = policy_reader_output["raw_text"]
    draft_text = draft_reader_output["raw_text"]

    result = check_for_contradiction(policy_text, draft_text)
    result["reasoning_method"] = "FAKE_MODE (rule-based stand-in, not real AI reasoning yet)"
    return result


def reason_about_contradiction_real(policy_reader_output: dict, draft_reader_output: dict) -> dict:
    """
    The real Reasoner — an actual Strands Agent that judges whether the
    two documents conflict using AI reasoning. Runs on whichever provider
    model_provider.py is set to.
    """
    from strands import Agent
    from model_provider import get_model, provider_label

    model = get_model()
    # Streams its working to the terminal by design — see the note in
    # reader_agent.py. Don't add callback_handler=None to quieten it.
    reasoner = Agent(model=model, system_prompt=REASONER_SYSTEM_PROMPT)

    prompt = (
        f"POLICY DOCUMENT FACTS:\n{policy_reader_output.get('extraction', policy_reader_output.get('raw_text'))}\n\n"
        f"DRAFT DOCUMENT FACTS:\n{draft_reader_output.get('extraction', draft_reader_output.get('raw_text'))}\n\n"
        f"Does the draft contradict the policy? Explain clearly."
    )
    from model_provider import call_with_retry
    response = call_with_retry(reasoner, prompt)

    return {
        "contradiction_found": None,  # the real agent states this in plain language, not a bool yet
        "reasoning": str(response),
        # Named from the provider actually configured — see reader_agent.py.
        "reasoning_method": f"REAL (AI reasoning via {provider_label()})",
    }


def reason_about_contradiction(policy_reader_output: dict, draft_reader_output: dict) -> dict:
    """Entry point — routes to fake or real Reasoner based on FAKE_MODE."""
    if FAKE_MODE:
        return reason_about_contradiction_fake(policy_reader_output, draft_reader_output)
    else:
        return reason_about_contradiction_real(policy_reader_output, draft_reader_output)


if __name__ == "__main__":
    from reader_agent import read_document

    script_dir = os.path.dirname(os.path.abspath(__file__))
    policy_file = os.path.join(script_dir, "corporate_bylaws.txt")
    draft_file = os.path.join(script_dir, "joint_venture_draft.txt")

    print("Step 1: Reader reads the policy document...")
    policy_output = read_document(policy_file)

    print("Step 2: Reader reads the draft document...")
    draft_output = read_document(draft_file)

    print("Step 3: Reasoner compares them...\n")
    result = reason_about_contradiction(policy_output, draft_output)

    print("=== REASONER OUTPUT ===")
    print(f"Method: {result['reasoning_method']}")
    if "contradiction_found" in result and result["contradiction_found"] is not None:
        print(f"Contradiction found: {result['contradiction_found']}")
        print(f"Policy promises: {result['policy_promises']}")
        print(f"Draft covers: {result['draft_covers']}")
        print(f"Dropped: {result['dropped_scopes']}")
    if "reasoning" in result:
        print(f"Reasoning:\n{result['reasoning']}")
