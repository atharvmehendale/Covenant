"""
THE ORCHESTRATOR

This is what turns three separate agent files into one actual
multi-agent SYSTEM.

Two ways this runs:

FAKE_MODE (True) — calls the three agents one after another in a fixed
order, same as reader_agent.py -> reasoner_agent.py -> writer_agent.py
did individually. Good for testing the plumbing offline, without a real
API call.

Real mode (False) — this is the more impressive version for the demo.
Instead of ME deciding the order (read, then reason, then write), the
Reader, Reasoner, and Writer become TOOLS that a fourth agent — the
Orchestrator — is handed. The Orchestrator gets one instruction
("review this draft against this policy") and DECIDES on its own to
call the Reader, then the Reasoner, then the Writer, in that order,
because that's the logical sequence — not because I hardcoded it.
That's the actual definition of a multi-agent system, not just three
scripts run back to back.

There is also run_pipeline_sequential() at the bottom of this file: the
same three REAL agents, called one at a time in a fixed order with a
pause between calls. It exists because the Orchestrator packs both
documents and every tool result into one large final call, which
overruns a free API tier on a realistically-sized contract. The
sequential path spreads the same work over several smaller calls, so a
long document still gets a genuine review. It is a different pacing
strategy, not a different or weaker analysis — same agents, same
prompts, same verdict reader.

Any format the intake layer can read works through either path: a PDF or
a Word document is turned into text by document_intake, so the agents
themselves never need to know what kind of file it came from.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from document_intake import load_text

FAKE_MODE = False  # Real AI is working — this stays False.
# Only set to True temporarily if you need to test offline without an API call.

# The Orchestrator's report is not a summary for a log file — it IS the case
# file. monitor.py takes this response and writes it to the scan log as the
# case's "analysis", and the dashboard shows that text and nothing else. The
# Reader's, Reasoner's and Writer's own answers reach the tool layer and stop
# there.
#
# That is why the reporting rules below are so blunt about reproducing the
# Writer's work in full. Asked only to "report the final result clearly and
# concisely", the Orchestrator did exactly that — it wrote a tidy paragraph
# ending "the Writer supplied a redline expanding the definition to include
# Scope 3 and an escalation memo", and the redline itself went nowhere. A
# compliance officer opening that case was told a redline existed and given no
# way to read it. The pending-approval wording is stated here for the same
# reason: this path's output is human-facing, so the never-applied rule has to
# be carried in the words the human actually reads.
ORCHESTRATOR_SYSTEM_PROMPT = """You are the lead compliance agent, managing a
small team: a Reader, a Reasoner, and a Writer.

Given a policy document and a draft document to review, your job is to:
1. Have the Reader extract facts from both documents.
2. Have the Reasoner judge whether the draft contradicts the policy.
3. If a contradiction is found, have the Writer produce a proposed
   redline and an escalation memo.
4. If no contradiction is found, simply report that clearly — do not
   call the Writer unnecessarily.

Use your team members in the right order.

HOW TO REPORT. Your report is the only thing the human reviewer sees. It is
written straight into the compliance case file, and your team members' own
answers are NOT shown next to it. So:

- If a contradiction was found, first state what the Reasoner concluded and
  quote the conflicting language from each document. Then reproduce the
  Writer's proposed redline and escalation memo IN FULL, as the Writer wrote
  them. Do not summarise them, and never write that a redline "has been
  prepared" or "has been supplied" in place of showing it — a reviewer told
  that a redline exists but unable to read it has been given nothing to act on.
- Introduce the Writer's work with exactly this line:
  **Writer's proposed redline and escalation memo — PENDING HUMAN APPROVAL, nothing has been applied:**
  That opening word matters and is not decoration: the dashboard hunts for the
  proposed wording with a pattern anchored to lines that START with "Proposed"
  or "Suggested", so a label beginning with the adjective gets mistaken for the
  redline itself and the reviewer is shown this heading where the clause should
  be. Beginning with "Writer's" is what makes the label skippable. Never state
  or imply that any document has been changed. Nothing is ever applied
  automatically; a human decides.
