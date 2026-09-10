"""
SCAN ONCE — one pass over the inbox, then exit.

monitor.py is the background watcher: it loops forever, re-checking the inbox
every N seconds. That is the right shape for a machine that stays on. It is the
WRONG shape for GitHub Actions, which visits the repo on a timer, does its
work, and leaves. This script is that visiting version: exactly one cycle of
the watcher's loop, run standalone.

The important word there is EXACTLY. This does not re-implement the scanning
logic — it imports and calls the very same functions monitor.py uses
(load_processed_files, check_for_new_documents, save_processed_files), so a
document reviewed here is reviewed identically to one reviewed by the watcher:
same content-fingerprint rule for new-vs-changed documents, same unreadable
handling, same real Reader/Reasoner/Writer pipeline, same scan log. There are
not two scanning implementations to drift apart.

Exit code is 0 whether or not a contradiction was found — a flagged document
is a normal result of a scan, not a failure of it. The verdicts live in the
scan log, where the dashboard and any human reviewer read them. A non-zero
exit is reserved for the scan itself breaking, which is what a scheduler
actually needs to know about.

Usage:
    python scan_once.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from monitor import (
    PROCESSED_FILES_TRACKER,
    check_for_new_documents,
    load_processed_files,
    save_processed_files,
)


def scan_once() -> dict:
    """
    Runs one full pass over the inbox and saves what was learned.

    Returns a small summary dict (documents seen, reviewed, skipped) so a
    caller — or a test — can check what happened without parsing print output.
    """
    config = load_config()
    # The tracker sits next to the scan log, exactly where monitor.py keeps it,
    # so the watcher and this script share ONE record of what has been reviewed.
    tracker_path = os.path.join(
        os.path.dirname(config["log_file"]) or ".", PROCESSED_FILES_TRACKER
    )

    processed = load_processed_files(tracker_path, config["inbox_dir"])
    before = dict(processed)

    # Save what we learned EVEN IF the pass dies part-way through, and this is
    # not a theoretical worry — the first real run of this script reviewed three
    # documents and then the network dropped on the fourth. Without the finally,
    # those three finished reviews were already written to the scan log but
    # never recorded as processed, so the next run would review them a second
    # time: duplicate cases in front of a reviewer, and three wasted sets of AI
    # calls against a limited free tier. check_for_new_documents fills in the
    # same dict object it was handed, one document at a time, so the partial
    # progress is genuinely there to be saved.
    try:
        processed = check_for_new_documents(config, processed)
    finally:
        save_processed_files(tracker_path, processed)

    # "Reviewed" means the fingerprint we now hold differs from the one we
    # arrived with: that covers brand-new documents and new revisions of old
    # ones alike, which is the same distinction the watcher makes.
    reviewed = sorted(
        name for name, fingerprint in processed.items()
        if before.get(name) != fingerprint
    )
    skipped = sorted(set(processed) - set(reviewed))

    return {"seen": len(processed), "reviewed": reviewed, "skipped": skipped}


if __name__ == "__main__":
    from datetime import datetime

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Covenant compliance scan starting (single pass).")
    summary = scan_once()

    if summary["reviewed"]:
        print(f"\nReviewed {len(summary['reviewed'])} document(s): "
              + ", ".join(summary["reviewed"]))
    if summary["skipped"]:
        print(f"Skipped {len(summary['skipped'])} already-reviewed, unchanged document(s): "
              + ", ".join(summary["skipped"]))
    if not summary["reviewed"] and not summary["skipped"]:
        print("The inbox is empty. Nothing to review.")

    print("Scan complete. Results are in the scan log.")
