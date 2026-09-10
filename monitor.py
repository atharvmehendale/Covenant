"""
Watches the inbox CONTINUOUSLY — this is the actual background worker,
not a one-time check.

Two things make this genuinely "background" behavior instead of a
script you have to remember to run:

1. It loops forever, checking the inbox every N seconds (set in
   config.json), instead of running once and exiting.
2. It remembers which documents it has already reviewed (in
   processed_files.json), so it doesn't re-flag the same document over
   and over on every loop — only genuinely NEW or CHANGED documents get
   reviewed.

How "already reviewed" is decided: by the document's CONTENT, not just
its filename. Each reviewed file is recorded with a SHA-256 fingerprint
of its contents. So if someone edits a draft and saves it under the same
name — exactly how a real contract negotiation works, revision after
revision — the fingerprint changes and the document is re-reviewed.
Tracking filenames alone would have silently ignored that new version.

This routes through orchestrator.py — meaning every new document that
arrives is reviewed by the full Reader/Reasoner/Writer team.

What can be dropped in the inbox: PDF, Word (.docx) or plain text.
document_intake.py does the reading, so a real PDF contract is reviewed
properly rather than read as binary noise. A document we CAN'T read — a
scanned PDF with no text layer, a password-protected file — is never
quietly skipped: it is recorded as its own case marked COULD_NOT_READ,
with the reason, and no AI call is made. A file sitting in the inbox with
no entry against it would look exactly like one that was reviewed and
found clean, which is the failure this guards against.

How to stop it: press Ctrl+C in the terminal.
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_config
from orchestrator import run_pipeline

PROCESSED_FILES_TRACKER = "processed_files.json"
HEARTBEAT_FILE = "heartbeat.json"


def write_heartbeat(heartbeat_path: str, status: str, interval: int):
    """
    Records a tiny liveness signal for the dashboard: when the watcher last
    ran a check and whether it is mid-check right now. Best-effort only — a
    failure here must never disturb the actual scanning, so it swallows errors.
    """
    try:
        payload = {
            "status": status,  # "checking" while a pass runs, "idle" between passes
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scan_interval_seconds": interval,
        }
        with open(heartbeat_path, "w") as f:
            json.dump(payload, f)
    except OSError:
        pass


def file_fingerprint(path: str) -> str:
    """
    A SHA-256 fingerprint of the file's exact contents.

    This is what lets us tell "a document I've already reviewed" apart from
    "a NEW REVISION of a document I've already reviewed." Two files with the
    same name but different wording produce different fingerprints, so an
    edited draft gets reviewed again instead of being silently skipped.

    Read in chunks so a large document doesn't have to sit in memory at once.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_processed_files(tracker_path: str, inbox_dir: str) -> dict:
    """
    Loads what we've already reviewed, as {filename: content_fingerprint}.

    Also upgrades the OLD format gracefully. Earlier versions stored a plain
    list of filenames with no fingerprints. If we find that, we adopt each
    file's CURRENT contents as its fingerprint — so upgrading doesn't cause a
    noisy re-scan of every document that was already reviewed.

    Returns {} if the tracker is missing or unreadable, which just means
    "nothing reviewed yet" — a corrupt tracker must never crash the watcher.
    """
    if not os.path.exists(tracker_path):
        return {}

    try:
        with open(tracker_path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}

    if isinstance(data, dict):
        return data

    migrated = {}
    for filename in data:
        path = os.path.join(inbox_dir, filename)
        try:
            migrated[filename] = file_fingerprint(path)
        except OSError:
            continue  # file is gone; treat it as never reviewed
    return migrated


def save_processed_files(tracker_path: str, processed: dict):
    with open(tracker_path, "w") as f:
        json.dump(processed, f, indent=2, sort_keys=True)


