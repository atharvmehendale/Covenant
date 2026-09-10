"""
TEST DOCUMENT BUILDER — makes the real PDFs and Word files used to test intake.

The point of this file is that the PDF tests are honest. It would be easy to
"test PDF support" by feeding the system something that was never really a PDF.
Instead this builds genuine files on disk:

  jv_texas_refinery.pdf         a straight one-page conversion of the sample
                                clause in inbox/jv_texas_refinery.txt
  jv_texas_refinery_long.pdf    the SAME clause buried several pages into a
                                realistic multi-page agreement, which is how
                                this problem actually shows up — the narrowing
                                language is never on page 1
  jv_texas_refinery_scanned.pdf every page of the first PDF rendered to an
                                image and re-wrapped with NO text layer: a real
                                scanned document, of the kind an OCR-less
                                reader genuinely cannot read
  jv_pipeline_venture.docx      a Word version of a second sample clause, with
                                part of the terms in a table

Everything written here is synthetic. The boilerplate around the real sample
clause is filler written for this test and is not any company's contract.

Run it with:
    python make_test_documents.py

It writes into samples/ and overwrites what's there, so it is safe to re-run.
"""

import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(ROOT, "samples")

# A4, in PDF points, with a margin a legal document would actually use.
PAGE_WIDTH, PAGE_HEIGHT = 595, 842
MARGIN = 72
FONT_SIZE = 10.5
LEADING = 15.0
BODY_FONT = "helv"
BOLD_FONT = "hebo"


def read_sample(name: str) -> str:
    """Reads one of the project's existing .txt samples, whitespace tidied."""
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return " ".join(f.read().split())


# ----------------------------------------------------------------------------
# Laying text out over as many pages as it needs
# ----------------------------------------------------------------------------

def wrap(text: str, font: str, size: float, width: float) -> list:
    """Breaks a paragraph into lines that fit the given width."""
    import fitz

    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if fitz.get_text_length(candidate, fontname=font, fontsize=size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def ascii_safe(text: str) -> str:
    """
    Swaps typographic characters for plain ones.

    The base-14 PDF fonts used here can't encode an em dash or curly quotes, and
    silently substitute something odd for them. Since the point of these files
    is to test extraction, the text on the page should be exactly what we expect
    to read back out.
    """
    for fancy, plain in (("—", "-"), ("–", "-"), ("‑", "-"), ("“", '"'),
                         ("”", '"'), ("‘", "'"), ("’", "'"), (" ", " ")):
        text = text.replace(fancy, plain)
    return text


def write_pdf(path: str, blocks: list):
    """
    Writes a real PDF, flowing `blocks` across as many pages as they need.

    Each block is ("heading" | "body", text). Pagination is done by hand rather
    than with a single text box so the output is genuinely multi-page — which is
    the thing the extraction code has to get right.
    """
    import fitz

    document = fitz.open()
    usable_width = PAGE_WIDTH - 2 * MARGIN
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    y = MARGIN

    def new_page():
        nonlocal page, y
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        y = MARGIN

    for kind, text in blocks:
        font = BOLD_FONT if kind == "heading" else BODY_FONT
        size = FONT_SIZE + (1 if kind == "heading" else 0)
        lines = wrap(ascii_safe(text), font, size, usable_width)

        if kind == "heading" and y > MARGIN:
            y += LEADING * 0.6  # a little air above a heading

        for line in lines:
            if y + LEADING > PAGE_HEIGHT - MARGIN:
                new_page()
            page.insert_text((MARGIN, y), line, fontname=font, fontsize=size)
            y += LEADING
        y += LEADING * 0.5  # paragraph spacing

    # Page numbers, because a real agreement has them — and because they give
    # the "some pages have text" logic something realistic to chew on.
    total = document.page_count
    for index, each in enumerate(document, start=1):
        each.insert_text(
            (PAGE_WIDTH / 2 - 30, PAGE_HEIGHT - MARGIN / 2),
            f"Page {index} of {total}",
            fontname=BODY_FONT,
            fontsize=8,
        )

    document.save(path)
    document.close()
    return total


def write_scanned_pdf(source_pdf: str, path: str, dpi: int = 150):
    """
    Turns a normal PDF into a genuinely scanned-looking one.

    Every page is rendered to a bitmap and placed into a fresh PDF as an image.
    The result has no text layer at all — exactly like a contract that went
    through a photocopier in 2004 — so it is a real test of the no-extractable-
    text path rather than a simulated one.

    The images are JPEG-compressed, which is what a real scanner produces, and
    keeps the fixture small enough to live in the repository.
    """
    import fitz

    source = fitz.open(source_pdf)
    scanned = fitz.open()
    for page in source:
        pixmap = page.get_pixmap(dpi=dpi)
        target = scanned.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, stream=pixmap.tobytes("jpeg", jpg_quality=55))
    scanned.save(path)
    pages = scanned.page_count
    scanned.close()
    source.close()
    return pages


