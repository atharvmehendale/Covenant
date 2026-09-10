"""
REAL-DOCUMENT TESTS  (ad-hoc, run by hand)

This is NOT part of the background system. It is a set of one-off checks that
run the REAL AI agents against REAL, publicly published corporate commitments
instead of the hand-written sample policy. The point is to prove the AI
reasoning holds up on genuine, real-world corporate language -- and that it is
not quietly tuned to one subject. Two SUITES, in two unrelated domains, run
through exactly the same agents, with the same prompts and no code changes:

  emissions : a published "carbon negative by 2030" climate commitment,
              reproduced under the fictional name "Meridian Industries"
              (real_policy_meridian.txt).
  privacy   : a published data-privacy commitment about never selling,
              renting or monetizing personal data, reproduced under the
              fictional name "Quillhaven Communications"
              (real_policy_quillhaven.txt).

In each suite the policy file holds the verbatim commitment language with the
real company's name replaced (see the source note inside each one), and the two
draft files are HYPOTHETICAL / synthetic contract clauses, clearly labeled as
such inside each file. They are fabricated; they exist only so we can check two
opposite behaviours:

      NARROWING draft -> the agent SHOULD flag it (it quietly gives away
                         something the public commitment promised).
      CLEAN draft     -> the agent SHOULD stay silent (it honors the promise).

WHY THIS USES THE FIXED-ORDER PATH (not the full orchestrator):
The full multi-agent Orchestrator (orchestrator.run_pipeline_real) re-sends
each document as a tool argument and piles every tool result into one large
final call -- roughly 7,000+ tokens. Groq's FREE tier caps at 8,000 tokens
per minute, so a single real-document orchestrator run trips the rate limit.
This test instead calls the exact same REAL Reader, Reasoner, and Writer
agents directly, in fixed order, as four small independent calls (paced a
few seconds apart). Same real AI, same prompts -- just light enough to fit
the free tier. On Amazon Bedrock or a paid tier, the full orchestrator
handles a document this size directly. No FAKE_MODE flag is changed here;
all three agents remain real (their FAKE_MODE stays False).

This script prints its results to the screen AND records each case in
scan_log.jsonl, using the very same log_result() helper monitor.py uses, so the
dashboard shows these runs as real cases alongside everything else. Two
deliberate limits on that:

  - Each entry carries its own case title, naming both its company and its
    subject -- e.g. "Matter: Quillhaven Communications -- Data Privacy
    Commitment Verification (Narrowing Case)" -- so it can never be mistaken
    for one of the sample inbox matters or for a live compliance review.
  - It still never touches approvals.json, never edits a contract, and never
    rewrites or removes anything already in the log. The sample inbox cases are
    left exactly as they were, decisions and all.

Run it with:
    python run_real_document_test.py                    (every case)
    python run_real_document_test.py privacy            (both privacy cases)
    python run_real_document_test.py emissions          (both emissions cases)
    python run_real_document_test.py privacy narrowing  (one specific case)
    python run_real_document_test.py narrowing          (the flag-it case in
                                                         every suite)
On the free tier, running one suite -- or one case -- at a time is the most
reliable, since the whole per-minute token budget goes to that case.
"""

import os
import re
import sys
import time

# Match the project's Windows-safe output handling: force UTF-8 so any
# non-ASCII the model emits (e.g. a non-breaking hyphen in "Net-Zero")
# prints instead of crashing the run on a cp1252 console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reader_agent import read_document
from reasoner_agent import reason_about_contradiction
from writer_agent import write_output
from config import load_config
from monitor import log_result  # the exact same log writer the watcher uses

ROOT = os.path.dirname(os.path.abspath(__file__))

# Seconds to wait between agent calls, so four calls don't stack inside a
# single 60-second free-tier token window.
PACE = 20

# --------------------------------------------------------------------------
# THE SUITES
#
# Same agents, same prompts, two unrelated subjects. The only thing that
# differs between suites is which documents get read. That is the entire
# point of having a second suite: it shows the reasoning is not tuned to
# emissions vocabulary.
# --------------------------------------------------------------------------

