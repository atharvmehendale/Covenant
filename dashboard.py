"""
THE COMPLIANCE CASE FILE  (the human's side of the system)

A small Streamlit app that lets a human review what the agents have found, and
decide what to do about it. It presents each reviewed document as a legal
MATTER — a case with a readable title you click to open — rather than as a row
of raw filenames.

What it does:
  - reads the monitor's log (scan_log.jsonl) and shows each document as a case
    card with a law-firm status
  - opens a real case view (a modal) with a plain-language summary, the
    conflicting language from both documents side by side, and the suggested fix
  - offers Approve / Reject at the bottom of that case view
  - reviews a document you UPLOAD, on demand, without waiting for the
    background watcher's next pass

The upload panel is the one place this app starts a review of its own. It does
not analyse anything itself: it hands the file to upload_review.py, which uses
the same document reader, the same three real agents and the same log writer the
background watcher uses. An uploaded PDF becomes a case in this same case file,
judged by the same rules. Everything else on this page is read-only.

SAFETY PROPERTIES (unchanged, and deliberately narrow):
  - Approving or rejecting only RECORDS your decision in approvals.json.
  - An uploaded file is saved once and never modified. Reviewing it never
    approves it — a flagged upload waits for a human exactly like every other
    matter.
  - It never edits a contract, never writes to the inbox, and never rewrites or
    removes anything already in the scan log. Nothing is ever auto-applied.

How to run it:
    python -m streamlit run dashboard.py

Keep monitor.py running separately in its own terminal if you want the inbox
watched in the background; uploads here work with or without it. Use Refresh to
pull in new scans.
"""

import json
import os
import re
import sys
from datetime import datetime

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))

from config import load_config
from approvals import load_approvals, record_decision
from document_intake import SUPPORTED_EXTENSIONS, load_text_or_empty

# Case status wording a law firm would actually use, paired with the colour
# used for quick scanning. Keys are the raw statuses the monitor and the
# approvals file store, so the underlying data format is untouched.
CASE_STATUS = {
    "CLEAR": ("No Issues Found", "green"),
    "PENDING_HUMAN_APPROVAL": ("Pending Review", "red"),
    "APPROVED": ("Approved", "blue"),
    "REJECTED": ("Rejected", "orange"),
    # Not a verdict — a document that arrived and could not be read at all.
    # It gets a case anyway, because a scanned contract with no entry against
    # it would look exactly like one that was reviewed and found clean.
    "COULD_NOT_READ": ("Could Not Be Read", "violet"),
}

# ----------------------------------------------------------------------------
# The house style
# ----------------------------------------------------------------------------
# Deliberately a presentation layer and nothing more: no function below reads
# these, no data shape depends on them, and deleting this whole block leaves a
# working (if plainer) dashboard. That separation is the point — the visual pass
# must not be able to change what the agents found or what a human decided.

INK = "#0b1220"          # near-black navy, the page itself
INK_RAISED = "#131c2e"   # a case file lifted off the desk
INK_EDGE = "#243149"     # borders
GOLD = "#c8a24a"         # the firm's accent: rules, the name, key emphasis
GOLD_SOFT = "#e0c37e"
PARCHMENT = "#eef1f6"    # body text on dark
PARCHMENT_DIM = "#9aa7bd"
BURGUNDY = "#7f1d2e"     # reserved for genuine escalation
STATUS_GREEN = "#4ea36b"  # watcher actively checking (the only animated state)
STATUS_GRAY = "#5c6b82"   # watcher idle/not running — neutral, deliberately not red

# Serif for anything that stands in for letterhead (the firm name, case titles);
# sans for body copy, which is what actually gets read at length. The stacks are
# system fonts on purpose — a web font fetch that fails mid-demo is a broken
# page, and these degrade to something reasonable everywhere.
SERIF = "'Iowan Old Style','Palatino Linotype','Book Antiqua',Palatino,Georgia,'Times New Roman',serif"
SANS = "'Inter','Segoe UI',system-ui,-apple-system,'Helvetica Neue',Arial,sans-serif"

# Status accent colours for the card rail, keyed by the SAME raw status strings
# CASE_STATUS uses. Visual only; the badge text still comes from CASE_STATUS.
STATUS_RAIL = {
    "CLEAR": "#3f7d58",
    "PENDING_HUMAN_APPROVAL": BURGUNDY,
    "APPROVED": "#2f5d8a",
    "REJECTED": "#8a5a2f",
    "COULD_NOT_READ": "#5b4a7d",
}