def _extract_analysis(result: dict) -> str:
    """
    Pulls the human-readable memo / proposed-redline text out of a pipeline
    result, whether it came from the real AI pipeline (final_output) or the
    FAKE_MODE fallback (writer_output.memo). Returns "" if there's nothing
    to show (e.g. a clean document).
    """
    if result.get("final_output"):
        return result["final_output"]
    writer_output = result.get("writer_output")
    if writer_output and writer_output.get("needs_output"):
        return writer_output.get("memo", "")
    return ""


def log_result(log_file: str, filename: str, result: dict, case_title: str = None,
               policy_document: str = None, source: dict = None):
    """Appends one scan result as a single line of JSON to the log file.

    We store the verdict, a human-readable status, and the full memo/redline
    text — so the dashboard has something real to show and approve, not just
    a bare summary line.

    `case_title`, `policy_document` and `source` are all optional and normally
    left off: inbox scans are all judged against the one policy named in
    config.json, and the dashboard works out a readable case name from the
    document itself. They exist for entries that aren't ordinary inbox reviews:

      - the real-document verification test sets the first two, so its cases
        announce themselves as a proof-of-concept and name the real published
        commitment they were compared against.
      - a document uploaded through the dashboard sets `source`, a small dict
        recording where the file came from and how its text was obtained —
        e.g. {"kind": "upload", "text_document": "uploads/extracted/x.txt",
        "format": "PDF", "pages": 2, "note": "..."}. That is what lets the
        dashboard quote a PDF's wording (it reads the extracted text sidecar,
        never the PDF bytes) and show the reader honestly how the words were
        obtained.

    Ordinary scans set none of the three, so their entries keep exactly the
    same shape they always had — an absent field means "behave as before".
    """
    contradiction = result.get("contradiction_found")
    if result.get("status"):
        # A caller can state the status outright. Only used for outcomes that
        # aren't a verdict at all — chiefly COULD_NOT_READ, where there was no
        # review to have a verdict about.
        status = result["status"]
    elif contradiction is True:
        status = "PENDING_HUMAN_APPROVAL"
    elif contradiction is False:
        status = "CLEAR"
    else:
        status = "UNKNOWN"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "document": filename,
        "contradiction_found": contradiction,
        "status": status,
        "analysis": _extract_analysis(result),
        "mode": result.get("mode"),
    }
    if case_title:
        entry["case_title"] = case_title
    if policy_document:
        entry["policy_document"] = policy_document
    if source:
        entry["source"] = source
    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def source_note(intake: dict) -> dict:
    """
    A small record of HOW a document's words were obtained, or None when there's
    nothing worth saying.

    A plain .txt read cleanly needs no explanation, so those entries keep exactly
    the shape they always had. A PDF does need one: a compliance reviewer looking
    at a redline is entitled to know the text came off page 2 of a scan, and to be
    told if three pages of it were never read at all.
    """
    from document_intake import describe

    interesting = intake.get("format") != "plain text" or intake.get("warnings")
    if not interesting:
        return None

    note = {
        "kind": "inbox",
        "format": intake.get("format"),
        "method": intake.get("method"),
        "note": describe(intake),
    }
    if intake.get("page_count"):
        note["pages"] = intake["page_count"]
        note["pages_with_text"] = intake["pages_with_text"]
    if intake.get("warnings"):
        note["warnings"] = intake["warnings"]
    return note


def log_unreadable(config: dict, filename: str, intake: dict):
    """
    Records that a document arrived and could NOT be read — a real outcome that
    has to be visible, not swallowed.

    A scanned contract sitting in the inbox with no entry against it looks
    exactly like a contract that was reviewed and found clean. That is the one
    failure mode this whole intake layer exists to prevent, so it gets a case of
    its own, marked COULD_NOT_READ, with the honest explanation as its analysis.
    No AI was called and no verdict is claimed.
    """
    log_result(
        config["log_file"],
        filename,
        {
            "contradiction_found": None,
            "status": "COULD_NOT_READ",
            "final_output": (
                f"**This document could not be read, so it was not reviewed.**\n\n"
                f"{intake.get('message', 'No text could be extracted.')}\n\n"
                "No AI review was run and no verdict is being claimed. Supply a "
                "text-based copy of this document and it will be reviewed on the "
                "next pass."
            ),
            "mode": "NOT REVIEWED (unreadable)",
        },
        source={
            "kind": "inbox",
            "format": intake.get("format") or "unknown",
            "problem": intake.get("problem"),
            "note": intake.get("message", ""),
        },
    )