SUITES = [
    {
        "key": "emissions",
        "company": "Meridian Industries",
        "subject": "a published 'carbon negative by 2030' climate commitment",
        "policy": os.path.join(ROOT, "real_policy_meridian.txt"),
        # The sentence of the public commitment this suite is really about. We
        # quote it straight out of the file rather than retyping it, so what the
        # dashboard shows is the document's own wording, not a paraphrase.
        "policy_quote_hint": "for all three scopes",
        "preamble": (
            "_Real-document verification test: genuine published climate-commitment "
            "language (reproduced under the fictional name \"Meridian Industries\") "
            "against a hypothetical draft clause. This is a proof of concept, not a "
            "live compliance review._"
        ),
        "cases": [
            {
                "draft": os.path.join(ROOT, "test_draft_meridian_narrowing.txt"),
                "label": "NARROWING draft (redefines carbon-negative as Scope 1 & 2 only)",
                "expected_contradiction": True,
                # The clause that does the narrowing, quoted from the draft itself.
                "quote_hint": "expressly excluded",
                "case_title": (
                    "Matter: Meridian Industries — Real-World Language Verification "
                    "(Narrowing Case)"
                ),
            },
            {
                "draft": os.path.join(ROOT, "test_draft_meridian_clean.txt"),
                "label": "CLEAN draft (honors Scope 1, 2 and 3)",
                "expected_contradiction": False,
                "quote_hint": "shall encompass",
                "case_title": (
                    "Matter: Meridian Industries — Real-World Language Verification "
                    "(Clean Case)"
                ),
            },
        ],
    },
    {
        "key": "privacy",
        "company": "Quillhaven Communications",
        "subject": "a published data-privacy commitment about never monetizing personal data",
        "policy": os.path.join(ROOT, "real_policy_quillhaven.txt"),
        # The promise this suite turns on: personal data is never sold, rented
        # or monetized. Quoted from the file, not retyped.
        "policy_quote_hint": "rent or monetize",
        "preamble": (
            "_Real-document verification test — second domain, no code or prompt changes: "
            "genuine published data-privacy commitment language (reproduced under the "
            "fictional name \"Quillhaven Communications\") against a hypothetical draft "
            "clause. This is a proof of concept, not a live compliance review._"
        ),
        "cases": [
            {
                "draft": os.path.join(ROOT, "test_draft_quillhaven_narrowing.txt"),
                "label": "NARROWING draft (permits monetizing user data with 'trusted commercial partners')",
                "expected_contradiction": True,
                "quote_hint": "trusted commercial partners",
                "case_title": (
                    "Matter: Quillhaven Communications — Data Privacy Commitment "
                    "Verification (Narrowing Case)"
                ),
            },
            {
                "draft": os.path.join(ROOT, "test_draft_quillhaven_clean.txt"),
                "label": "CLEAN draft (honors the no-sale, no-retention, minimum-disclosure promise)",
                "expected_contradiction": False,
                "quote_hint": "shall not sell, rent, license",
                "case_title": (
                    "Matter: Quillhaven Communications — Data Privacy Commitment "
                    "Verification (Clean Case)"
                ),
            },
        ],
    },
]

# Every case, flattened, each carrying a back-reference to the suite it belongs
# to. The suite is what supplies the policy file, the quote hint and the memo
# preamble, so nothing about a case is hardcoded to one subject.
CASES = []
for _suite in SUITES:
    for _case in _suite["cases"]:
        _case["suite"] = _suite
        CASES.append(_case)

# How the Reasoner's plain-language verdict becomes a flagged/clear decision now
# lives in verdict_reader.py, so this test and the dashboard's upload review grade
# a verdict by exactly the same rules. The reasoning text itself is always
# printed below, so a human can see the agent's own words either way.
from verdict_reader import looks_like_contradiction

# Where one sentence ends and the next begins. The second alternative covers a
# sentence that closes with a bracket or quote mark — "(...text omitted.) Next
# sentence" — which the simple version ran together into one long quote.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|(?<=[.!?][)\]\"'”])\s+")