- If no contradiction was found, say so briefly and stop there.

IMPORTANT: After your report, end your entire response with a single
final line in EXACTLY one of these two formats, and write nothing after it:
VERDICT: CONTRADICTION
VERDICT: NO_CONTRADICTION
Use CONTRADICTION only if the draft actually conflicts with the policy.
"""


def run_pipeline_fake(policy_path: str, draft_path: str) -> dict:
    """Fixed-order fake pipeline — Reader, then Reasoner, then Writer, no real AI decision-making."""
    from reader_agent import read_document
    from reasoner_agent import reason_about_contradiction
    from writer_agent import write_output

    policy_output = read_document(policy_path)
    draft_output = read_document(draft_path)
    reasoner_output = reason_about_contradiction(policy_output, draft_output)
    writer_output = write_output(reasoner_output, draft_output["raw_text"])

    return {
        "contradiction_found": reasoner_output.get("contradiction_found"),
        "writer_output": writer_output,
        "mode": "FAKE_MODE",
    }


def run_pipeline_real(policy_path: str, draft_path: str) -> dict:
    """
    The real multi-agent system — Reader, Reasoner, and Writer are each
    wrapped as a tool, and a top-level Orchestrator agent decides how
    to use them. Runs on whichever provider model_provider.py is set to.
    """
    from strands import Agent, tool
    from model_provider import get_model

    model = get_model()

    from reader_agent import READER_SYSTEM_PROMPT
    from reasoner_agent import REASONER_SYSTEM_PROMPT
    from writer_agent import WRITER_SYSTEM_PROMPT

    @tool
    def reader_tool(document_text: str) -> str:
        """Reads a document and extracts the relevant facts and commitments from it."""
        from model_provider import call_with_retry
        reader = Agent(model=model, system_prompt=READER_SYSTEM_PROMPT, callback_handler=None)
        return str(call_with_retry(reader, f"Extract the relevant facts from this document:\n\n{document_text}"))

    @tool
    def reasoner_tool(policy_facts: str, draft_facts: str) -> str:
        """Judges whether the draft document's facts contradict the policy document's facts."""
        from model_provider import call_with_retry
        reasoner = Agent(model=model, system_prompt=REASONER_SYSTEM_PROMPT, callback_handler=None)
        prompt = f"POLICY FACTS:\n{policy_facts}\n\nDRAFT FACTS:\n{draft_facts}\n\nDoes the draft contradict the policy?"
        return str(call_with_retry(reasoner, prompt))

    @tool
    def writer_tool(reasoner_verdict: str, original_draft_text: str) -> str:
        """Writes a proposed redline and escalation memo based on the Reasoner's verdict."""
        from model_provider import call_with_retry
        writer = Agent(model=model, system_prompt=WRITER_SYSTEM_PROMPT, callback_handler=None)
        prompt = f"REASONER'S VERDICT:\n{reasoner_verdict}\n\nORIGINAL DRAFT CLAUSE:\n{original_draft_text}\n\nWrite the proposed redline and escalation memo."
        return str(call_with_retry(writer, prompt))

    policy_text = load_text(policy_path)
    draft_text = load_text(draft_path)

    orchestrator = Agent(
        model=model,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=[reader_tool, reasoner_tool, writer_tool],
        callback_handler=None,
    )

    prompt = (
        f"POLICY DOCUMENT:\n{policy_text}\n\n"
        f"DRAFT DOCUMENT TO REVIEW:\n{draft_text}\n\n"
        f"Review the draft against the policy using your team."
    )
    from model_provider import call_with_retry
    response = call_with_retry(orchestrator, prompt)

    # The Orchestrator ends its answer with a machine-readable verdict line
    # (see the system prompt). We parse it into a reliable True/False so the
    # monitor and dashboard can tell "flagged" from "clear" without guessing
    # from prose. If the line is ever missing, we fall back to the
    # deterministic checker so this is never left as None.
    full_text = str(response)
    contradiction_found = None
    for line in full_text.splitlines():
        stripped = line.strip().upper()
        if stripped.startswith("VERDICT:"):
            value = stripped.split(":", 1)[1].strip()
            if "NO_CONTRADICTION" in value or "NO CONTRADICTION" in value:
                contradiction_found = False
            elif "CONTRADICTION" in value:
                contradiction_found = True

    if contradiction_found is None:
        from contradiction_checker import check_for_contradiction
        contradiction_found = check_for_contradiction(policy_text, draft_text)["contradiction_found"]

    # Hide the machine-readable VERDICT line from the human-facing output.
    display_output = "\n".join(
        line for line in full_text.splitlines()
        if not line.strip().upper().startswith("VERDICT:")
    ).strip()

    return {
        "contradiction_found": contradiction_found,
        "final_output": display_output,
        "mode": "REAL",
    }


