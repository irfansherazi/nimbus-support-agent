import pytest

from app.llm.pricing import PRICES, ModelPrice, cost_usd


def test_cost_usd_uses_price_table():
    PRICES["test-model"] = ModelPrice(input=1.0, cached_input=0.5, output=2.0)
    assert cost_usd("test-model", 1_000_000, 500_000, cached_input_tokens=200_000) == pytest.approx(0.8 + 0.1 + 1.0)
    assert cost_usd("unknown", 10, 10) == 0.0


def test_audio_tokens_priced_separately():
    PRICES["rt"] = ModelPrice(input=4.0, cached_input=0.4, output=16.0, audio_input=32.0, audio_output=64.0)
    assert cost_usd("rt", 0, 0, audio_input_tokens=1_000_000, audio_output_tokens=500_000) == pytest.approx(64.0)


def test_configured_models_have_prices():
    from app.config import Settings

    s = Settings(_env_file=None)
    for m in (s.agent_model, s.small_model, s.fallback_model, s.realtime_model, s.embedding_model):
        assert m in PRICES, m