def quoted_sentence(path: str, must_contain: str) -> str:
    """
    Pulls one sentence VERBATIM out of a document — the first one containing
    `must_contain`.

    This is a quote, not a summary. The dashboard's "the language in question"
    panel is supposed to show the exact wording each side actually used, and
    these documents open with a source note and a "this is hypothetical"
    warning that would otherwise drown the real clause out.
    """
    try:
        with open(path, encoding="utf-8") as f:
            text = " ".join(f.read().split())
    except OSError:
        return ""
    for sentence in re.split(SENTENCE_BREAK, text):
        if must_contain.lower() in sentence.lower():
            return sentence.strip()
    return ""


def build_analysis(case: dict, result: dict) -> str:
    """
    Assembles the case memo that gets logged and shown in the dashboard.

    Everything substantive here is real output: the two Fact lines are quoted
    word-for-word from the documents, and the judgment and memo are the real
    Reasoner's and Writer's own text. The headings are the ones the dashboard
    already knows how to read, so it lays these cases out the same way it lays
    out an inbox scan — no dashboard changes needed for a new suite.
    """
    suite = case["suite"]
    policy_quote = quoted_sentence(suite["policy"], suite["policy_quote_hint"])
    draft_quote = quoted_sentence(case["draft"], case["quote_hint"])

    parts = [suite["preamble"]]
    if policy_quote:
        parts.append(f"**Policy Fact:** {policy_quote}")
    if draft_quote:
        parts.append(f"**Draft Fact:** {draft_quote}")
    if result.get("reasoning"):
        parts.append("**Conclusion (Reasoner, real AI):**")
        parts.append(result["reasoning"].strip())
    if result.get("memo"):
        parts.append(
            "**Writer's proposed redline and escalation memo (real AI) — "
            "PENDING HUMAN APPROVAL, nothing has been applied:**"
        )
        parts.append(result["memo"].strip())
    return "\n\n".join(parts)

def record_case(case: dict, result: dict) -> bool:
    """
    Writes this case into scan_log.jsonl through monitor.log_result(), so the
    entry has exactly the same shape as one the background watcher writes and
    the dashboard needs no special handling.

    It APPENDS one line. It does not read, rewrite, or remove anything already
    in the log, and it never goes near approvals.json — so the sample inbox
    matters, including any decisions recorded against them, stay untouched.
    """
    config = load_config()
    try:
        log_result(
            config["log_file"],
            os.path.basename(case["draft"]),
            {
                "contradiction_found": result["found"],
                "final_output": build_analysis(case, result),
                "mode": "REAL",
            },
            case_title=case["case_title"],
            policy_document=os.path.basename(case["suite"]["policy"]),
        )
    except OSError as e:
        print(f"  (Could not write this case to the scan log: {e})")
        return False
    return True


def run_case(case: dict) -> dict:
    """Run the real agents in fixed order, pacing calls for the free tier."""
    policy = case["suite"]["policy"]

    print("  Reader is reading the public commitment...")
    policy_out = read_document(policy)
    time.sleep(PACE)

    print("  Reader is reading the draft contract...")
    draft_out = read_document(case["draft"])
    time.sleep(PACE)

    print("  Reasoner is judging whether the draft contradicts the commitment...")
    reasoner_out = reason_about_contradiction(policy_out, draft_out)
    reasoning = reasoner_out.get("reasoning", "")
    found = looks_like_contradiction(reasoning)

    memo = ""
    if found:
        time.sleep(PACE)
        print("  Contradiction suspected -- Writer is drafting the redline + memo...")
        writer_out = write_output(reasoner_out, draft_out["raw_text"])
        memo = writer_out.get("output") or writer_out.get("memo") or ""

    return {"reasoning": reasoning, "memo": memo, "found": found}

def case_matches(case: dict, token: str) -> bool:
    """A word on the command line matches a case if it names that case's
    suite (e.g. "privacy") or appears in its label (e.g. "narrowing")."""
    return token in case["suite"]["key"].lower() or token in case["label"].lower()