def _fall_back_to_sequential(policy_path: str, draft_path: str, reason: str) -> dict:
    """
    Re-runs the review the paced way, after the Orchestrator hit a provider limit.

    Says so out loud, and records it in the returned `mode`, because a review
    that quietly changed how it ran is a review nobody can account for later.

    A note on the noise that follows. This path lets each agent stream its
    working to the terminal — the Reader's extracted tables, the Reasoner's
    comparison, the Writer's drafting — because the three agents build their
    Agent() without callback_handler=None, unlike the Orchestrator's tool
    wrappers above, which silence theirs. That asymmetry is deliberate and
    should stay: the fallback re-runs the same work in four paced calls and
    takes a minute or more, and a terminal printing the model's actual
    reasoning reads as a system working, where a silent one reads as a system
    hung. Anyone tempted to quieten this for tidiness should know they are
    trading a visibly-working minute for a frozen-looking one.
    """
    print(
        f"\n  (The Orchestrator could not finish: {reason}.\n"
        f"   Re-running the same Reader, Reasoner and Writer in a fixed order,\n"
        f"   with pauses between calls, so the same work fits into smaller\n"
        f"   requests. This changes the pacing, not the analysis.\n"
        f"   Each agent's working is printed below as it goes; the finished\n"
        f"   verdict and any proposed redline follow at the end.)\n"
    )
    result = run_pipeline_sequential(policy_path, draft_path)
    result["mode"] = "REAL (fixed-order — Orchestrator hit provider limits)"
    return result


def run_pipeline(policy_path: str, draft_path: str) -> dict:
    """
    Entry point used by monitor.py — routes to fake or real pipeline based on FAKE_MODE.

    The real path is the full Orchestrator, and it falls back to the paced
    fixed-order path when the provider refuses the work rather than the work
    being wrong. There are exactly two such cases, and both are properties of
    how the Orchestrator packs its requests, not of the document:

      - the document is too big to fit one request, because the Orchestrator
        re-sends both documents as tool arguments and then piles every tool
        result into one final call;
      - the free tier's per-minute token allowance ran out mid-review, after
        call_with_retry had already waited and retried.

    Both are precisely what run_pipeline_sequential was built for, so the honest
    response is to run it rather than to give up. This matters because the
    background watcher calls straight into here with nothing catching anything:
    before this, a single realistically-sized PDF in the inbox ended the watcher
    with a traceback, having reviewed nothing — the one outcome the whole intake
    layer exists to prevent.

    Anything else still raises. A fallback that swallowed every error would turn
    a broken review into a silently clean-looking one.
    """
    if FAKE_MODE:
        return run_pipeline_fake(policy_path, draft_path)

    from model_provider import DocumentTooLargeForModel, is_rate_limit_error

    try:
        return run_pipeline_real(policy_path, draft_path)
    except DocumentTooLargeForModel:
        return _fall_back_to_sequential(
            policy_path, draft_path,
            "this document is too large to review in a single request",
        )
    except Exception as e:
        if not is_rate_limit_error(e):
            raise
        return _fall_back_to_sequential(
            policy_path, draft_path,
            "the provider's per-minute token allowance ran out",
        )


# How long to wait between agent calls on the sequential path. Free API tiers
# meter tokens per MINUTE, so spacing the calls out is what keeps a long document
# inside the allowance. call_with_retry() still covers the case where we hit the
# limit anyway.
SEQUENTIAL_PACE_SECONDS = 20


