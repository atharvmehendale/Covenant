"""
THE MODEL PROVIDER SWITCH

Every agent file (Reader, Reasoner, Writer, Orchestrator) gets its AI
model from this ONE file instead of building it individually. That
means switching providers only requires changing the setting below,
not editing five files.

To switch providers: change PROVIDER below and nothing else needs to
change anywhere else in the project.
"""

import os
import sys
import time

# On Windows, the default console encoding (cp1252) can't print some of the
# Unicode characters that models emit — e.g. the non-breaking hyphen in
# "Net‑Zero" (‑) — which would crash an otherwise-successful run with a
# UnicodeEncodeError. Force UTF-8 output so any agent text prints safely,
# regardless of the terminal's default codepage. Every real-AI run imports
# this file, so doing it here covers all of them in one place.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Quiet the very chatty third-party logs (LiteLLM feedback banners, Strands
# stream/rate-limit warnings, the "reasoningContent is not supported" notice)
# so the console shows OUR clean output, not library noise. Wrapped
# defensively — a logging tweak must never break an actual run.
try:
    import logging

    for _noisy in ("LiteLLM", "litellm", "strands"):
        logging.getLogger(_noisy).setLevel(logging.ERROR)
    os.environ.setdefault("LITELLM_LOG", "ERROR")
except Exception:
    pass


TRUNCATION_NOTICE = (
    "\n\n[This answer was cut off because it reached the model's output limit. "
    "What is above is genuine model output; nothing after this point was "
    "written. Read it as incomplete.]"
)


def _recover_partial(agent) -> str:
    """
    Digs the partial answer out of an agent whose reply was cut off mid-sentence.

    When a reply exceeds the output limit, Strands raises but leaves the partial
    message in the agent's own conversation history. Losing a page of real
    analysis to a crash would be silly, so we retrieve it. Returns "" if there
    is nothing recoverable, which the caller treats as a genuine failure.
    """
    try:
        for message in reversed(getattr(agent, "messages", []) or []):
            role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
            if role != "assistant":
                continue
            content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
            pieces = []
            for block in content or []:
                text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
                if text:
                    pieces.append(text)
            recovered = "\n".join(pieces).strip()
            if recovered:
                return recovered
    except Exception:
        pass
    return ""


TOO_LARGE_MARKERS = ("request too large", "reduce your message size")


class DocumentTooLargeForModel(RuntimeError):
    """
    One request, on its own, is bigger than the model will accept.

    Kept separate from an ordinary rate limit because the two need opposite
    responses. A rate limit means "you asked too often" — waiting fixes it. This
    means "you asked for too much at once" — waiting changes nothing, and the
    honest thing is to stop immediately and say so, rather than sit through six
    pointless retries and then report a rate-limit error for a problem that was
    never about pacing.
    """


RATE_LIMIT_MARKERS = ("rate_limit", "429", "too many requests")


def is_rate_limit_error(error: BaseException) -> bool:
    """
    Was this failure the provider saying "you asked too often"?

    Matched on the message text rather than the exception class on purpose. The
    same underlying 429 reaches us wearing different coats depending on where it
    was raised — a LiteLLM RateLimitError from a direct agent call, or a Strands
    EventLoopException wrapping one when it happened inside a tool — so catching
    classes would mean chasing two libraries' internals and would quietly miss
    whichever wrapper we hadn't thought of. Defining it once here is what keeps
    call_with_retry and the pipeline's fallback agreeing on what a rate limit is.
    """
    return any(marker in str(error).lower() for marker in RATE_LIMIT_MARKERS)


def call_with_retry(agent, prompt: str, max_retries: int = 6, wait_seconds: int = 20):
    """
    Calls a Strands agent, and if it hits a rate limit (common on free
    API tiers), waits and tries again instead of crashing the whole run.
    Groq's free tier resets its per-minute limit every minute, so a
    short wait is usually all it takes.

    RETRIES START FROM A CLEAN CONVERSATION, and that detail is the whole
    difference between this working and this failing on a long document. A
    Strands agent remembers: it appends the prompt to its own message history
    before calling the model, and a failed call does not undo that. So a plain
    "try again" re-sends every earlier attempt alongside the new one. Attempt 2
    is twice the size, attempt 6 is six times the size — measured, not guessed —
    which on a realistic contract turned a comfortable 5,500-token request into a
    33,000-token one and got it rejected outright as too large. The retry loop was
    the thing causing the failure it was retrying. Rewinding the history to where
    it was on entry keeps every attempt the same size as the first, so waiting for
    the per-minute allowance to reset actually helps.

    It also handles the other way a free-tier call fails: the model running out
    of output room part-way through a long answer. That raises in Strands, but
    the partial answer is still real work, so it is recovered and returned with
    a plain note saying it was cut off. A truncated review that says so is
    useful; a traceback in front of a lawyer is not. What we never do is hide
    the truncation, because a memo that stops mid-clause must not read as final.
    """
    # Where the conversation stood before we touched it, so each attempt can be
    # put back to exactly this point. Copied, not referenced — the agent mutates
    # its own list in place.
    baseline = list(getattr(agent, "messages", []) or [])

    def rewind():
        try:
            agent.messages[:] = baseline
        except Exception:
            pass

    for attempt in range(1, max_retries + 1):
        try:
            return agent(prompt)
        except Exception as e:
            error_text = str(e).lower()

            # A single request that is over the model's size limit. Retrying is
            # useless, so say what is actually wrong in words a human can act on.
            if any(marker in error_text for marker in TOO_LARGE_MARKERS):
                raise DocumentTooLargeForModel(
                    "This document is too long to send to the model in one request "
                    f"on the current provider's limits. The model reported: {e}"
                ) from e

            is_rate_limit = is_rate_limit_error(e)
            if is_rate_limit and attempt < max_retries:
                print(f"  (Rate limit hit — waiting {wait_seconds}s before retry {attempt}/{max_retries - 1}...)")
                rewind()  # so the retry is the same size as the first try, not double it
                time.sleep(wait_seconds)
                continue

            if type(e).__name__ == "MaxTokensReachedException" or "maximum token limit" in error_text:
                partial = _recover_partial(agent)
                if partial:
                    print("  (The model ran out of output room — keeping the partial answer and marking it as cut off.)")
                    return partial + TRUNCATION_NOTICE
            raise

