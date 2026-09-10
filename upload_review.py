"""
UPLOAD REVIEW — reviewing a document someone hands you, on demand.

The background watcher (monitor.py) is patient: drop a file in the inbox and it
gets reviewed on the next pass. That is the right model for a firm's document
flow, but it is not how a lawyer with a contract in front of them works. They
want to hand over the PDF and get an answer now. This module is that path.

What it deliberately does NOT do is review the document differently. It saves
the file, reads it through document_intake (the same reader the watcher uses),
runs the same real Reader / Reasoner / Writer agents, and writes the result with
the same monitor.log_result() the watcher writes with. An uploaded document
becomes a case in the same case file, judged by the same rules. There is no
second, easier code path — that was the point.

THE SAFETY PROPERTIES, unchanged:
  - the uploaded file is written once and never modified afterwards
  - approvals.json is never touched here; a flagged upload still needs a human
    to press Approve or Reject, exactly like every other matter
  - no redline is ever applied to anything
  - a document that can't be read is reported as unreadable and NOT reviewed,
    so nobody is shown a confident AI review of an empty page

Two engines are available, and the caller picks one explicitly:
  "sequential"   the fixed-order path — four small, spaced-out calls. Fits a
                 free API tier on a realistically long contract.
  "orchestrator" the full multi-agent path, where an Orchestrator agent decides
                 to call each specialist itself. One large call, so on a free
                 tier a long document can hit the per-minute token limit.
Whichever is chosen is what runs. There is no silent fallback between them,
because a human reading a verdict is entitled to know which engine produced it.
"""

import hashlib
import os
import re

from document_intake import describe, extract
from monitor import log_result

# Engine names the caller may ask for, with the fixed-order path first because
# it is the one that reliably finishes on a free tier.
ENGINES = ("sequential", "orchestrator")

# What a saved upload's filename is allowed to contain. Everything else is
# replaced. This is what stops a crafted name like "..\..\config.json" from
# writing outside the uploads folder.
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    """
    Turns whatever name a browser hands us into something safe to write to disk.

    Path separators, "..", leading dots and control characters are all removed,
    so the result can only ever land inside the uploads folder. The visible name
    is kept as close to the original as possible, because it becomes the case
    name a human reads.
    """
    name = os.path.basename((name or "").replace("\\", "/"))
    stem, extension = os.path.splitext(name)
    stem = SAFE_NAME.sub("_", stem).strip("._-")
    extension = SAFE_NAME.sub("", extension).lower()
    if not stem:
        stem = "uploaded_document"
    return (stem[:80] + extension[:10]) or "uploaded_document"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_upload(uploads_dir: str, filename: str, data: bytes) -> str:
    """
    Writes the uploaded bytes into the uploads folder and returns the path.

    Nothing is ever overwritten with different content. If a file of this name is
    already there:
      - identical contents  -> we reuse it, so re-uploading the same contract
                               updates the same matter instead of cloning it
      - different contents  -> the new one is saved as "name_2.pdf", and becomes
                               its own matter, because two different contracts
                               that happen to share a filename are not the same
                               document and must never be merged into one case

    The bytes are written exactly as received. The file is not cleaned up,
    reformatted, or touched again after this.
    """
    os.makedirs(uploads_dir, exist_ok=True)
    safe = safe_filename(filename)
    stem, extension = os.path.splitext(safe)
    incoming = _sha256_bytes(data)

    candidate = safe
    attempt = 1
    while os.path.exists(os.path.join(uploads_dir, candidate)):
        existing = os.path.join(uploads_dir, candidate)
        try:
            if _sha256_file(existing) == incoming:
                return existing  # the very same document; nothing to write
        except OSError:
            pass
        attempt += 1
        candidate = f"{stem}_{attempt}{extension}"

    path = os.path.join(uploads_dir, candidate)
    with open(path, "wb") as f:
        f.write(data)
    return path


