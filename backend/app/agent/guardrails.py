"""Confidence guardrails as pure functions, so the routing rules are easy to read, test and defend.

Three bands on the top retrieval score:
  high  (score >= t_high)          -> answer
  grey  (t_low <= score < t_high)  -> answer only if the secondary groundedness check passes
  low   (score < t_low, or nothing) -> do not answer; escalate to a human with a ticket
`skipped` means the turn did not need retrieval (small talk, or a pure account action).
"""

from typing import Literal

from pydantic import BaseModel

from app.events import Band

Intent = Literal["small_talk", "policy", "account_action", "mixed", "out_of_scope"]

_NEEDS_RETRIEVAL: frozenset[str] = frozenset({"policy", "mixed", "out_of_scope"})


class ClassifyResult(BaseModel):
    intent: Intent
    rationale: str


class VerifyResult(BaseModel):
    verdict: Literal["supported", "unsupported"]
    reason: str


def band_for(top_score: float | None, t_low: float, t_high: float) -> Band:
    if top_score is None or top_score < t_low:
        return "low"
    return "high" if top_score >= t_high else "grey"


def needs_forced_retrieval(intent: Intent, searched_this_turn: bool) -> bool:
    """Code, not the model, guarantees that every policy-bearing answer is grounded in a search."""
    return intent in _NEEDS_RETRIEVAL and not searched_this_turn


def needs_verification(intent: Intent, band: Band) -> bool:
    """Small talk is checked for smuggled facts; grey-band answers are checked against their sources."""
    return intent == "small_talk" or band == "grey"


def route_after_guardrail(band: Band, intent: Intent) -> Literal["respond", "escalate"]:
    return "escalate" if band == "low" else "respond"