# "groq"        = Groq's API (genuinely free tier, no credit card — same
#                 provider MindMesh used). Best for regular building/testing.
# "featherless" = Featherless.ai (paid, uses the existing $24 credit).
#                 Worth testing as a backup for demo-day recording,
#                 since Groq's free tier can hit rate limits under load —
#                 though Featherless caused a live capacity error during
#                 ProofMesh's demo recording before, so test this ahead
#                 of time, not on recording day itself.
# "anthropic"   = Anthropic's own API directly (requires a payment method,
#                 not actually free — kept here in case you add billing later)
# "bedrock"     = Amazon Bedrock via AWS (needs AWS credentials + the
#                 account issue fixed)
PROVIDER = "groq"


def get_model():
    if PROVIDER == "groq":
        from strands.models.litellm import LiteLLMModel

        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Set it as an environment "
                "variable before running (see the setup steps), then "
                "restart your terminal."
            )
        return LiteLLMModel(
            client_args={"api_key": api_key},
            model_id="groq/openai/gpt-oss-120b",
            # reasoning_effort="low": gpt-oss-120b is a *reasoning* model that
            # otherwise spends a large, hidden token budget "thinking" on every
            # call. Our tasks (route to a tool, compare two short clauses) don't
            # need deep chain-of-thought, and that hidden spend is what pushes a
            # multi-agent run over Groq's free 8,000-tokens-per-minute ceiling.
            # Dialing it to "low" keeps the real AI reasoning but slashes the
            # wasted token burn so realistic-length documents fit the free tier.
            # max_tokens=2048: 1024 was too tight, and a real document proved it.
            # Reviewing a 2-page PDF (samples/jv_texas_refinery_long.pdf), the
            # Reader's structured extraction plus this model's hidden reasoning
            # tokens ran past 1024 and the call died mid-sentence with
            # MaxTokensReachedException. 2048 gives the Reader room to quote a
            # long clause properly while still being a firm ceiling — with the
            # sequential path's 20s pacing, worst-case input+output still fits
            # inside Groq's free 8,000-tokens-per-minute allowance.
            params={"max_tokens": 2048, "temperature": 0.3, "reasoning_effort": "low"},
        )

    elif PROVIDER == "featherless":
        from strands.models.litellm import LiteLLMModel

        api_key = os.environ.get("FEATHERLESS_API_KEY")
        if not api_key:
            raise RuntimeError(
                "FEATHERLESS_API_KEY is not set. Set it as an environment "
                "variable before running, then restart your terminal."
            )
        return LiteLLMModel(
            client_args={
                "api_key": api_key,
                "api_base": "https://api.featherless.ai/v1",
            },
            model_id="openai/Qwen/Qwen2.5-72B-Instruct",
            params={"max_tokens": 1024, "temperature": 0.3},
        )

    elif PROVIDER == "anthropic":
        from strands.models.anthropic import AnthropicModel

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Set it as an environment "
                "variable before running (see the setup steps), then "
                "restart your terminal."
            )
        return AnthropicModel(
            client_args={"api_key": api_key},
            model_id="claude-sonnet-4-5-20250929",
            max_tokens=1024,
        )

    elif PROVIDER == "bedrock":
        from strands.models import BedrockModel

        return BedrockModel(
            model_id="us.amazon.nova-pro-v1:0",
            region_name="us-east-1",
            streaming=False,
        )

    else:
        raise ValueError(f"Unknown PROVIDER: {PROVIDER}")


# How the model layer describes itself on screen and in the scan log.
#
# This exists because the three agents each carried a hardcoded "REAL (AI
# reasoning via Bedrock)" string, written when Bedrock was the plan. The
# provider moved to Groq and the strings didn't, so every run printed — and
# logged — a claim about the model layer that was simply untrue. Deriving the
# label from PROVIDER means switching provider updates what the system says
# about itself, and the two cannot drift apart again.
PROVIDER_LABELS = {
    "groq": "Groq — gpt-oss-120b",
    "featherless": "Featherless.ai — Qwen2.5-72B-Instruct",
    "anthropic": "Anthropic API — Claude Sonnet 4.5",
    "bedrock": "Amazon Bedrock — Nova Pro",
}


def provider_label() -> str:
    """A plain-language name for the model actually being called."""
    return PROVIDER_LABELS.get(PROVIDER, PROVIDER)