def upload_source_note(intake: dict, stored_path: str, engine: str) -> dict:
    """
    The record of where this case's words came from, stored on the log entry.

    A compliance team about to act on a redline needs to know the text under
    discussion was extracted from page 2 of a PDF by pypdf — not typed in, not
    guessed, and not partly missed. `text_document` is the file the dashboard
    re-reads to quote the document, which is the original upload itself: there is
    no separate copy of the text to drift out of step with it.
    """
    note = {
        "kind": "upload",
        "text_document": os.path.basename(stored_path),
        "format": intake.get("format") or "unknown",
        "method": intake.get("method") or "",
        "note": describe(intake),
        "engine": engine,
    }
    if intake.get("page_count"):
        note["pages"] = intake["page_count"]
        note["pages_with_text"] = intake["pages_with_text"]
    if intake.get("warnings"):
        note["warnings"] = intake["warnings"]
    return note


def review_upload(config: dict, filename: str, data: bytes, engine: str = "sequential",
                  on_progress=None, pace: int = None) -> dict:
    """
    The whole on-demand review, start to finish.

    Returns a dict describing what happened, which the dashboard renders:
        ok            False if the document could not be read at all
        problem       why not, e.g. "scanned" (None when ok)
        message       the honest explanation to show the human
        stored_path   where the untouched upload was saved
        intake        the full extraction result, warnings and all
        document      the name this case is filed under
        logged        True if a case was written to the scan log
        result        the pipeline's result (None when nothing was reviewed)

    An unreadable document stops here, BEFORE any AI call: no model is invoked,
    no case is filed, and no verdict is invented. That is the honest outcome for
    a scanned contract, and it costs nothing to reach.
    """
    if engine not in ENGINES:
        raise ValueError(f"Unknown engine '{engine}'. Choose one of: {', '.join(ENGINES)}")

    def say(message: str):
        if on_progress:
            on_progress(message)

    say("Saving the document...")
    stored_path = store_upload(config["uploads_dir"], filename, data)
    document = os.path.basename(stored_path)

    say("Reading the text out of the document...")
    intake = extract(stored_path)

    if not intake["ok"]:
        # Nothing was reviewed, so nothing is logged and no verdict exists. The
        # saved file stays on disk so the user can see what they sent us.
        return {
            "ok": False,
            "problem": intake["problem"],
            "message": intake["message"],
            "stored_path": stored_path,
            "intake": intake,
            "document": document,
            "logged": False,
            "result": None,
        }

    if engine == "sequential":
        from orchestrator import run_pipeline_sequential
        result = run_pipeline_sequential(
            config["policy_file"], stored_path, pace=pace, on_progress=on_progress
        )
    else:
        from orchestrator import run_pipeline
        say("The Orchestrator is directing its team...")
        result = run_pipeline(config["policy_file"], stored_path)

    say("Filing the case...")
    log_result(
        config["log_file"],
        document,
        result,
        source=upload_source_note(intake, stored_path, engine),
    )

    return {
        "ok": True,
        "problem": None,
        "message": describe(intake),
        "stored_path": stored_path,
        "intake": intake,
        "document": document,
        "logged": True,
        "result": result,
    }


if __name__ == "__main__":
    # A command-line rehearsal of exactly what the dashboard's upload button
    # does, so the path can be tested without a browser:
    #     python upload_review.py samples/jv_texas_refinery.pdf
    import sys

    from config import load_config

    if len(sys.argv) < 2:
        print(__doc__)
        print("Usage: python upload_review.py <file> [sequential|orchestrator]")
        raise SystemExit(0)

    target = sys.argv[1]
    chosen = sys.argv[2] if len(sys.argv) > 2 else "sequential"

    with open(target, "rb") as handle:
        payload = handle.read()

    outcome = review_upload(
        load_config(),
        os.path.basename(target),
        payload,
        engine=chosen,
        on_progress=lambda message: print(f"  {message}"),
    )

    print()
    print(f"=== UPLOAD REVIEW: {outcome['document']} ===")
    if not outcome["ok"]:
        print(f"NOT REVIEWED ({outcome['problem']})")
        print(outcome["message"])
        print("No AI was called, and no case was filed.")
        raise SystemExit(0)

    print(f"Text source : {outcome['message']}")
    for warning in outcome["intake"]["warnings"]:
        print(f"Warning     : {warning}")
    print(f"Engine      : {outcome['result']['mode']}")
    print(f"Verdict     : {outcome['result']['contradiction_found']}")
    print("Filed as a case in the scan log. approvals.json was not touched.")
    print()
    print(outcome["result"]["final_output"])