# ----------------------------------------------------------------------------
# The documents themselves
# ----------------------------------------------------------------------------

FILLER_PREAMBLE = [
    ("heading", "SYNTHETIC TEST DOCUMENT"),
    ("body",
     "This agreement is filler written solely to test document handling. Only "
     "the clause reproduced under Article XIV is taken from this project's "
     "existing sample contract; everything else on these pages is invented "
     "boilerplate and does not describe any real company or transaction."),
    ("heading", "JOINT VENTURE AND OPERATING AGREEMENT"),
    ("body",
     "This Joint Venture and Operating Agreement (this \"Agreement\") is entered "
     "into between the parties identified in Schedule A (each a \"Party\" and "
     "together the \"Parties\") in respect of the refining and processing "
     "venture described in Schedule B (the \"Venture\")."),
    ("heading", "ARTICLE I — DEFINITIONS AND INTERPRETATION"),
    ("body",
     "1.1 In this Agreement, capitalised terms have the meanings given to them "
     "where they first appear, and any term not otherwise defined has the "
     "meaning customarily given to it in the industry in which the Venture "
     "operates. References to an Article or Section are references to an "
     "Article or Section of this Agreement."),
    ("body",
     "1.2 The headings in this Agreement are inserted for convenience only and "
     "do not affect its construction. Words importing the singular include the "
     "plural and vice versa, and words importing one gender include every "
     "gender."),
    ("heading", "ARTICLE II — FORMATION AND PURPOSE"),
    ("body",
     "2.1 The Parties agree to associate for the limited purpose of developing, "
     "financing, constructing and operating the Venture, and for no other "
     "purpose. Nothing in this Agreement constitutes either Party the agent of "
     "the other, save as expressly provided."),
    ("body",
     "2.2 Each Party shall contribute the capital, assets and personnel set out "
     "against its name in Schedule C, at the times and in the proportions there "
     "stated, and shall keep the other Party informed of any material change in "
     "its ability to do so."),
    ("heading", "ARTICLE III — GOVERNANCE"),
    ("body",
     "3.1 The Venture shall be managed by a Management Committee comprising an "
     "equal number of representatives appointed by each Party. The Management "
     "Committee shall meet not less than quarterly and shall keep minutes of "
     "its proceedings."),
    ("body",
     "3.2 Reserved Matters listed in Schedule D require the unanimous approval "
     "of the Management Committee. All other matters may be decided by simple "
     "majority, and in the event of deadlock the escalation procedure in "
     "Article XX applies."),
    ("heading", "ARTICLE IV — OPERATING STANDARDS"),
    ("body",
     "4.1 The Venture shall be operated in accordance with good industry "
     "practice, all applicable law, and the operating manual adopted by the "
     "Management Committee from time to time."),
    ("body",
     "4.2 Each Party shall procure that its personnel seconded to the Venture "
     "observe the health, safety and environmental standards adopted under "
     "Section 4.1, and shall promptly report any material breach of them to the "
     "Management Committee."),
    ("heading", "ARTICLE V — FINANCIAL PROVISIONS"),
    ("body",
     "5.1 The Venture shall maintain books and records in accordance with the "
     "accounting policies set out in Schedule E, and shall deliver audited "
     "accounts to each Party within ninety days of each financial year end."),
    ("body",
     "5.2 Distributions shall be made in the proportions set out in Schedule C, "
     "after provision for working capital, committed capital expenditure and "
     "any reserve the Management Committee reasonably determines."),
    ("heading", "ARTICLE VI — REPORTING AND DISCLOSURE"),
    ("body",
     "6.1 Each Party shall provide the other with such information concerning "
     "the Venture as it may reasonably require in order to comply with its own "
     "statutory, regulatory and listing obligations."),
    ("body",
     "6.2 Neither Party shall make any public statement concerning the Venture "
     "without the prior written consent of the other, except where disclosure "
     "is required by law or by a competent regulator."),
]

