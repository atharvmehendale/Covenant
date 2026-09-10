# Turning on the scheduled scan (GitHub website checklist)

This is the part that happens **on GitHub's website, in your browser**, after you've
pushed this project to a GitHub repository. None of it is coding. It's clicking
through settings once, doing a test run, and confirming it worked.

Do it in this order. Each step says what you'll click and what you should see.

---

## Before you start

You need the project pushed to GitHub already — a repository you can open in your
browser at an address like `https://github.com/your-username/your-repo`. If you're
not there yet, push first, then come back to this page.

You also need your **Groq API key** — the same secret key the project uses on your
own machine. It's a long string starting with `gsk_`. Have it ready to paste. If
you don't have it handy, you can make a fresh one at <https://console.groq.com/keys>
(sign in, "Create API Key", copy it — Groq only shows a new key once).

---

## Step 1 — Make sure Actions is turned on

GitHub Actions is the feature that runs the scan on a timer. It's on by default for
most repositories, but check:

1. Open your repository on GitHub.
2. Click the **Settings** tab (top of the page, on the right).
3. In the left sidebar, click **Actions**, then **General**.
4. Under "Actions permissions", make sure **"Allow all actions and reusable
   workflows"** is selected. If it isn't, select it and click **Save**.

> If you never see an **Actions** tab at the top of the repository at all, Actions
> has been switched off for the whole account or organization. On a personal
> account that's rare; if it happens, it's in this same Settings → Actions area.

---

## Step 2 — Let the scan save its findings back

The scan writes down what it found and needs permission to save that back into the
repository. Turn that on once:

1. Still in **Settings → Actions → General**.
2. Scroll down to **"Workflow permissions"**.
3. Select **"Read and write permissions"**.
4. Click **Save**.

That's what lets the scan record its results. Without it, the scan still runs but
can't save anything, and every run starts from scratch.

---

## Step 3 — Add your Groq key as a secret

A "secret" is how GitHub stores your API key safely: encrypted, hidden from the logs,
and never shown to anyone who reads the code. The workflow is already written to look
for a secret with this exact name.

1. In **Settings**, in the left sidebar, click **Secrets and variables**, then
   **Actions**.
2. Click the green **"New repository secret"** button.
3. In **Name**, type exactly:

   ```
   GROQ_API_KEY
   ```

   Type it exactly like that — all capitals, with the underscores. If the name is
   even slightly different, the scan won't find it.
4. In **Secret** (the big box), paste your Groq key (the `gsk_...` string).
5. Click **"Add secret"**.

You should now see `GROQ_API_KEY` listed under "Repository secrets". You won't be able
to read the value back — that's normal and intended. If you ever need to change it,
you replace it with "Update".

---

## Step 4 — Do a test run right now (don't wait for the timer)

The scan is set to run on a timer, but you don't have to wait — you can press a button
to run it immediately. This is the real test that everything above is correct.

1. Click the **Actions** tab at the top of the repository.
2. If GitHub shows a one-time "Workflows aren't being run on this forked repository"
   or a green "I understand my workflows, go ahead and enable them" button, click it.
   (This appears on some repositories the first time only.)
3. In the left sidebar you'll see the workflow's name: **"Scheduled compliance scan"**.
   Click it.
4. On the right you'll see a message: **"This workflow has a workflow_dispatch event
   trigger."** and a grey **"Run workflow"** button. Click **"Run workflow"**, then in
   the little dropdown click the green **"Run workflow"** button to confirm.
5. Wait a few seconds and refresh the page. A new run appears in the list with a
   spinning yellow dot.

---

## Step 5 — Watch the run and confirm it worked

1. Click the run that just started (the top row in the list).
2. Click the **scan** box (that's the job).
3. You'll see the steps run one by one, each turning green with a ✓:
   - Check out the repository
   - Set up Python
   - Install the packages the scan needs
   - Run one compliance scan pass
   - Commit and push what the scan found
4. Click **"Run one compliance scan pass"** to expand it. You'll see the same kind of
   output the scan prints on your own machine — lines like
   `[FLAGGED] jv_pipeline_venture.txt — violation found, escalating.` This is the real
   agents doing the real review.

**A green ✓ on every step means it worked.** The very first run reviews all four sample
documents (that takes a few minutes because the free Groq tier is paced deliberately),
so this run will be the slowest. It's normal.

### What "success" looks like on the two possible outcomes

- **It reviewed new documents:** the last step says findings were pushed, and if you go
  back to the main **Code** tab, `scan_log.jsonl` will have a new commit against it from
  `covenant-agent[bot]`. That's the scan saving its work back — exactly what you want.
- **There was nothing new to review:** the last step says *"No new findings this scan.
  Nothing to commit."* and stops there, still green. That's also success — it means every
  document in the inbox has already been reviewed and nothing changed. (Every run after the
  first will usually look like this, until you add or edit a document.)

Both are the scan working correctly. A green checkmark is the thing to look for, not a
commit every time.

---

## Step 6 — Check the ongoing history any time

To see whether the timer is firing on its own:

1. Click the **Actions** tab.
2. Click **"Scheduled compliance scan"** in the left sidebar.
3. You'll see the full list of runs, newest first. Each row shows whether it was started
   by the timer (**"Scheduled"**) or by you (**"Manually run"**), and whether it passed
   (green ✓) or failed (red ✗).

Click any run to see exactly what it did, the same way you did in Step 5.

---

## Two things about the timer, so nothing surprises you later

These are GitHub's own behaviors, not something wrong with the project:

1. **The timer is "roughly", not "exactly".** The scan is set for about every 10 minutes,
   but GitHub runs scheduled jobs on a best-effort basis and delays them when its servers
   are busy. Ten minutes can become twenty at a busy time. That's expected. Your manual
   **"Run workflow"** button always runs straight away, so use that when you want a scan
   *now*.

2. **GitHub pauses the timer after 60 days of no activity.** If the repository sits
   completely untouched for two months, GitHub switches the schedule off and shows a banner
   offering to switch it back on. One click, or any manual run, wakes it up again. This only
   affects the *automatic* timer — it never deletes anything.

---

## If a run fails (red ✗) — the two likely causes

Open the failed run and look at which step is red:

- **"Run one compliance scan pass" is red**, and the log mentions `GROQ_API_KEY is not set`
  → the secret in Step 3 is missing or its name is misspelled. Go back to Step 3 and check
  the name is exactly `GROQ_API_KEY`.
- **"Run one compliance scan pass" is red**, and the log mentions a rate limit or "429"
  → the free Groq tier was busy. This usually clears itself on the next run; you can also
  press "Run workflow" again to retry.
- **"Commit and push what the scan found" is red** → the write permission in Step 2 didn't
  save. Go back to Step 2, set "Read and write permissions", Save, and run again.

Anything else, open the red step, read the last few lines — the messages are written in
plain English on purpose — and that will usually point straight at the cause.
