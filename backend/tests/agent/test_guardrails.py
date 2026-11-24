import pytest

from app.agent.guardrails import (
    band_for,
    needs_forced_retrieval,
    needs_verification,
    route_after_guardrail,
)


@pytest.mark.parametrize(
    "score,band", [(None, "low"), (0.29, "low"), (0.30, "grey"), (0.449, "grey"), (0.45, "high"), (0.9, "high")]
)
def test_band_for(score, band):
    assert band_for(score, 0.30, 0.45) == band


@pytest.mark.parametrize(
    "intent,searched,forced",
    [
        ("policy", False, True),
        ("mixed", False, True),
        ("out_of_scope", False, True),
        ("policy", True, False),
        ("small_talk", False, False),
        ("account_action", False, False),
    ],
)
def test_needs_forced_retrieval(intent, searched, forced):
    assert needs_forced_retrieval(intent, searched) is forced


def test_low_band_escalates_but_skipped_band_responds():
    assert route_after_guardrail("low", "policy") == "escalate"
    assert route_after_guardrail("low", "out_of_scope") == "escalate"
    assert route_after_guardrail("skipped", "account_action") == "respond"
    assert route_after_guardrail("grey", "policy") == "respond"
    assert route_after_guardrail("high", "mixed") == "respond"


def test_verification_rules():
    assert needs_verification("small_talk", "skipped") and needs_verification("policy", "grey")
    assert not needs_verification("policy", "high") and not needs_verification("account_action", "skipped")
    assert needs_verification("account_action", "grey")  # an account answer that also cites grey-band policy


def test_low_band_on_account_action_still_responds():
    # The action already happened; the reply just must not lean on the weak policy match.
    assert route_after_guardrail("low", "account_action") == "respond"