FILLER_TAIL = [
    ("heading", "ARTICLE XV — TERM AND TERMINATION"),
    ("body",
     "15.1 This Agreement takes effect on the date of the last signature and "
     "continues until terminated in accordance with this Article, or until the "
     "Venture is wound up under Article XVIII."),
    ("heading", "ARTICLE XVI — GENERAL"),
    ("body",
     "16.1 This Agreement constitutes the entire agreement between the Parties "
     "in relation to its subject matter and supersedes all prior negotiations "
     "and understandings, whether written or oral."),
    ("body",
     "16.2 No variation of this Agreement is effective unless it is in writing "
     "and signed by an authorised representative of each Party."),
]


def build_short_pdf() -> str:
    """A faithful one-page PDF of the sample clause — nothing added, nothing lost."""
    clause = read_sample(os.path.join("inbox", "jv_texas_refinery.txt"))
    path = os.path.join(SAMPLES, "jv_texas_refinery.pdf")
    blocks = [
        ("heading", "JOINT VENTURE AGREEMENT - EXTRACT (SYNTHETIC TEST DOCUMENT)"),
        ("body", clause),
    ]
    pages = write_pdf(path, blocks)
    print(f"  wrote {os.path.basename(path)}  ({pages} page)")
    return path


def build_long_pdf() -> str:
    """
    The realistic case: the same narrowing clause, several pages in.

    This is the test that matters for multi-page handling. If extraction only
    read page one, the clause that has to be caught would never be seen.
    """
    clause = read_sample(os.path.join("inbox", "jv_texas_refinery.txt"))
    path = os.path.join(SAMPLES, "jv_texas_refinery_long.pdf")
    blocks = (
        FILLER_PREAMBLE
        + [
            ("heading", "ARTICLE XIV — ENVIRONMENTAL MATTERS"),
            ("body", clause),
        ]
        + FILLER_TAIL
    )
    pages = write_pdf(path, blocks)
    print(f"  wrote {os.path.basename(path)}  ({pages} pages, clause is NOT on page 1)")
    return path


# Clause bodies used to pad an agreement out to a genuinely realistic length.
# Deliberately dull, and deliberately about subjects the agent is NOT looking
# for: the point of a long-document test is that the one clause that matters is
# surrounded by pages of plausible contract prose competing for attention.
FILLER_CLAUSES = [
    "Each Party shall at its own cost obtain and maintain in force all consents, "
    "licences and permits required for the performance of its obligations, and "
    "shall provide copies to the other Party promptly on request.",
    "Neither Party shall assign, novate or otherwise transfer any of its rights "
    "or obligations under this Agreement without the prior written consent of "
    "the other Party, such consent not to be unreasonably withheld or delayed.",
    "Any notice given under this Agreement shall be in writing and shall be "
    "delivered by hand, by prepaid recorded delivery, or by electronic mail to "
    "the address most recently notified in writing by the receiving Party.",
    "The Parties shall keep confidential all information disclosed by the other "
    "in connection with the Venture, save for information which is or becomes "
    "public through no breach of this Agreement or which must be disclosed by law.",
    "Each Party warrants that it has full power and authority to enter into this "
    "Agreement and that doing so does not conflict with any other obligation, "
    "instrument or arrangement to which it is a party.",
    "The Venture shall maintain insurance with reputable insurers on terms "
    "consistent with good industry practice, and shall name each Party as an "
    "additional insured to the extent that its interest requires.",
    "No delay or failure by either Party in exercising any right under this "
    "Agreement operates as a waiver of that right, and no single exercise of any "
    "right precludes any further exercise of it.",
    "If any provision of this Agreement is held to be invalid or unenforceable, "
    "that provision shall be severed and the remainder shall continue in full "
    "force, provided the commercial intent of the Parties is preserved.",
    "The Parties shall review the operating budget annually and shall agree any "
    "variation in writing, failing which the previous budget continues to apply "
    "adjusted for inflation by reference to the index named in Schedule E.",
    "Each Party shall comply with all applicable anti-bribery, sanctions and "
    "anti-money-laundering laws, and shall maintain records sufficient to "
    "demonstrate that compliance for a period of not less than six years.",
]


