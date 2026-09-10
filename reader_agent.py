"""
THE READER AGENT

This is the first of three specialized agents (Reader, Reasoner, Writer).

Its ONLY job: read a document and extract the relevant facts in a
structured way. It does NOT decide whether something is a contradiction
— that's the Reasoner's job, later. Keeping it this narrow is the whole
point of splitting into multiple agents: a Reader that only reads is
simpler and more reliable than one AI trying to do everything at once.

FAKE_MODE note: when True, this runs on a stand-in extraction function
instead of a real model call, so the pipeline can be tested offline
without spending an API call. It is False by default — the real AI path
is the one that runs. Nothing else in this file changes either way.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contradiction_checker import extract_scope_coverage
from document_intake import load_text

FAKE_MODE = False  # Real AI is working now — this stays False.
# Only set to True temporarily if you need to test offline without an API call.

READER_SYSTEM_PROMPT = """You are the Reader — part of a compliance review team.

Your ONLY job is to read a document and extract the relevant factual
claims from it in a clear, structured way. Specifically:
- What commitments or obligations does this document state?
- What specific terms does it define, and how?
- Quote the exact relevant language where it matters.

Do NOT judge whether anything is a contradiction, risk, or problem —
that is someone else's job. You only extract and report facts, plainly
and accurately. Never invent facts that aren't in the document.
"""


def read_document_fake(file_path: str) -> dict:
    """
    Stand-in for the real Reader agent. Uses our existing deterministic
    scope-extraction logic to produce a structured result in the same
    shape the real AI Reader will eventually produce.
    """
    text = load_text(file_path)

    scopes_mentioned = extract_scope_coverage(text)

    return {
        "source_file": file_path,
        "raw_text": text,
        "scopes_mentioned": sorted(scopes_mentioned),
        "extraction_method": "FAKE_MODE (rule-based stand-in, not real AI reasoning yet)",
    }


def read_document_real(file_path: str) -> dict:
    """
    The real Reader — an actual Strands Agent that reads the document
    and extracts facts using AI reasoning, not just keyword rules.
    Runs on whichever provider model_provider.py is set to.
    """
    from strands import Agent
    from model_provider import get_model, provider_label

    text = load_text(file_path)

    model = get_model()
    # No callback_handler=None here, on purpose: this agent streams its working
    # to the terminal. The Orchestrator's copy of the Reader is silenced instead,
    # because there it is one tool call inside a larger run. Run directly, or via
    # the paced fixed-order path, the visible working is the point — a minute of
    # printed reasoning reads as a system thinking, a blank terminal reads as a
    # system hung. See _fall_back_to_sequential in orchestrator.py.
    reader = Agent(model=model, system_prompt=READER_SYSTEM_PROMPT)
    from model_provider import call_with_retry
    response = call_with_retry(reader, f"Extract the relevant facts from this document:\n\n{text}")

    return {
        "source_file": file_path,
        "raw_text": text,
        "extraction": str(response),
        # Named from the provider actually configured, not hardcoded. This
        # string used to say "via Bedrock" long after the provider moved to
        # Groq, which put a false claim on screen and in the scan log.
        "extraction_method": f"REAL (AI reasoning via {provider_label()})",
    }


def read_document(file_path: str) -> dict:
    """
    Entry point — routes to fake or real Reader based on FAKE_MODE.

    The file itself can be a PDF, a Word document or plain text: the actual
    reading is done by document_intake.load_text(), which is the one place in
    the project that knows how to get words out of a file. That is why a PDF
    dropped into the watched inbox is reviewed properly instead of being read as
    binary noise. If the document can't be read at all — a scanned contract with
    no text layer, say — load_text raises UnreadableDocument with an explanation,
    rather than handing the agents an empty string to review.
    """
    if FAKE_MODE:
        return read_document_fake(file_path)
    else:
        return read_document_real(file_path)


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    test_file = os.path.join(script_dir, "corporate_bylaws.txt")

    result = read_document(test_file)

    print("=== READER OUTPUT ===")
    print(f"Source: {result['source_file']}")
    print(f"Method: {result['extraction_method']}")
    if "scopes_mentioned" in result:
        print(f"Scopes mentioned: {result['scopes_mentioned']}")
    if "extraction" in result:
        print(f"Extraction:\n{result['extraction']}")