def selected_cases():
    """
    By default we run every case in every suite. Any words given on the command
    line narrow that down — each word has to match, so `privacy` runs both
    privacy cases, `narrowing` runs the flag-it case in every suite, and
    `privacy narrowing` runs exactly one case.

    Narrowing matters on the free tier: focusing the whole per-minute token
    budget on one case makes it far more likely to finish without rate limits.
    """
    tokens = [a.strip().lower() for a in sys.argv[1:] if a.strip()]
    if not tokens:
        return CASES
    picked = [c for c in CASES if all(case_matches(c, t) for t in tokens)]
    if picked:
        return picked
    print(f"(Nothing matched '{' '.join(tokens)}' -- running all cases instead.)")
    return CASES


def main():
    cases = selected_cases()

    # Which suites this run actually touches. Deduplicated by key on purpose:
    # each case holds a reference back to its suite, and each suite holds its
    # cases, so comparing the dicts themselves would chase that loop forever.
    seen_keys, suites_in_run = [], []
    for case in cases:
        if case["suite"]["key"] not in seen_keys:
            seen_keys.append(case["suite"]["key"])
            suites_in_run.append(case["suite"])

    print("=" * 72)
    print("REAL-DOCUMENT TESTS")
    for suite in suites_in_run:
        print(f"  {suite['key']}: {suite['company']} — {suite['subject']}")
        print(f"     source cited inside {os.path.basename(suite['policy'])}")
    print("vs. hypothetical draft contract clauses. Real AI, fixed-order path.")
    print("Every suite runs through the same agents with the same prompts.")
    print("=" * 72)

    results_summary = []

    # The free Groq tier resets its per-minute token budget every 60s. If this
    # script was just run, that window may still be depleted, which would make
    # the first calls fail on rate limits. Start from a clean window.
    warmup = 60
    print(f"\nWarming up: waiting {warmup}s so the free-tier rate-limit window is clear...")
    time.sleep(warmup)

    for i, case in enumerate(cases, 1):
        print(f"\n\n----- CASE {i} [{case['suite']['key']}]: {case['label']} -----")
        print(f"Policy file: {os.path.basename(case['suite']['policy'])}")
        print(f"Draft file:  {os.path.basename(case['draft'])}\n")
        try:
            result = run_case(case)
        except Exception as e:
            print(f"  !! This case failed to run: {e}")
            results_summary.append((f"{case['suite']['key']}: {case['label']}", "ERROR"))
            continue

        found = result["found"]
        if found is True:
            verdict = "FLAGGED (contradiction)"
        elif found is False:
            verdict = "CLEAR (no contradiction)"
        else:
            verdict = "UNCLEAR (could not parse a verdict -- read the reasoning)"

        expected = "FLAGGED" if case["expected_contradiction"] else "CLEAR"
        match = "PASS" if (found is case["expected_contradiction"]) else "CHECK"
        results_summary.append((f"{case['suite']['key']}: {case['label']}", match))

        print(f"\n  Expected: {expected}   |   Agent said: {verdict}   ->   {match}")
        print("\n  --- Reasoner's judgment (real AI) ---")
        print(result["reasoning"] or "(no reasoning returned)")
        if result["memo"]:
            print("\n  --- Writer's proposed redline + escalation memo (real AI) ---")
            print(result["memo"])

        if record_case(case, result):
            print(f"\n  Recorded on the dashboard as: {case['case_title']}")

        if i < len(cases):
            print(f"\n  (pausing {PACE}s before the next case to respect the rate limit...)")
            time.sleep(PACE)

    print("\n\n" + "=" * 72)
    print("SUMMARY")
    for label, outcome in results_summary:
        print(f"  [{outcome}] {label}")
    print("Each case above was appended to scan_log.jsonl under its own case title,")
    print("so it shows on the dashboard. No contract was modified, approvals.json")
    print("was not touched, and no existing log entry was changed or removed.")
    print("=" * 72)


if __name__ == "__main__":
    main()