def filler_articles(start_number: int, count: int) -> list:
    """
    Generates `count` numbered articles of ordinary contract prose.

    Used to pad a test agreement out to a realistic page count. Numbering
    continues from `start_number` so the finished document reads as one
    coherently numbered agreement rather than obvious repetition.
    """
    topics = [
        "CONSENTS AND AUTHORISATIONS", "ASSIGNMENT", "NOTICES", "CONFIDENTIALITY",
        "REPRESENTATIONS AND WARRANTIES", "INSURANCE", "WAIVER", "SEVERANCE",
        "BUDGETS AND VARIATION", "REGULATORY COMPLIANCE", "BOOKS AND RECORDS",
        "AUDIT RIGHTS", "SUBCONTRACTING", "FORCE MAJEURE", "DISPUTE RESOLUTION",
        "GOVERNING LAW", "COSTS AND EXPENSES", "FURTHER ASSURANCE",
        "THIRD PARTY RIGHTS", "COUNTERPARTS",
    ]
    roman = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
             "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
             "XXI", "XXII", "XXIII", "XXIV", "XXV", "XXVI", "XXVII", "XXVIII",
             "XXIX", "XXX", "XXXI", "XXXII", "XXXIII", "XXXIV", "XXXV"]

    blocks = []
    for index in range(count):
        number = start_number + index
        topic = topics[index % len(topics)]
        blocks.append(("heading", f"ARTICLE {roman[(number - 1) % len(roman)]} - {topic}"))
        for sub in range(1, 4):
            clause = FILLER_CLAUSES[(index * 3 + sub) % len(FILLER_CLAUSES)]
            blocks.append(("body", f"{number}.{sub} {clause}"))
    return blocks


def build_realistic_pdf() -> str:
    """
    A contract of the length a real one actually is, with the clause buried in it.

    The existing "long" fixture is two pages. That proved multi-page extraction
    worked, but it is not the document a compliance team would hand this thing —
    a joint venture agreement runs tens of pages, and the clause that matters is
    one paragraph somewhere in the middle. This builds that: dozens of numbered
    articles of ordinary contract prose with the narrowing environmental clause
    sitting well past the halfway point, so both the extraction AND the agents
    are tested at a size that resembles the real job.
    """
    clause = read_sample(os.path.join("inbox", "jv_texas_refinery.txt"))
    path = os.path.join(SAMPLES, "jv_texas_refinery_full.pdf")
    blocks = (
        FILLER_PREAMBLE
        + filler_articles(start_number=7, count=14)
        + [
            ("heading", "ARTICLE XXI - ENVIRONMENTAL MATTERS"),
            ("body", clause),
        ]
        + filler_articles(start_number=22, count=12)
        + FILLER_TAIL
    )
    pages = write_pdf(path, blocks)
    print(f"  wrote {os.path.basename(path)}  ({pages} pages, full-length agreement)")
    return path


def build_scanned_pdf(source_pdf: str) -> str:
    """The failure case, built for real: images of pages, no text layer."""
    path = os.path.join(SAMPLES, "jv_texas_refinery_scanned.pdf")
    pages = write_scanned_pdf(source_pdf, path)
    print(f"  wrote {os.path.basename(path)}  ({pages} page, image only — no text layer)")
    return path


def build_docx() -> str:
    """A Word version of a second sample clause, with terms split into a table."""
    import docx

    clause = read_sample(os.path.join("inbox", "jv_pipeline_venture.txt"))
    path = os.path.join(SAMPLES, "jv_pipeline_venture.docx")

    document = docx.Document()
    document.add_heading("PIPELINE VENTURE AGREEMENT — EXTRACT", level=1)
    document.add_paragraph(
        "Synthetic test document. Only the clause below is taken from this "
        "project's existing sample contract; the surrounding material is filler."
    )
    document.add_paragraph(clause)

    document.add_heading("Schedule 1 — Reporting Matrix", level=2)
    table = document.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    header = table.rows[0].cells
    header[0].text = "Emissions category"
    header[1].text = "Treatment under this Agreement"
    for category, treatment in [
        ("Scope 1 (direct)", "Reported quarterly to the Management Committee."),
        ("Scope 2 (purchased energy)", "Reported quarterly to the Management Committee."),
        ("Scope 3 (downstream)", "Not reported. No accountability requirement."),
    ]:
        row = table.add_row().cells
        row[0].text = category
        row[1].text = treatment

    document.save(path)
    print(f"  wrote {os.path.basename(path)}  (Word document, includes a table)")
    return path


def main():
    os.makedirs(SAMPLES, exist_ok=True)
    print(f"Building real test documents in {SAMPLES}\n")

    short_pdf = build_short_pdf()
    build_long_pdf()
    build_realistic_pdf()
    build_scanned_pdf(short_pdf)
    try:
        build_docx()
    except ImportError:
        print("  skipped the Word document (pip install python-docx to build it)")

    print("\nDone. Try them with:")
    print("  python document_intake.py samples/jv_texas_refinery_long.pdf")
    print("  python document_intake.py samples/jv_texas_refinery_scanned.pdf")


if __name__ == "__main__":
    main()