def run_pipeline_sequential(policy_path: str, draft_path: str, pace: int = None,
                            on_progress=None) -> dict:
    """
    The same three real agents, called in a fixed order with a pause between
    calls — and the same result shape as run_pipeline(), so every caller,
    logger and dashboard treats it identically.

    Why this exists: the full Orchestrator re-sends both documents as tool
    arguments and then piles every tool result into one final call, which runs
    to several thousand tokens on a realistic contract and overruns a free
    tier's per-minute allowance. Splitting the same work into four smaller,
    spaced-out calls fits comfortably. The analysis is not reduced — it is the
    identical Reader, Reasoner and Writer, with the identical prompts. What is
    lost is only the part where the Orchestrator agent chooses the order for
    itself; here the order is fixed, because for this job the order was never
    in doubt.

    The Writer is skipped entirely when the Reasoner finds nothing wrong, which
    is the same "stay silent on a clean document" rule the rest of the system
    follows.

    `on_progress` is an optional callback taking one short status string, so a
    UI can show what the team is doing during a review that takes a minute.
    """
    import time

    from reader_agent import read_document
    from reasoner_agent import reason_about_contradiction
    from writer_agent import write_output
    from verdict_reader import looks_like_contradiction

    if pace is None:
        pace = SEQUENTIAL_PACE_SECONDS

    def say(message: str):
        if on_progress:
            on_progress(message)

    say("Reader is reading the public commitment...")
    policy_output = read_document(policy_path)
    time.sleep(pace)

    say("Reader is reading the document under review...")
    draft_output = read_document(draft_path)
    time.sleep(pace)

    say("Reasoner is judging whether the draft narrows the commitment...")
    reasoner_output = reason_about_contradiction(policy_output, draft_output)
    reasoning = reasoner_output.get("reasoning", "")

    # The real Reasoner answers in plain language, so its verdict is read by the
    # shared verdict reader — the exact same rules the real-document
    # verification test uses.
    contradiction_found = looks_like_contradiction(reasoning)

    parts = []
    if reasoning:
        parts.append("**Conclusion (Reasoner, real AI):**")
        parts.append(reasoning.strip())

    if contradiction_found:
        time.sleep(pace)
        say("Writer is drafting the proposed redline and escalation memo...")
        writer_output = write_output(reasoner_output, draft_output["raw_text"])
        memo = writer_output.get("output") or writer_output.get("memo") or ""
        if memo:
            parts.append(
                "**Writer's proposed redline and escalation memo (real AI) — "
                "PENDING HUMAN APPROVAL, nothing has been applied:**"
            )
            parts.append(memo.strip())

    return {
        "contradiction_found": contradiction_found,
        "final_output": "\n\n".join(parts),
        "mode": "REAL (fixed-order)",
    }


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    policy_file = os.path.join(script_dir, "corporate_bylaws.txt")
    draft_file = os.path.join(script_dir, "joint_venture_draft.txt")

    result = run_pipeline(policy_file, draft_file)

    print("=== ORCHESTRATOR RESULT ===")
    print(f"Mode: {result['mode']}")
    print(f"Contradiction found: {result['contradiction_found']}")
    if "writer_output" in result:
        wo = result["writer_output"]
        if not wo["needs_output"]:
            print(wo.get("message", "No contradiction found. No escalation needed."))
        else:
            # Read both shapes. The real Writer returns its redline and memo as
            # one piece of prose under "output"; FAKE_MODE returns a separate
            # "memo". This block used to read wo['memo'] outright, which is a
            # KeyError waiting to happen precisely because the two FAKE_MODE
            # switches are independent: setting orchestrator.FAKE_MODE = True
            # for an offline run while writer_agent.FAKE_MODE stays False (the
            # normal state here) sends the real Writer's dict into this line.
            print(f"\n{wo.get('output') or wo.get('memo') or '(no memo returned)'}")
    if "final_output" in result:
        print(f"\n{result['final_output']}")
