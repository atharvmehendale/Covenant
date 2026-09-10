# Covenant — Compliance Enforcer Agent

**An AI agent that catches contracts quietly promising *less* than a company's public commitments — then drafts the fix, but never signs it for you.**

Built for the AWS **"Agents for Humans"** hackathon (Professional Agents track) using the **[Strands Agents SDK](https://strandsagents.com)**.

---

## The problem it solves

A company makes a bold public promise — say, *"carbon negative across Scope 1, 2, and 3 by 2030."* Months later, a 40-page supplier contract crosses a lawyer's desk. Buried in Section 7.2, one clause quietly redefines "carbon negative" to mean **Scope 1 and 2 only**, silently dropping Scope 3 — the largest chunk. Nobody's lying outright; the language just *narrows*. It's the kind of thing that's easy to miss and expensive to sign.

**Covenant reads both documents and catches exactly this.** It compares a company's public policy against an incoming draft, uses real AI reasoning to judge whether the draft walks back a public commitment, and — if it does — writes a proposed redline and a plain-English escalation memo for a human compliance officer.

### Four guarantees, by design

1. **It never auto-applies a fix.** Every suggested redline is marked *pending human approval*. The agent proposes; a human decides. It never edits a real contract.
2. **It stays silent when a document is clean.** It runs as a background inbox watcher and only speaks up when there's a genuine problem — no noise, no false alarms on honest drafts.
3. **It uses genuine AI reasoning, not keyword matching.** The judgment about whether a draft "narrows" a commitment is made by an AI reasoning model, so it works on real-world legal language, not just documents written to trip a rule. It is also **not tied to one subject** — the same agents, with the same prompts and no code changes, have been verified on real published *climate* wording and real published *data-privacy* wording (see [the real-document tests](#4-the-real-document-tests-proof-it-works-on-genuine-language)).
4. **It says so when it cannot read a document.** Real contracts arrive as PDFs and Word files, and some PDFs are scans with no text in them at all. Those are reported as **unreadable and not reviewed** — never passed to the AI as an empty document, which would produce a confident review of nothing. A silent false "no issues found" is the most dangerous output a compliance tool can give, so this case is handled explicitly rather than left to chance.

---

## The canonical example

- **Public commitment** (`real_policy_meridian.txt`): *"…committing to becoming carbon negative for 2030 for all three scopes… we will reduce our Scope 3 emissions by more than half by 2030."*
- **Narrowing draft** (`test_draft_meridian_narrowing.txt`): *"'Carbon Negative Operations' shall be defined exclusively as… Scope 1 and Scope 2… Scope 3 emissions… are expressly excluded."*

→ The agent **flags** it, quotes both sides, and drafts a redline restoring Scope 3 plus an escalation memo.

- **Clean draft** (`test_draft_meridian_clean.txt`): honors Scope 1, 2, **and** 3.

→ The agent **stays silent**. No memo, no redline.

> The commitment language above is real, published corporate climate wording, reproduced verbatim under the fictional name **"Meridian Industries."** The two draft contracts are fabricated hypotheticals written only for testing — they are not associated with any real company. (See the source note inside `real_policy_meridian.txt`.)

---

## How it works — the architecture

Covenant is a **multi-agent system**: instead of one AI trying to do everything, the work is split across three specialists, coordinated by a fourth.

```
                        ┌─────────────────────────────┐
   New draft lands  ──▶ │        ORCHESTRATOR         │   (decides who to call, and when)
   in the inbox         │  "review this draft against │
                        │   this policy"              │
                        └──────────────┬──────────────┘
                                       │ hands its team out as TOOLS
                 ┌─────────────────────┼─────────────────────┐
                 ▼                     ▼                     ▼
          ┌────────────┐       ┌──────────────┐      ┌──────────────┐
          │   READER   │       │   REASONER   │      │    WRITER    │
          │ extracts   │  ──▶  │ judges: does │  ──▶ │ drafts the   │
          │ the facts  │       │ the draft    │      │ redline +    │
          │ from each  │       │ contradict   │      │ escalation   │
          │ document   │       │ the policy?  │      │ memo         │
          └────────────┘       └──────────────┘      └──────────────┘
                                                     (skipped if the
                                                      draft is clean)
```

- **Reader** (`reader_agent.py`) — reads a document and extracts the relevant commitments and definitions. It only reads; it never judges.
- **Reasoner** (`reasoner_agent.py`) — takes the Reader's extractions from both documents and decides whether the draft quietly drops, narrows, or redefines something the policy promised. This is the hard reasoning step, deliberately kept separate.
- **Writer** (`writer_agent.py`) — only runs if the Reasoner found a problem. Turns the verdict into a proposed redline and a compliance-officer memo, always framed as *pending approval*.
- **Orchestrator** (`orchestrator.py`) — the multi-agent centerpiece. It's a top-level agent handed the Reader, Reasoner, and Writer **as tools**, and it decides on its own to call them in the right order. It ends every review with a machine-readable `VERDICT: CONTRADICTION | NO_CONTRADICTION` line that the rest of the system parses into a reliable flag.

Supporting pieces:

- **`model_provider.py`** — one place that supplies the AI model to every agent. Switch the AI provider by changing a single `PROVIDER` line (Groq by default; Featherless, Anthropic, or Amazon Bedrock also wired up). Also holds `call_with_retry()`, which waits out free-tier rate limits instead of crashing.
- **`monitor.py`** — the background worker. It watches the inbox folder and reviews only genuinely new documents, remembering what it's already seen in `processed_files.json`. It tracks each document by a **SHA-256 fingerprint of its contents**, not just its filename — so if a draft is edited and resaved under the same name (exactly how contract negotiation works), the new revision is detected and reviewed again. It logs each result to `scan_log.jsonl` and stays quiet on clean documents.
- **`dashboard.py`** — a Streamlit **case file** for the human reviewer. Each reviewed document is presented as a legal matter with a readable title derived from its own section heading (*"Matter: Pipeline Venture JV — Reporting Scope Review"*), not a raw filename, and a law-firm status: **No Issues Found**, **Pending Review**, **Approved**, or **Rejected**. Clicking a case name opens it: a plain-language summary of the issue first, then the conflicting language from both documents side by side, then the suggested fix, then **Approve / Reject** at the bottom. Decisions are recorded to `approvals.json`. It is strictly read-only otherwise — it never scans a document, never edits a contract, and never alters the scan log.
- **`document_intake.py`** — the one place any document becomes text, whichever route it arrives by. It reads **PDF** (pypdf, falling back to pdfplumber), **Word** (python-docx, including text inside tables), and **plain text** (trying several encodings). Crucially, it decides *whether a document is readable at all* and refuses to return an empty string pretending to be a contract: a scanned PDF comes back as **unreadable** with a plain explanation, and a PDF where only some pages carry text comes back readable **with a warning naming the pages that were never read**. Every other module reads documents through this, so there is no second, sloppier reader anywhere.
- **`upload_review.py`** — the on-demand path behind the dashboard's upload button. It saves the file untouched, reads it through `document_intake`, runs the same real agents, and files the case with the same `log_result()` the watcher uses. No shortcut path, no separate logic, and it never touches `approvals.json`.
- **`contradiction_checker.py` + `redline_drafter.py`** — a deterministic, rule-based fallback. It doubles as the offline test baseline and as a safety net if the AI verdict is ever missing.

A rendered architecture diagram is in [`Documentation/architecture_diagram.svg`](Documentation/architecture_diagram.svg).

---

## Setup (from scratch)

```bash
git clone https://github.com/<your-username>/<your-repo>.git
```

```bash
cd <your-repo>
```

**1. Prerequisites**

- Python 3.10+ (developed on 3.14, Windows 11).
- A free Groq API key — sign up at <https://console.groq.com> (no credit card required).

**2. Install the dependencies**

The simplest route — the exact versions this project was built and tested against:

```bash
pip install -r requirements.txt
```

Or by name, if you'd rather have the newest of each:

```bash
pip install "strands-agents[litellm]" streamlit pypdf pdfplumber python-docx pymupdf
```

*(If your Strands version doesn't expose the `litellm` extra, `pip install strands-agents litellm streamlit pypdf pdfplumber python-docx pymupdf` works the same way.)*

**pypdf** extracts PDF text, **pdfplumber** is the fallback for PDFs pypdf struggles with, and **python-docx** reads Word files. Plain `.txt` needs none of them, so the agent still runs if they're missing — it just reports PDFs and Word files as unreadable and says which library to install. **pymupdf** is used only by `make_test_documents.py`, which builds the sample PDFs the offline test suite reads — but don't skip it: without it, nine of the seventeen document-reading tests in [step 6](#6-the-document-reading-tests) cannot run.

There is also a smaller `requirements-scan.txt` — the subset a headless scan needs, with no dashboard and no fixture builder. That is what the scheduled GitHub Actions run installs.

**3. Set your API key as an environment variable**

The agent reads the key from the environment — it is never hardcoded or committed.

Windows (PowerShell), for the current session:

```bash
$env:GROQ_API_KEY = "your-groq-key-here"
```

macOS / Linux (bash/zsh):

```bash
export GROQ_API_KEY="your-groq-key-here"
```

To set it permanently on Windows so you don't repeat it each session:

```bash
setx GROQ_API_KEY "your-groq-key-here"
```

*(After `setx`, open a new terminal so the change takes effect.)*

---

## Running it

### 1. The background watcher (the actual product)

Starts Covenant watching the `inbox/` folder. Drop a draft into `inbox/` — **`.pdf`, `.docx`, or `.txt`** — and it gets reviewed automatically. Clean docs pass silently; problems are flagged with a memo.

```bash
python monitor.py
```

Press **Ctrl+C** to stop.

**On a fresh clone, this first run deliberately reviews nothing — that is correct behaviour, not a broken install.** The sample drafts in `inbox/` have already been reviewed; their results are the cases waiting for you on the dashboard, and `processed_files.json` (committed, because the scheduled cloud scan needs it as the agent's memory) records that they are done. The watcher only reviews a document that is new *or* has changed since it was last seen, so it correctly finds nothing to do and waits quietly.

To see it review something live, drop any `.pdf`, `.docx` or `.txt` draft into `inbox/` while it is running. To re-review the shipped samples from scratch instead, delete `processed_files.json` and start it again — every document in `inbox/` then looks new. (Bear in mind that spends a real AI call per document.)

If a PDF turns out to be a scan with no extractable text, the watcher does **not** review it and does **not** skip it quietly either — it files it as unreadable, with the reason, so it shows up on the dashboard as a document that still needs a human to look at.

### 2. The approvals dashboard

Opens the case file in a browser (at <http://localhost:8501>) — every reviewed document as a clickable matter, with Approve / Reject on anything flagged.

```bash
python -m streamlit run dashboard.py
```

### 3. Upload a contract and review it on the spot

The dashboard's **Review a new document** panel takes a **PDF, Word, or text** file and reviews it immediately — no waiting for the next background scan. This is the pattern real tools in this space use, and it sits alongside the watcher rather than replacing it.

What happens when you upload:

1. The file is saved, byte-for-byte unchanged, into `uploads/`. The original is never modified.
2. Text is extracted through `document_intake.py`. You are told which library read it and how many characters came out — and if only some pages had text, exactly which pages were skipped.
3. If nothing could be extracted, the review **does not start**. You get a plain message that the PDF appears to be scanned or image-based and that OCR isn't built yet. The Review button doesn't even appear, so an unreadable document can never burn an AI call or produce a fake all-clear.
4. Otherwise it runs the **same real agents** as everything else and is logged with the same `log_result()` — so it appears on the dashboard as a proper case, indistinguishable in handling from a watcher find, and still needs a human **Approve / Reject**.

The same thing from the command line, if you'd rather not use the browser:

```bash
python upload_review.py samples/jv_texas_refinery.pdf
```

```bash
python upload_review.py samples/jv_pipeline_venture.docx sequential
```

The optional second argument picks the engine: `sequential` (default — the paced fixed-order path that fits the free tier) or `orchestrator` (the full multi-agent path).

### 4. The real-document tests (proof it works on genuine language)

Runs the real AI agents against genuine, published corporate commitment wording and hypothetical draft clauses — one that narrows the commitment, one that honors it. There are **two suites, in two unrelated domains**, and they run through the same agents with the same prompts and no code changes:

| Suite | Real commitment | Fictional name | Narrowing draft gives away… |
|---|---|---|---|
| `emissions` | *"…carbon negative for 2030 for all three scopes."* | Meridian Industries | Scope 3 emissions |
| `privacy` | *"…does not sell, rent or monetize your personal data or content in any way – ever."* | Quillhaven Communications | the no-monetization promise, to "trusted commercial partners" |

That second suite is the point: the agent isn't tuned to emissions vocabulary. The same Reasoner that catches a dropped emissions scope catches a privacy promise being sold off.

Each case is recorded to the scan log, so all four show up on the dashboard as their own matters — *"Matter: Quillhaven Communications — Data Privacy Commitment Verification (Narrowing Case)"*, and so on. The titles say plainly that these are a proof of concept on real published language, not a live compliance review. The tests append only; they never touch `approvals.json` and never alter an existing log entry.

```bash
python run_real_document_test.py
```

You can narrow it down by suite or by case — recommended on the free tier, since the whole per-minute token budget then goes to one case (see the limitation below):

```bash
python run_real_document_test.py privacy
```

```bash
python run_real_document_test.py privacy narrowing
```

```bash
python run_real_document_test.py narrowing
```

### 5. The deterministic baseline test

Runs the rule-based checker with no API calls at all — fast, offline confirmation that the core contradiction logic works.

```bash
python test_contradiction_checker.py
```

### 6. The document-reading tests

Seventeen offline checks on the intake layer — also no API calls. They cover real multi-page PDFs, Word files with tables, odd text encodings, empty and corrupt files, oversized uploads, the **scanned-PDF** case, and the partly-scanned case where only some pages carry text. These are the tests that prove an unreadable document is reported rather than reviewed.

```bash
python test_document_intake.py
```

The PDF and Word fixtures they need are generated from the sample contracts:

```bash
python make_test_documents.py
```

### 7. The scheduled scan (the same watcher, on a timer, in the cloud)

`monitor.py` is the right shape for a machine you leave switched on. If you'd rather not leave one on, `.github/workflows/scan.yml` runs the **same scanning logic** on GitHub's servers on a timer: GitHub starts a temporary machine, runs one pass over `inbox/`, commits what it found back into the repo, and shuts down.

The one-pass version is a separate script — `monitor.py` is untouched:

```bash
python scan_once.py
```

It imports `load_processed_files`, `check_for_new_documents` and `save_processed_files` straight from `monitor.py`, so there is exactly one scanning implementation. Same content-fingerprint rule for new-vs-changed documents, same unreadable handling, same real agents, same scan log. The only difference is that it ends instead of sleeping and going round again. Run it twice and the second run reviews nothing and writes nothing — it recognises everything as already seen.

Because the cloud machine is deleted after each run, its findings have to be committed back or they'd vanish; the repo itself is the agent's memory. `scan_log.jsonl` and `processed_files.json` are therefore tracked in git. `approvals.json` is **not** — a named human's sign-offs stay off a public repo — and neither is `uploads/`, which holds other people's contracts.

Two honest caveats about GitHub's scheduler: runs are best-effort and often land later than the cron says, and GitHub pauses schedules after 60 days of repository inactivity. Setup instructions for the GitHub website side are in `Documentation/github_actions_setup.md`.

---

## Known limitation: free tier vs. Amazon Bedrock

This is stated plainly because it matters for anyone running the demo.

The full multi-agent **Orchestrator** packs both documents and every intermediate tool result into one large final AI call — roughly **7,000+ tokens** on a realistically-sized document. Groq's **free tier caps at 8,000 tokens per minute**, so a single orchestrator run on a *real-length* document can trip that rate limit. Short sample documents run fine.

**What we did about it (without weakening the real AI):**

- Set `reasoning_effort="low"` on the reasoning model, which keeps genuine reasoning but cuts the hidden token burn.
- Added `call_with_retry()`, which waits out the per-minute limit and retries instead of crashing.
- The standalone real-document test uses a **lighter, fixed-order path** — the same real Reader/Reasoner/Writer agents called one at a time, paced a few seconds apart — so it fits comfortably inside the free tier.

**The clean fix is Amazon Bedrock** (the hackathon's target platform). Bedrock removes the tight per-minute ceiling, so the full Orchestrator handles real-length documents directly. The provider is already wired up in `model_provider.py` — deploying to Bedrock is the next step on the roadmap. A paid Groq tier would also lift the ceiling.

---

## Configuration

All runtime settings live in `config.json` — no need to edit code to point the agent at a different policy or inbox:

| Key | Default | Meaning |
|---|---|---|
| `policy_file` | `corporate_bylaws.txt` | The public commitment every draft is checked against |
| `inbox_dir` | `inbox` | Folder the watcher monitors for new drafts |
| `uploads_dir` | `uploads` | Where uploaded documents are kept, unchanged, as the record of what was reviewed |
| `log_file` | `scan_log.jsonl` | Where scan results are recorded (the dashboard reads this) |
| `approvals_file` | `approvals.json` | Where human Approve/Reject decisions are recorded |
| `auto_apply_redline` | `false` | Kept `false` by design — the agent never auto-applies a fix |
| `scan_interval_seconds` | `30` | How often the watcher checks the inbox |

---

## Project layout

```
model_provider.py            AI model + provider switch, rate-limit retry
orchestrator.py              Multi-agent system (Reader/Reasoner/Writer as tools)
reader_agent.py              Reader agent — extracts facts
reasoner_agent.py            Reasoner agent — judges contradictions
writer_agent.py              Writer agent — drafts redline + memo
monitor.py                   Background inbox watcher (the product)
dashboard.py                 Streamlit case-file viewer (Approve / Reject, upload)
document_intake.py           PDF / Word / text reader + readability check
upload_review.py             On-demand review of an uploaded document
verdict_reader.py            Parses the VERDICT line out of a review
config.json / config.py      Runtime settings
approvals.py                 Records human approve/reject decisions
contradiction_checker.py     Deterministic fallback + test baseline
redline_drafter.py           Deterministic redline/memo generator (fallback)
test_contradiction_checker.py  Offline baseline test
test_document_intake.py      Offline document-reading tests (17 checks)
make_test_documents.py       Builds the PDF / Word / scanned fixtures
run_real_document_test.py    Real-AI tests against genuine public wording
real_policy_meridian.txt     Real climate commitment (fictional name)
test_draft_meridian_*.txt    Hypothetical narrowing / clean drafts
real_policy_quillhaven.txt   Real data-privacy commitment (fictional name)
test_draft_quillhaven_*.txt  Hypothetical narrowing / clean drafts
inbox/                       Sample drafts for the watcher
samples/                     Generated PDF / Word / scanned test documents
uploads/                     Uploaded documents, kept unchanged (git-ignored)
.streamlit/config.toml       Streamlit settings (real upload size limit)
Documentation/               Architecture diagram
```

---

## Status & roadmap

- ✅ Multi-agent Reader → Reasoner → Writer pipeline, real AI via Groq.
- ✅ Background watcher, JSONL logging, Streamlit case-file viewer with human Approve / Reject.
- ✅ Verified on genuine published corporate commitment wording, in two unrelated domains (climate and data privacy), with no code or prompt changes between them.
- ✅ Real document formats: **PDF** (multi-page) and **Word (.docx)**, including text inside tables, on both the watcher and upload paths.
- ✅ Upload-and-review-on-demand from the dashboard, running the same pipeline and producing a normal case that still needs human approval.
- ✅ Scanned / image-only PDFs detected and reported as unreadable instead of reviewed — no empty document ever reaches the AI.
- ⬜ **OCR is not built.** A scanned PDF is correctly refused, not read. Adding OCR (e.g. Amazon Textract, which fits the AWS target platform) is the natural next step for that case.
- ⬜ Amazon Bedrock deployment (removes the free-tier token ceiling).
- ⬜ Demo video.

---

## License

Released under the **MIT License** — see the [`LICENSE`](LICENSE) file.