def inject_house_style():
    """
    Applies the firm's visual identity.

    Streamlit's own theming can't reach most of this, so it goes in as CSS. It
    targets structural data-testid hooks rather than generated class names, which
    are the stable ones across Streamlit versions — but if a future version
    renames them, the consequence is a plainer page, never a broken one, because
    nothing here carries behaviour.
    """
    st.markdown(
        f"""
        <style>
        .stApp {{
            background:
              radial-gradient(1200px 600px at 15% -10%, #16223a 0%, transparent 60%),
              linear-gradient(180deg, {INK} 0%, #0e1626 100%);
            color: {PARCHMENT};
            font-family: {SANS};
        }}

        /* Letterhead type for display text; body copy stays sans.
           The descendant selectors are not redundant: Streamlit wraps heading
           TEXT in a <span> inside the h1/h2/h3, so a bare `h1 {{...}}` rule
           styles a box whose contents are then restyled by the generic `span`
           rule below. Without `h1 span` the titles silently stayed sans —
           found by inspecting the rendered page, not by reading the CSS. */
        h1, h2, h3,
        h1 span, h2 span, h3 span,
        .cv-firm, .cv-case-title {{
            font-family: {SERIF} !important;
            letter-spacing: .2px;
        }}
        h1, h1 span {{ color: {PARCHMENT} !important; font-weight: 600 !important; }}
        h2, h3, h2 span, h3 span {{ color: {PARCHMENT} !important; font-weight: 600 !important; }}
        p, li, span, label, .stMarkdown {{ font-family: {SANS}; }}

        /* The sidebar reads as the firm's masthead. */
        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #0a1120 0%, #0d1526 100%);
            border-right: 1px solid {INK_EDGE};
        }}
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h2 span {{
            color: {GOLD} !important;
        }}
        section[data-testid="stSidebar"] h2 {{
            border-bottom: 1px solid {INK_EDGE};
            padding-bottom: .5rem;
        }}
        /* The sidebar's small labels are index tabs, not letterhead — sans,
           uppercase, tracked out. Overrides the serif heading rule above, so it
           has to reach the inner span as well. */
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] h3 span {{
            font-size: .74rem !important;
            text-transform: uppercase;
            letter-spacing: .13em;
            color: {PARCHMENT_DIM} !important;
            font-family: {SANS} !important;
            font-weight: 600 !important;
        }}
        section[data-testid="stSidebar"] h3 {{ margin-bottom: .1rem; }}

        /* Case files: a bordered container becomes a filed folder.
           Targeted by the container's own `key=`, which Streamlit turns into a
           `st-key-...` class — the documented, version-stable hook. An earlier
           draft of this used data-testid="stVerticalBlockBorderWrapper", which
           simply does not exist in Streamlit 1.55: the rules silently matched
           nothing and the cards stayed default. Checked in the browser this
           time rather than assumed. */
        div[class*="st-key-casecard"], div.st-key-filingpanel {{
            background: {INK_RAISED};
            border: 1px solid {INK_EDGE} !important;
            border-radius: 4px !important;
            box-shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.6);
            transition: border-color .16s ease, transform .16s ease;
            padding: 1rem 1.15rem !important;
        }}
        div[class*="st-key-casecard"]:hover {{
            border-color: {GOLD} !important;
            transform: translateY(-1px);
        }}

        /* The case name: a link-style button restyled to read as a file label. */
        div[class*="st-key-casecard"] button[kind="tertiary"] {{
            font-family: {SERIF} !important;
            font-size: 1.16rem !important;
            font-weight: 600 !important;
            color: {PARCHMENT} !important;
            text-align: left !important;
            padding: 0 !important;
            border: none !important;
            background: transparent !important;
            text-decoration: none !important;
        }}
        div[class*="st-key-casecard"] button[kind="tertiary"]:hover {{
            color: {GOLD_SOFT} !important;
            background: transparent !important;
        }}

        /* Buttons: restrained, with the accent reserved for the primary action. */
        .stButton > button {{
            font-family: {SANS};
            border-radius: 3px;
            border: 1px solid {INK_EDGE};
            background: #1b2740;
            color: {PARCHMENT};
            font-weight: 500;
        }}
        .stButton > button:hover {{
            border-color: {GOLD};
            color: {GOLD_SOFT};
        }}
        .stButton > button[kind="primary"] {{
            background: {GOLD};
            border-color: {GOLD};
            color: #17120a;
            font-weight: 600;
        }}
        .stButton > button[kind="primary"]:hover {{
            background: {GOLD_SOFT};
            border-color: {GOLD_SOFT};
            color: #17120a;
        }}

        /* Metrics as a docket strip. */
        div[data-testid="stMetric"] {{
            background: {INK_RAISED};
            border: 1px solid {INK_EDGE};
            border-left: 2px solid {GOLD};
            border-radius: 3px;
            padding: .7rem .9rem;
        }}
        div[data-testid="stMetricLabel"] {{
            text-transform: uppercase;
            letter-spacing: .1em;
            font-size: .68rem !important;
            color: {PARCHMENT_DIM} !important;
        }}
        div[data-testid="stMetricValue"] {{
            font-family: {SERIF} !important;
            color: {PARCHMENT} !important;
        }}

        /* Quoted contract language should look quoted. */
        blockquote {{
            border-left: 2px solid {GOLD} !important;
            background: rgba(200,162,74,.05);
            padding: .55rem .9rem !important;
            font-family: {SERIF};
            color: {PARCHMENT} !important;
        }}

        code, pre, .stCode {{ font-family: 'SF Mono',Consolas,'Courier New',monospace; }}
        div[data-testid="stExpander"] {{
            border: 1px solid {INK_EDGE};
            border-radius: 3px;
            background: rgba(255,255,255,.015);
        }}
        hr {{ border-color: {INK_EDGE} !important; }}

        /* The modal is the case file opened on the desk. */
        div[data-testid="stDialog"] div[role="dialog"] {{
            background: {INK_RAISED};
            border: 1px solid {GOLD};
            border-radius: 5px;
        }}

        /* A thin gold rule under the page title, like a letterhead divider. */
        .cv-rule {{
            height: 2px;
            background: linear-gradient(90deg, {GOLD} 0%, rgba(200,162,74,.28) 42%, transparent 100%);
            margin: .1rem 0 1.1rem 0;
        }}
        .cv-firm {{
            font-size: 1.32rem;
            font-weight: 600;
            color: {GOLD};
            letter-spacing: .04em;
            margin: 0;
        }}
        .cv-firm-sub {{
            font-family: {SANS};
            font-size: .68rem;
            text-transform: uppercase;
            letter-spacing: .17em;
            color: {PARCHMENT_DIM};
            margin: .18rem 0 0 0;
        }}
        .cv-eyebrow {{
            font-family: {SANS};
            font-size: .68rem;
            text-transform: uppercase;
            letter-spacing: .17em;
            color: {GOLD};
            margin-bottom: .25rem;
        }}
        /* Live watcher status — a bordered pill at the very top of the page,
           matching the case-card surface. Only the "checking" state animates. */
        .cv-status {{
            display: inline-flex;
            align-items: center;
            gap: .55rem;
            font-family: {SANS};
            font-size: .95rem;
            font-weight: 600;
            letter-spacing: .02em;
            color: {PARCHMENT};
            background: {INK_RAISED};
            border: 1px solid {INK_EDGE};
            border-radius: 999px;
            padding: .5rem 1.05rem;
            margin: 0 0 1rem 0;
        }}
        .cv-status-dot {{
            width: .7rem;
            height: .7rem;
            border-radius: 50%;
            flex: 0 0 auto;
            display: inline-block;
        }}
        .cv-status-checking .cv-status-dot {{
            background: {STATUS_GREEN};
            animation: cv-breathe 2.2s ease-in-out infinite;
        }}
        .cv-status-idle .cv-status-dot {{ background: {GOLD}; }}
        .cv-status-stopped {{ color: {PARCHMENT_DIM}; }}
        .cv-status-stopped .cv-status-dot {{ background: {STATUS_GRAY}; }}
        @keyframes cv-breathe {{
            0%, 100% {{ box-shadow: 0 0 0 0 rgba(78,163,107,.55); opacity: 1; }}
            50%      {{ box-shadow: 0 0 .55rem .18rem rgba(78,163,107,.55); opacity: .72; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def case_rail(status: str) -> str:
    """The coloured left rail that gives a case card its status at a glance."""
    return STATUS_RAIL.get(status, INK_EDGE)

# "Section 14.1 (Environmental Indemnity)" -> "Environmental Indemnity"
SECTION_HEADING = re.compile(r"Section\s+[\d.]+\s*\(([^)]{3,60})\)")

# The agent writes free-form markdown. These pull the pieces we present
# separately. Every one of them has a fallback, so an unexpected shape
# degrades to showing the raw text rather than showing nothing.
POLICY_FACT = re.compile(r"Policy\s+(?:Fact|Document|Says)\b[^:\n]*:\**\s*(.+?)(?:\n|$)", re.I)
DRAFT_FACT = re.compile(r"Draft\s+(?:Fact|Document|Says)\b[^:\n]*:\**\s*(.+?)(?:\n|$)", re.I)
CONCLUSION = re.compile(r"Conclusion\b[^:\n]*:\**\s*(.+?)(?:\n\s*\n|$)", re.S | re.I)
# The heading the Writer puts above its proposed clause, in the many ways it
# actually phrases it. This started life matching only "Suggested replacement"
# and a real review caught the gap: the Writer wrote "Suggested revision to
# bring the clause into line with corporate policy:" and the case page said
# "the agent did not propose specific replacement wording" while a perfectly
# good redline sat two inches below in the memo. For a tool whose whole job is
# surfacing the proposed fix, silently hiding it is the worst kind of bug —
# so this matches the family of headings rather than one exact phrase.
#
# The ^ anchor (with re.M) is load-bearing, and widening this without it was a
# bug of its own: our own section label reads "Writer's proposed redline and
# escalation memo ... nothing has been applied:", which ends in a colon, so an
# unanchored pattern matched THAT and presented the banner line as the redline.
# A real heading starts its own line; a phrase buried mid-sentence does not.
# The leading class allows the markdown a heading may be dressed in (**bold**,
# # hashes, "1." numbering, "- " bullets) but nothing else.
SUGGESTED_REPLACEMENT = re.compile(
    r"^[ \t>*#\-\d.]*"
    r"(?:Suggested|Proposed|Recommended|Revised)\s+"
    r"(?:new\s+|revised\s+|replacement\s+)?"
    r"(?:replacement|revision|redline|wording|language|clause|text|version)"
    r"\b[^:\n]*:\**\s*(.+?)(?:\n\s*\n|\Z)",
    re.S | re.I | re.M,
)
RECOMMENDED_ACTION = re.compile(r"Recommended\s+Action\b[^:\n]*:\**\s*(.+?)(?:\n\s*\n|\Z)", re.S | re.I)

# The banner form of the same announcement: a line that says a redline follows,
# with no colon and no wording on it. Matched on its own so clause_under_banner()
# can walk forward to the actual clause. Note it must NOT be allowed to match
# our own "Writer's proposed redline and escalation memo ...:" section label, so
# the adjective has to start the line here too.
REDLINE_BANNER = re.compile(
    r"^[ \t>*#\-\d.]*"
    r"(?:PROPOSED|SUGGESTED|RECOMMENDED|REVISED)\s+"
    r"(?:REDLINE|REPLACEMENT|REVISION|WORDING|CLAUSE|LANGUAGE)"
    r"\b[^\n]*$",
    re.I | re.M,
)

# ----------------------------------------------------------------------------
# Reading the monitor's data (read-only)
# ----------------------------------------------------------------------------

def read_scan_log(log_file: str) -> list:
    """Reads scan_log.jsonl into a list of scan entries, newest first."""
    if not os.path.exists(log_file):
        return []
    entries = []
    with open(log_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip a half-written line rather than crash
    entries.reverse()  # newest first
    return entries


def latest_per_document(entries: list) -> list:
    """A document can be scanned more than once; keep only its newest scan."""
    seen = set()
    latest = []
    for entry in entries:  # already newest-first
        doc = entry.get("document")
        if doc in seen:
            continue
        seen.add(doc)
        latest.append(entry)
    return latest


def effective_status(entry: dict, approvals: dict) -> str:
    """
    A document's status is its scan status — UNLESS a human has since approved
    or rejected it. A recorded human decision always wins.
    """
    document = entry.get("document")
    if document in approvals:
        return approvals[document].get("status", "UNKNOWN")
    return entry.get("status", "UNKNOWN")


def read_text_file(path: str) -> str:
    """
    Reads a document for display, whatever format it is in.

    This goes through the same intake layer the agents use, so the case view
    quotes a PDF's real wording rather than showing binary noise — and so what
    the human reads is what the agent read. Returns "" if the document isn't
    available or can't be read, which the caller says plainly rather than
    crashing on.
    """
    return load_text_or_empty(path).strip()


def find_document_text(config: dict, document: str, entry: dict = None) -> str:
    """
    Finds a logged document and returns its text, or "" if we can't.

    An entry may name the file its text should come from (`source.text_document`,
    set for uploads), and that is trusted first — but only by BASENAME, looked up
    inside the uploads folder, so a value in the log can never point the viewer at
    an arbitrary file on disk.

    Otherwise the watched inbox is checked first, since that's where reviewed
    documents normally live, then the project folder, which is where the
    standalone real-document verification fixtures sit — they are reviewed by
    hand rather than dropped in the inbox, and their case view should still be
    able to quote them.
    """
    folders = [config["inbox_dir"], ROOT, config["uploads_dir"]]

    named = ((entry or {}).get("source") or {}).get("text_document")
    if named:
        text = read_text_file(os.path.join(config["uploads_dir"], os.path.basename(named)))
        if text:
            return text

    if not document:
        return ""
    for folder in folders:
        text = read_text_file(os.path.join(folder, document))
        if text:
            return text
    return ""


def policy_text_for(entry: dict, config: dict, default_policy_text: str) -> str:
    """
    The text of the commitment THIS entry was actually compared against.

    Inbox scans are all judged against the one policy named in config.json, so
    that's the default. An entry may also name its own `policy_document` — the
    real-document test does, because it deliberately uses a different, real
    published commitment — and in that case we show that document instead, so
    the case view never quotes a policy the agent didn't actually use.
    """
    named = (entry.get("policy_document") or "").strip()
    if not named:
        return default_policy_text
    return find_document_text(config, named) or default_policy_text

# ----------------------------------------------------------------------------
# Turning a filename into a readable case title
# ----------------------------------------------------------------------------

def matter_name(document: str) -> str:
    """
    "jv_pipeline_venture.txt" -> "Pipeline Venture JV"

    A filename is not a case name. This makes the label read like something a
    lawyer would put on a folder, while the exact filename stays visible
    underneath so nothing is obscured.
    """
    stem = os.path.splitext(document)[0]
    is_joint_venture = bool(re.match(r"^jv[_\-]", stem, re.I))
    stem = re.sub(r"^jv[_\-]", "", stem, flags=re.I)
    words = [w for w in re.split(r"[_\-\s]+", stem) if w]
    if not words:
        return "Unnamed Matter"
    name = " ".join(word.capitalize() for word in words)
    return f"{name} JV" if is_joint_venture else name


def case_title(document: str, source_text: str) -> str:
    """
    Builds a case title, preferring the document's own section heading as the
    subject: "Matter: Texas Refinery JV — Environmental Indemnity Review".

    Falls back to a generic subject when the document has no recognisable
    heading, or is no longer on disk.
    """
    name = matter_name(document)
    match = SECTION_HEADING.search(source_text or "")
    subject = match.group(1).strip() if match else ""
    if not subject:
        return f"Matter: {name} — Compliance Review"
    if subject.lower().endswith("review"):
        return f"Matter: {name} — {subject}"
    return f"Matter: {name} — {subject} Review"


def entry_case_title(entry: dict, source_text: str) -> str:
    """
    The case name shown for one log entry.

    Almost always this is worked out from the document itself (above). The one
    exception: an entry may carry its own `case_title`, and if it does we use
    it verbatim. That's how the real-document verification test labels its two
    cases as a proof-of-concept on published language rather than letting them
    read like live inbox reviews. Ordinary scans don't set the field, so they
    are titled exactly as before.
    """
    explicit = (entry.get("case_title") or "").strip()
    if explicit:
        return explicit
    return case_title(entry.get("document", ""), source_text)

# ----------------------------------------------------------------------------
# Pulling the readable pieces out of the agent's memo
# ----------------------------------------------------------------------------

def plain_text(markdown_text: str) -> str:
    """Strips light markdown so a fragment reads cleanly as a sentence."""
    text = (markdown_text or "").replace("‑", "-").replace("–", "-")
    text = re.sub(r"[*_`>#]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().strip("\"'“” ")


def first_sentences(text: str, limit: int = 2) -> str:
    """Keeps the first one or two sentences — enough to say what the issue is."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    kept = " ".join(parts[:limit]).strip()
    return kept


def plain_summary(entry: dict, analysis: str) -> str:
    """
    A one-or-two-sentence, plain-language statement of the issue — shown FIRST,
    so a human knows what they're looking at before reading any legal text.
    """
    if entry.get("contradiction_found") is False or entry.get("status") == "CLEAR":
        return (
            "No conflict found. This document's language is consistent with the "
            "company's public commitment, so there is nothing to action."
        )

    match = CONCLUSION.search(analysis or "")
    if match:
        return first_sentences(plain_text(match.group(1)), 2)

    # Fall back to the first real paragraph of the memo.
    for block in re.split(r"\n\s*\n", analysis or ""):
        cleaned = plain_text(block)
        if len(cleaned) > 40:
            return first_sentences(cleaned, 2)

    return "This document was flagged for review. See the full memo below."

def conflicting_language(analysis: str, policy_text: str, draft_text: str) -> tuple:
    """
    Returns (policy_says, draft_says) — the specific language on each side.

    Prefers the agent's own extracted "Policy Fact" / "Draft Fact" lines, since
    those are the passages it actually compared. Falls back to the source
    documents themselves so this panel is never empty.
    """
    policy_match = POLICY_FACT.search(analysis or "")
    draft_match = DRAFT_FACT.search(analysis or "")

    policy_says = plain_text(policy_match.group(1)) if policy_match else plain_text(policy_text)
    draft_says = plain_text(draft_match.group(1)) if draft_match else plain_text(draft_text)

    return (
        policy_says or "(The policy document could not be read.)",
        draft_says or "(The draft document could not be read.)",
    )


def clause_under_banner(analysis: str) -> str:
    """
    The proposed wording when the Writer announces it with a banner line rather
    than a "heading: wording" pair — e.g.

        **PROPOSED REDLINE (suggested wording - pending human approval)**

        *Section 14.1 (Environmental Indemnity):*
        > The parties agree that ... Scope 1, Scope 2, and Scope 3 emissions ...

    A pattern looking for "something: the wording" cannot see this, because the
    banner has no colon and the clause is a blockquote two lines below. This
    walks forward from the banner instead, throwing away the scaffolding
    (blockquote arrows, rules, and a bare "Section 14.1 (...):" label) and
    keeping the first real block of wording. Returns "" if it finds nothing it
    is confident about — an empty answer is better than a confident wrong one.
    """
    match = REDLINE_BANNER.search(analysis or "")
    if not match:
        return ""

    kept = []
    for raw in analysis[match.end():].splitlines():
        line = plain_text(raw.strip().lstrip(">").strip())
        if not line or set(line) <= set("-—_*= "):
            if kept:
                break       # a blank line or a rule closes the clause
            continue        # ...but leading spacing is not the end of anything
        if line.upper().startswith(("ESCALATION", "MEMO", "TO:", "FROM:", "SUBJECT:")):
            break           # we have run past the redline into the memo
        if not kept and line.endswith(":") and len(line) < 90:
            continue        # a label announcing the clause, not the clause
        kept.append(line)
    return " ".join(kept).strip()


def suggested_fix(analysis: str) -> str:
    """
    The proposed replacement wording, if the agent produced one. Returns "" when
    there is nothing to suggest, so the caller can say so plainly rather than
    render an empty box.

    Three passes, most precise first. The last one, "Recommended Action", is
    deliberately last: it usually reads like "adopt the redline above", which
    tells a reviewer to look at wording rather than showing it. Real wording
    wins over a pointer to wording every time.
    """
    explicit = SUGGESTED_REPLACEMENT.search(analysis or "")
    if explicit:
        # Keep it to the suggestion itself, not the rest of the memo.
        return plain_text(re.split(r"\n\s*\*\*", explicit.group(1).strip())[0])

    from_banner = clause_under_banner(analysis)
    if from_banner:
        return from_banner

    action = RECOMMENDED_ACTION.search(analysis or "")
    if action:
        return plain_text(re.split(r"\n\s*\*\*", action.group(1).strip())[0])

    return ""

def format_time(iso_string: str) -> str:
    """Turns a stored ISO timestamp into something human-friendly."""
    if not iso_string:
        return "an unknown time"
    try:
        return datetime.fromisoformat(iso_string).strftime("%d %b %Y, %H:%M UTC")
    except ValueError:
        return iso_string


def status_badge(status: str) -> str:
    """A compact coloured case status for quick scanning."""
    label, colour = CASE_STATUS.get(status, (status, "gray"))
    return f":{colour}[**● {label}**]"


# ----------------------------------------------------------------------------
# The case view — summary, the language on both sides, the fix, then a decision
# ----------------------------------------------------------------------------

def request_case_dismissal(document):
    """
    Asks for the open case to be closed, as an on_click callback.

    Two session keys, and both are needed for a reason worth writing down.

    "open_case" is CONSUMED where it is read, so by the time a click is being
    handled it is already gone. Re-setting it here keeps the case alive for
    exactly one more rerun. That one extra rerun is not decoration: Streamlit
    closes a modal only when st.rerun() is called from INSIDE the dialog
    function, so the dialog body has to execute once more in order to dismiss
    itself. "close_case_now" is the instruction to do exactly that and nothing
    else — see body() at the opened-case section.

    Skipping this and simply dropping the key looked like it worked and did not:
    the decision was recorded, but the modal stayed on screen frozen at its old
    content, still reading "Pending Review" over a case that had just been
    approved. A stale panel contradicting the record is worse than a stale panel.
    """
    st.session_state["open_case"] = document
    st.session_state["close_case_now"] = True


def decide_and_close(approvals_path, document, decision):
    """
    Records a human Approve/Reject, then closes the case, as an on_click callback.

    Recording the decision in a callback rather than inline is load-bearing.
    Callbacks fire BEFORE the script reruns, so the decision is written even
    though the case key was consumed on read and the button is not guaranteed to
    be redrawn. Handled inline against a consumed key, a click is silently
    dropped and a reviewer's decision is lost — the worst possible bug in the one
    place this tool has to be trustworthy.

    Still writes only to approvals.json. No contract is touched, as before.
    """
    record_decision(approvals_path, document, decision)
    request_case_dismissal(document)


def render_case_detail(entry, status, approvals, approvals_path, policy_text, draft_text):
    """
    The body of an opened case. Order is deliberate: a human should learn WHAT
    the issue is before being shown legal text, and should only reach the
    Approve / Reject buttons after seeing the evidence and the proposed fix.
    """
    document = entry.get("document", "(unknown)")
    analysis = entry.get("analysis") or ""
    source = entry.get("source") or {}
    is_clean = status == "CLEAR" or entry.get("contradiction_found") is False

    st.markdown(status_badge(status))
    st.caption(
        f"File on record: `{document}`  ·  Reviewed {format_time(entry.get('timestamp'))}"
        f"  ·  Analysis mode: {entry.get('mode', '?')}"
    )

    # Where the words under discussion came from. Only shown when there's
    # something to say — a plain .txt read cleanly needs no explanation, but a
    # PDF does, because a reviewer acting on a redline is entitled to know the
    # text was extracted from a scan and by what.
    if source.get("note"):
        st.caption(f"📄 Text source: {source['note']}")
    for warning in source.get("warnings", []):
        st.warning(f"**Part of this document was never read.** {warning}")

    # A document that couldn't be read has no verdict, so none of the panels
    # below would mean anything. Say so plainly and stop.
    if status == "COULD_NOT_READ":
        st.subheader("This document was not reviewed")
        st.error(source.get("note") or "No text could be extracted from this document.")
        st.write(
            "No AI review was run on it, so there is no verdict here — and "
            "nothing to approve. This case exists so the document can't be "
            "mistaken for one that was checked and found clean."
        )
        st.info(
            "**What to do:** supply a text-based copy (a PDF exported from the "
            "original, or a Word file). The background watcher will review the "
            "new version on its next pass, or file it yourself under "
            "**“File a document for review”** at the foot of the case list for an "
            "immediate review."
        )
        if analysis:
            with st.expander("Read the full intake note"):
                st.markdown(analysis)
        return

    st.subheader("What's the issue")
    st.write(plain_summary(entry, analysis))

    st.subheader("The language in question")
    policy_says, draft_says = conflicting_language(analysis, policy_text, draft_text)
    left, right = st.columns(2)
    with left:
        st.markdown("**The public commitment says**")
        st.info(policy_says)
    with right:
        st.markdown("**This draft says**")
        if is_clean:
            st.success(draft_says)
        else:
            st.error(draft_says)

    st.subheader("Suggested fix")
    if is_clean:
        st.write("No fix is needed — this draft honours the public commitment.")
    else:
        fix = suggested_fix(analysis)
        if fix:
            st.info(fix)
            st.caption(
                "⚠️ Proposed wording only. Nothing has been changed, and approving "
                "this does **not** edit the contract."
            )
        else:
            # Careful wording: we do not know that no fix was proposed, only
            # that we could not lift one cleanly out of free-form prose. Saying
            # "the agent proposed nothing" would be a claim about the review
            # itself, and if the pattern-matching is what failed, that claim is
            # simply false. Point at the memo instead.
            st.write(
                "No single replacement clause could be pulled out of this memo "
                "automatically. Read the full memo below — the agent's proposal, "
                "if it made one, is in there."
            )

    if analysis:
        with st.expander("Read the agent's full memo"):
            st.markdown(analysis)

    st.divider()

    if status == "PENDING_HUMAN_APPROVAL":
        st.caption(
            "Recording a decision here only notes **your** choice in the case "
            "file. It does not modify the contract."
        )
        approve, reject = st.columns(2)
        # on_click rather than "if button:" — see decide_and_close(). The decision
        # must be recorded by a callback, because the case key is consumed on read
        # and this button will not be redrawn on the next run to report its click.
        # No st.rerun() is needed either: a callback always triggers one.
        approve.button(
            "✅ Approve suggested fix",
            key=f"dlg_approve_{document}",
            use_container_width=True,
            on_click=decide_and_close,
            args=(approvals_path, document, "APPROVED"),
        )
        reject.button(
            "✋ Reject suggested fix",
            key=f"dlg_reject_{document}",
            use_container_width=True,
            on_click=decide_and_close,
            args=(approvals_path, document, "REJECTED"),
        )
    elif status in ("APPROVED", "REJECTED"):
        info = approvals.get(document, {})
        label = CASE_STATUS.get(status, (status, "gray"))[0]
        st.success(
            f"**{label}** by {info.get('decided_by', 'a human reviewer')} "
            f"on {format_time(info.get('decided_at'))}."
        )
        st.caption("No contract was modified by this decision.")
    elif is_clean:
        st.caption("No decision is required — no issues were found in this document.")
    else:
        st.caption(
            "No decision is recorded against this case: the agent did not reach a "
            "definite verdict. Read its reasoning above before acting on it."
        )

# ----------------------------------------------------------------------------
# Reviewing a document you upload, on demand
# ----------------------------------------------------------------------------

# Engines the upload panel offers, in the order shown. Wording is aimed at the
# person choosing, not at a developer.
ENGINE_CHOICES = {
    "sequential": (
        "Paced review (recommended)",
        "The three agents are called one at a time with a pause between them. "
        "Slower to watch — about a minute — but it stays inside a free API "
        "tier's per-minute limit, so a long contract completes.",
    ),
    "orchestrator": (
        "Full multi-agent review",
        "A lead Orchestrator agent decides for itself which specialist to call "
        "next. The same analysis, done in one large request — which on a free "
        "API tier can hit the per-minute token limit on a long contract.",
    ),
}


def precheck(uploaded) -> dict:
    """
    Reads the text out of a just-selected file WITHOUT reviewing it.

    This is what makes the scanned-document case cheap and immediate: the file is
    examined the moment it's chosen, so a scan with no text layer is reported
    before any AI is called and before anything is saved. The bytes go to a
    temporary file that is deleted straight away — the upload itself is only
    stored once the human actually asks for a review.

    The result is remembered for the session so it isn't recomputed every time
    Streamlit redraws the page.
    """
    import tempfile

    from document_intake import extract

    key = f"precheck::{uploaded.name}::{uploaded.size}"
    if key in st.session_state:
        return st.session_state[key]

    extension = os.path.splitext(uploaded.name)[1].lower()
    handle, temp_path = tempfile.mkstemp(suffix=extension or ".bin")
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(uploaded.getvalue())
        result = extract(temp_path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    st.session_state[key] = result
    return result


def render_upload_panel(config: dict):
    """
    The "hand me a contract and review it now" panel.

    It does no analysis itself — it hands the file to upload_review.py, which
    runs the same reader, the same three real agents and the same log writer the
    background watcher uses. The result becomes a case in the docket above, and
    a flagged one still waits for a human to approve or reject it.
    """
    from document_intake import describe

    # No heading here — render_upload_section supplies it, and it is the one
    # that carries the #file-a-document-for-review anchor the sidebar link
    # jumps to. Two headings would mean two anchors and a duplicated title.
    st.caption(
        "For a contract that's in front of you now, rather than one you drop in "
        "the watched folder and wait for. Accepted: "
        + ", ".join(SUPPORTED_EXTENSIONS)
        + ". The file is saved untouched and reviewed by the same agents."
    )

    uploaded = st.file_uploader(
        "Choose a contract or draft",
        type=[extension.lstrip(".") for extension in SUPPORTED_EXTENSIONS],
        key="upload_widget",
        label_visibility="collapsed",
    )

    if uploaded is None:
        return

    # No "clear the stale case here" step any more, deliberately. This panel used
    # to clear it when a different document was attached, which only ever fixed
    # attaching a document — the stale case still came back on a Refresh, on a
    # decision recorded elsewhere, or on any other rerun. The case key is now
    # consumed where it is read instead, which covers every trigger at once, so
    # duplicating a narrower version of that rule here would just be a second
    # mechanism to keep in sync.
    intake = precheck(uploaded)

    if not intake["ok"]:
        # The honest stop. Nothing was saved, no AI was called, and no case will
        # be filed — a scanned contract must never come back as a confident
        # review of an empty page.
        st.error(f"**This document can't be reviewed.** {intake['message']}")
        if intake["problem"] == "scanned":
            st.caption(
                f"Pages found: {intake['page_count']}  ·  pages containing "
                f"readable text: {intake['pages_with_text']}. Nothing was saved "
                "and no review was run. Reading text off page images needs OCR, "
                "which isn't built yet — export a text-based PDF from the "
                "original document, or supply a Word version, and it will "
                "review normally."
            )
        return

    st.success(f"Ready to review — {describe(intake)}")
    for warning in intake["warnings"]:
        st.warning(
            f"**Part of this document can't be read.** {warning} The review will "
            "go ahead on the text that could be extracted."
        )

    with st.expander("Preview the text that will be reviewed"):
        st.text(intake["text"][:3000] + ("\n\n[…truncated for preview]" if intake["chars"] > 3000 else ""))

    engine = st.radio(
        "How should it be reviewed?",
        options=list(ENGINE_CHOICES),
        format_func=lambda key: ENGINE_CHOICES[key][0],
        horizontal=True,
        key="upload_engine",
    )
    st.caption(ENGINE_CHOICES[engine][1])

    if not st.button("⚖️ Review this document", type="primary", key="run_upload_review"):
        return

    from upload_review import review_upload

    status_box = st.status("Starting the review...", expanded=True)

    def progress(message: str):
        status_box.write(message)
        status_box.update(label=message)

    try:
        outcome = review_upload(
            config,
            uploaded.name,
            uploaded.getvalue(),
            engine=engine,
            on_progress=progress,
        )
    except Exception as e:
        # Most likely an API rate limit or a missing key. Say what happened
        # rather than leaving a spinner turning; nothing was logged.
        status_box.update(label="The review could not be completed.", state="error")
        st.error(
            f"**The review didn't finish: {type(e).__name__}: {e}**\n\n"
            "No case was filed. If this was a rate limit, the paced review "
            "option handles long documents better on a free API tier."
        )
        return

    if not outcome["ok"]:
        status_box.update(label="This document could not be read.", state="error")
        st.error(f"**Not reviewed.** {outcome['message']}")
        return

    status_box.update(label="Review complete — the case is now on file.", state="complete")
    st.session_state["open_case"] = outcome["document"]
    st.rerun()


def render_upload_section(config: dict):
    """
    The filing section: the upload panel with a heading of its own, placed
    below the docket instead of above it.

    This is layout only. It exists so the panel can sit at the bottom of the
    page and still be reachable in one click from the sidebar: Streamlit turns
    a subheader into a page anchor, so "File a document for review" becomes
    #file-a-document-for-review, which is what the sidebar link points at. The
    review path itself is untouched — the same render_upload_panel, calling the
    same upload_review.review_upload, with the same human-approval rule.
    """
    st.markdown('<div class="cv-rule"></div>', unsafe_allow_html=True)
    st.markdown('<p class="cv-eyebrow">Filing</p>', unsafe_allow_html=True)
    st.subheader("File a document for review")
    with st.container(border=True, key="filingpanel"):
        render_upload_panel(config)


# ----------------------------------------------------------------------------
# Streamlit feature detection (so this still runs on an older install)
# ----------------------------------------------------------------------------

def supports_link_style_button() -> bool:
    """`type="tertiary"` renders a button as a text link. Added in Streamlit 1.39."""
    try:
        major, minor = (int(part) for part in st.__version__.split(".")[:2])
    except (ValueError, AttributeError):
        return False
    return (major, minor) >= (1, 39)


def open_case_button(label: str, key: str) -> bool:
    """The clickable case title. Falls back to a normal button on older versions."""
    if supports_link_style_button():
        return st.button(label, key=key, type="tertiary")
    return st.button(label, key=key)


def watcher_status(config: dict):
    """
    Reads monitor.py's heartbeat file and returns (state, text), where state is
    one of "checking" / "idle" / "stopped". Read-only: it never writes the file.
    "stopped" covers both a missing file and a stale one (older than ~2x the scan
    interval), since a watcher that died mid-cycle leaves a "checking" heartbeat
    that would otherwise look live forever.
    """
    heartbeat_path = os.path.join(
        os.path.dirname(config["log_file"]) or ".", "heartbeat.json"
    )
    try:
        with open(heartbeat_path) as f:
            beat = json.load(f)
        stamp = datetime.fromisoformat(beat["timestamp"])
    except (OSError, ValueError, KeyError):
        return "stopped", "Not currently running"

    interval = beat.get("scan_interval_seconds") or config.get("scan_interval_seconds", 30)
    age = (datetime.now(stamp.tzinfo) - stamp).total_seconds()

    if age > 2 * interval + 5:
        return "stopped", "Not currently running"
    if beat.get("status") == "checking":
        return "checking", "Checking now…"

    if age < 10:
        ago = "just now"
    elif age < 90:
        ago = f"{int(age)} seconds ago"
    else:
        ago = f"{int(age // 60)} min ago"
    return "idle", f"Last checked {ago}"


def render_watcher_badge(config: dict):
    """Draws the live-status pill at the top of the main content area."""
    state, text = watcher_status(config)
    st.markdown(
        f'<div class="cv-status cv-status-{state}">'
        f'<span class="cv-status-dot"></span>{text}</div>',
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------------------
# The app
# ----------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Covenant — Compliance Case File",
        page_icon="⚖️",
        layout="wide",
    )

    config = load_config()
    approvals_path = config["approvals_file"]

    inject_house_style()

    entries = read_scan_log(config["log_file"])
    documents = latest_per_document(entries)
    approvals = load_approvals(approvals_path)
    policy_text = read_text_file(config["policy_file"])

    with st.sidebar:
        st.markdown(
            '<p class="cv-firm">⚖️ COVENANT</p>'
            '<p class="cv-firm-sub">Compliance Enforcement</p>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="cv-rule"></div>', unsafe_allow_html=True)
        st.write(
            "Your side of the system: read what the agents found and decide what "
            "to do about it. Reviews happen in the background as documents arrive "
            "— or immediately, on a document you file for review."
        )
        st.divider()
        st.subheader("Commitment being enforced")
        st.code(os.path.basename(config["policy_file"]), language=None)
        st.subheader("Folder under watch")
        st.code(os.path.basename(config["inbox_dir"]) + "/", language=None)
        st.subheader("Documents readable")
        st.code("  ".join(SUPPORTED_EXTENSIONS), language=None)
        st.caption(
            "A scanned PDF with no text layer is reported as unreadable, not "
            "reviewed as if it were blank. OCR isn't built yet."
        )
        st.divider()
        # A second way into the upload panel. The panel itself now sits below the
        # case list, so this is the "I came here to file something" shortcut —
        # it jumps to the same section rather than duplicating it, because two
        # uploaders on one page would be two code paths to keep honest.
        st.markdown(
            f'<a href="#file-a-document-for-review" '
            f'style="display:block;text-align:center;padding:.5rem;'
            f'border:1px solid {GOLD};border-radius:3px;color:{GOLD};'
            f'text-decoration:none;font-size:.8rem;letter-spacing:.06em;'
            f'text-transform:uppercase;font-weight:600;">'
            f'File a document ↓</a>',
            unsafe_allow_html=True,
        )
        st.divider()
        st.info(
            "**Safety rule:** the agent only ever *proposes* fixes. Approving "
            "records **your** decision — it never edits a contract, and nothing "
            "is auto-applied."
        )

    render_watcher_badge(config)

    header, refresh = st.columns([5, 1])
    with header:
        st.markdown('<p class="cv-eyebrow">Internal · Privileged</p>', unsafe_allow_html=True)
        st.title("Compliance Case File")
    with refresh:
        st.write("")
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
    st.markdown('<div class="cv-rule"></div>', unsafe_allow_html=True)
    st.caption(
        "Every document the agents have reviewed, as an open matter. "
        "Click a case name to read it and record a decision."
    )

    if not documents:
        st.warning(
            "No matters on file yet. File a document below for an immediate "
            "review, or start the background monitor (`python monitor.py`) and it "
            "will review the watched inbox as documents arrive."
        )
        render_upload_section(config)
        return

    statuses = [effective_status(entry, approvals) for entry in documents]

    a, b, c, d = st.columns(4)
    a.metric("Matters on file", len(documents))
    b.metric("Pending Review", statuses.count("PENDING_HUMAN_APPROVAL"))
    c.metric("Approved", statuses.count("APPROVED"))
    d.metric("No Issues Found", statuses.count("CLEAR"))

    unreadable = statuses.count("COULD_NOT_READ")
    if unreadable:
        st.caption(
            f"⚠️ {unreadable} document(s) arrived that could not be read and were "
            "therefore **not** reviewed. They are listed below so they can't be "
            "mistaken for documents that came back clean."
        )

    st.divider()

    # One card per matter. The case NAME is the clickable thing — a lawyer opens
    # a case, they don't expand a row.
    st.subheader("Open matters")
    drafts = {}  # document -> its text, read once and reused by the case view

    for entry, status in zip(documents, statuses):
        document = entry.get("document", "(unknown)")
        draft_text = find_document_text(config, document, entry)
        drafts[document] = draft_text
        title = entry_case_title(entry, draft_text)

        # `key` is what makes the card stylable: Streamlit renders it as an
        # `st-key-...` CSS class. Sanitised because a key becomes part of a
        # class name, and a filename can contain dots and spaces.
        card_key = "casecard_" + re.sub(r"[^0-9a-zA-Z]+", "_", document)
        with st.container(border=True, key=card_key):
            # The status rail: a thin coloured edge that makes a card's state
            # readable before any text is. Purely decorative — the authoritative
            # status is still the badge, which comes from CASE_STATUS.
            st.markdown(
                f'<div style="height:3px;background:{case_rail(status)};'
                f'margin:-0.25rem 0 .6rem 0;border-radius:2px;"></div>',
                unsafe_allow_html=True,
            )
            # [5, 2] rather than [4, 1]: the longest badge ("Could Not Be Read")
            # wrapped onto three lines in the narrower column and made the card
            # look broken. Checked in the browser at 1180px.
            left, right = st.columns([5, 2])
            with left:
                if open_case_button(title, key=f"open_{document}"):
                    st.session_state["open_case"] = document
                    st.rerun()
                caption = f"File on record: `{document}`"
                source = entry.get("source") or {}
                if source.get("kind") == "upload":
                    caption += "  ·  uploaded for review"
                if source.get("format") and source["format"] != "plain text":
                    caption += f"  ·  {source['format']}"
                st.caption(caption)
            with right:
                st.markdown(status_badge(status))
                st.caption(format_time(entry.get("timestamp")))

    st.caption(
        "Reviews are proposals only. This page never edits a contract, never "
        "applies a redline, and never rewrites the agents' log — it records your "
        "decisions, and nothing else."
    )

    # The upload panel lives HERE, below the docket, not above it. Opening the
    # page should answer "what needs my attention?" first; filing a new document
    # is a deliberate act you scroll to, or reach by the sidebar link.
    render_upload_section(config)

    # ---- The opened case -----------------------------------------------------
    # NOTE the pop rather than get: the case key is CONSUMED here. A case is shown
    # for exactly the one rerun that asked for it, and anything that wants it to
    # stay open has to say so again.
    #
    # This is the fix for a real bug. Streamlit's built-in ✕ on a modal closes it
    # in the browser only — the server is never told — so a key that survives
    # until something explicitly clears it outlives a dialog the user believes
    # they closed, and the case pops back up on the next rerun. The first version
    # of this fix cleared the key when a new document was attached to the
    # uploader, which fixed the one path I had reproduced and left every other
    # trigger broken: the ✕ followed by a Refresh, by a decision on another card,
    # by st.rerun() anywhere, or by Rerun from Streamlit's own menu all brought
    # the stale case back. Consuming the key handles all of them at once, because
    # it stops asking "did something cancel this?" and instead requires a fresh
    # reason to show a case at all.
    #
    # The consequence to keep in mind when editing the case body: every widget in
    # there is redrawn only if the case is re-armed. That is why Approve, Reject
    # and Close do their work in on_click callbacks (callbacks run BEFORE the
    # rerun, so they always fire), and why any NEW widget added to the case body
    # that needs the case to stay open must set st.session_state["open_case"]
    # again in its own callback.
    open_document = st.session_state.pop("open_case", None)
    if not open_document:
        return

    entry = next((e for e in documents if e.get("document") == open_document), None)
    if entry is None:
        # The log changed underneath us (e.g. after a Refresh). Forget it.
        st.session_state.pop("open_case", None)
        return

    status = effective_status(entry, approvals)
    title = entry_case_title(entry, drafts.get(open_document, ""))

    def body():
        # The dismissal step, and it has to live HERE rather than in the callback
        # that asked for it. Streamlit closes a modal only when st.rerun() is
        # called from inside the dialog function, so a request to close is carried
        # over one rerun and spent here, before anything is drawn. Handle it first
        # and draw nothing: re-rendering a case we are in the middle of closing is
        # how a modal ends up frozen on stale content.
        if st.session_state.pop("close_case_now", False):
            st.session_state.pop("open_case", None)
            st.rerun()

        render_case_detail(
            entry,
            status,
            approvals,
            approvals_path,
            policy_text_for(entry, config, policy_text),
            drafts.get(open_document, ""),
        )
        # on_click, like Approve and Reject, so closing behaves identically
        # however it is triggered and never depends on this button being redrawn.
        st.button(
            "Close",
            key=f"close_{open_document}",
            on_click=request_case_dismissal,
            args=(open_document,),
        )

    if hasattr(st, "dialog"):
        # The decorator is applied fresh on each rerun so the modal's heading can
        # be this particular case's name rather than a fixed string.
        st.dialog(title, width="large")(body)()
    else:
        # Older Streamlit: no modal. Show the case view as a distinct bordered
        # panel above the list — deliberately NOT an expander, so it still reads
        # as opening a case rather than unfolding a row.
        st.divider()
        st.markdown(f"### {title}")
        with st.container(border=True):
            body()


if __name__ == "__main__":
    main()