def process_document(config: dict, filename: str) -> dict:
    """Runs one document through the full agent pipeline and logs the result."""
    draft_path = os.path.join(config["inbox_dir"], filename)

    # Can we actually read it? Asked FIRST, before any AI call, because the
    # honest answer for a scanned PDF is "we couldn't" — and finding that out
    # cheaply is better than paying for a confident review of an empty string.
    from document_intake import extract
    intake = extract(draft_path)
    if not intake["ok"]:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] [UNREADABLE] {filename} -- "
            f"{intake['message']} Not reviewed."
        )
        log_unreadable(config, filename, intake)
        return {"contradiction_found": None, "status": "COULD_NOT_READ"}

    for warning in intake["warnings"]:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [PARTIAL]    {filename} -- {warning}")

    result = run_pipeline(config["policy_file"], draft_path)

    # Only escalate on a genuine contradiction. Clean documents stay silent —
    # no memo, no noise — which is the whole point of the background watcher.
    should_escalate = result.get("contradiction_found") is True

    if should_escalate:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [FLAGGED] {filename} — violation found, escalating.")
        analysis = _extract_analysis(result)
        if analysis:
            print(analysis)
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [CLEAR]   {filename} — no issue, no action needed.")

    log_result(config["log_file"], filename, result, source=source_note(intake))
    return result


def check_for_new_documents(config: dict, processed: dict) -> dict:
    """
    Looks at the inbox and reviews anything new OR changed.

    A document is skipped only if we've seen a file by that name AND its
    contents still fingerprint the same. If the wording changed, it counts as
    a new revision and gets a fresh review.
    """
    inbox_dir = config["inbox_dir"]

    for filename in sorted(os.listdir(inbox_dir)):
        path = os.path.join(inbox_dir, filename)
        if not os.path.isfile(path):
            continue  # ignore subfolders

        try:
            fingerprint = file_fingerprint(path)
        except OSError:
            # Someone may be mid-save, or the file just vanished. Skip it this
            # round; we'll pick it up on the next pass.
            continue

        previously_seen = processed.get(filename)
        if previously_seen == fingerprint:
            continue  # already reviewed, and unchanged since

        if previously_seen is not None:
            # Plain ASCII here on purpose: this line can print before any agent
            # code has run, so the project's central UTF-8 fix (in
            # model_provider.py) may not have been imported yet, and a fancy
            # dash would render as garbage on a Windows cp1252 console.
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] {filename} has changed "
                f"since its last review -- reviewing the new version."
            )

        process_document(config, filename)
        processed[filename] = fingerprint

    return processed


def watch_loop():
    """The actual background worker — runs forever until you stop it with Ctrl+C."""
    config = load_config()
    tracker_path = os.path.join(os.path.dirname(config["log_file"]) or ".", PROCESSED_FILES_TRACKER)
    heartbeat_path = os.path.join(os.path.dirname(config["log_file"]) or ".", HEARTBEAT_FILE)
    interval = config.get("scan_interval_seconds", 30)

    processed = load_processed_files(tracker_path, config["inbox_dir"])

    print(f"Covenant agent is now watching '{config['inbox_dir']}' in the background.")
    print(f"Checking every {interval} seconds. Press Ctrl+C to stop.")
    print("New documents AND edited revisions of old ones are both reviewed.\n")

    try:
        while True:
            write_heartbeat(heartbeat_path, "checking", interval)
            processed = check_for_new_documents(config, processed)
            save_processed_files(tracker_path, processed)
            write_heartbeat(heartbeat_path, "idle", interval)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped. The agent is no longer watching the inbox.")


if __name__ == "__main__":
    watch_loop()
