"""
THE WRITER AGENT

Third of three specialized agents (Reader -> Reasoner -> Writer).

Its ONLY job: take the Reasoner's verdict (contradiction found or not,
and what specifically) and turn it into the two things a human actually
needs — a proposed redline and an escalation memo. It does NOT re-judge
whether something is a contradiction; it trusts the Reasoner's verdict
and focuses purely on communicating it well.

FAKE_MODE: same pattern as the other two — when True, reuses our
existing redline_drafter.py logic instead of a real model call, so the
full three-agent chain can be tested offline. It is False by default —
the real AI path is the one that runs.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redline_drafter import draft_redline, draft_escalation_memo

FAKE_MODE = False  # Real AI is working now — this stays False.
# Only set to True temporarily if you need to test offline without an API call.

WRITER_SYSTEM_PROMPT = """You are the Writer — part of a compliance review team.

You will be given the Reasoner's verdict on whether a draft document
contradicts company policy. Your ONLY job is to communicate that
verdict clearly to a human, in two parts:

1. A PROPOSED REDLINE — suggested replacement wording that would fix
   the contradiction. Always frame this as a suggestion pending human
   approval. Never claim it has been applied.

2. AN ESCALATION MEMO — a short, plain-English memo to a Chief
   Compliance Officer explaining what was found and why it matters.
   Be direct and precise, like a sharp compliance lawyer, but never
   invent facts beyond what the Reasoner concluded.

If the Reasoner found no contradiction, simply state that clearly and
briefly — no memo or redline is needed.
"""


def write_output_fake(reasoner_output: dict, original_draft_text: str) -> dict:
    """
    Stand-in for the real Writer agent. Reuses our existing
    redline_drafter.py logic to produce the redline and memo.
    """
    if not reasoner_output.get("contradiction_found"):
        return {
            "needs_output": False,
            "message": "No contradiction found. No escalation needed.",
            "writing_method": "FAKE_MODE (template stand-in, not real AI writing yet)",
        }

    redline = draft_redline(reasoner_output, original_draft_text)
    memo = draft_escalation_memo(reasoner_output, redline)

    return {
        "needs_output": True,
        "redline": redline,
        "memo": memo,
        "writing_method": "FAKE_MODE (template stand-in, not real AI writing yet)",
    }


def write_output_real(reasoner_output: dict, original_draft_text: str) -> dict:
    """
    The real Writer — an actual Strands Agent that drafts the redline
    and memo using AI writing, not a fixed template. Runs on whichever
    provider model_provider.py is set to.
    """
    from strands import Agent
    from model_provider import get_model, provider_label

    model = get_model()
    # Streams its working to the terminal by design — see the note in
    # reader_agent.py. Don't add callback_handler=None to quieten it.
    writer = Agent(model=model, system_prompt=WRITER_SYSTEM_PROMPT)

    reasoning_text = reasoner_output.get("reasoning", str(reasoner_output))
    prompt = (
        f"REASONER'S VERDICT:\n{reasoning_text}\n\n"
        f"ORIGINAL DRAFT CLAUSE:\n{original_draft_text}\n\n"
        f"Write the proposed redline and escalation memo as instructed."
    )
    from model_provider import call_with_retry
    response = call_with_retry(writer, prompt)

    return {
        "needs_output": True,
        "output": str(response),
        # Named from the provider actually configured — see reader_agent.py.
        "writing_method": f"REAL (AI writing via {provider_label()})",
    }


def write_output(reasoner_output: dict, original_draft_text: str) -> dict:
    """Entry point — routes to fake or real Writer based on FAKE_MODE."""
    if FAKE_MODE:
        return write_output_fake(reasoner_output, original_draft_text)
    else:
        return write_output_real(reasoner_output, original_draft_text)


if __name__ == "__main__":
    from reader_agent import read_document
    from reasoner_agent import reason_about_contradiction

    script_dir = os.path.dirname(os.path.abspath(__file__))
    policy_file = os.path.join(script_dir, "corporate_bylaws.txt")
    draft_file = os.path.join(script_dir, "joint_venture_draft.txt")

    print("Step 1: Reader reads the policy document...")
    policy_output = read_document(policy_file)

    print("Step 2: Reader reads the draft document...")
    draft_output = read_document(draft_file)

    print("Step 3: Reasoner compares them...")
    reasoner_output = reason_about_contradiction(policy_output, draft_output)

    print("Step 4: Writer drafts the output...\n")
    writer_output = write_output(reasoner_output, draft_output["raw_text"])

    print("=== WRITER OUTPUT ===")
    print(f"Method: {writer_output['writing_method']}")
    if not writer_output["needs_output"]:
        print(writer_output.get("message", "No contradiction found. No escalation needed."))
    elif writer_output.get("output"):
        # The real AI path writes the redline and memo as one piece of prose.
        print(f"\n{writer_output['output']}")
    else:
        # FAKE_MODE returns the two as separate structured pieces. Read both
        # with .get() so a shape change prints a clear note instead of raising
        # a KeyError halfway through a demo.
        redline = writer_output.get("redline") or {}
        print(f"\nProposed redline: {redline.get('suggested_replacement', '(none returned)')}")
        print(f"Status: {redline.get('status', '(none returned)')}")
        print(f"\n{writer_output.get('memo', '(no memo returned)')}")
