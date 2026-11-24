"""Model price table (USD per 1M tokens) for the cost estimates in the observability drawer.

Prices are list prices and only estimates: they ignore batch discounts and free tiers. Update them when models
change. Source: provider pricing pages (openai.com/api/pricing, anthropic.com/pricing); last checked 2026-11-23,
values marked "approx" could not be confirmed online at that time and should be re-checked before the demo.
"""

import logging

from pydantic import BaseModel

log = logging.getLogger(__name__)


class ModelPrice(BaseModel):
    input: float
    cached_input: float
    output: float
    audio_input: float = 0.0
    audio_output: float = 0.0


PRICES: dict[str, ModelPrice] = {
    "gpt-4.1-mini": ModelPrice(input=0.40, cached_input=0.10, output=1.60),
    "gpt-4.1-nano": ModelPrice(input=0.10, cached_input=0.025, output=0.40),
    "gpt-4.1": ModelPrice(input=2.00, cached_input=0.50, output=8.00),
    "gpt-realtime": ModelPrice(input=4.00, cached_input=0.40, output=16.00, audio_input=32.00, audio_output=64.00),
    "gpt-4o-mini-transcribe": ModelPrice(input=1.25, cached_input=1.25, output=5.00, audio_input=3.00),
    "text-embedding-3-small": ModelPrice(input=0.02, cached_input=0.02, output=0.0),
    "claude-haiku-5-5": ModelPrice(input=1.00, cached_input=0.10, output=5.00),  # approx
    "claude-sonnet-5-5": ModelPrice(input=3.00, cached_input=0.30, output=15.00),  # approx
}

_warned: set[str] = set()


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    audio_input_tokens: int = 0,
    audio_output_tokens: int = 0,
) -> float:
    """Estimated cost. `input_tokens` includes cached ones; those are billed at the cached rate."""
    price = PRICES.get(model)
    if price is None:
        if model not in _warned:
            log.warning("no price for model %s; cost reported as 0", model)
            _warned.add(model)
        return 0.0
    uncached = max(input_tokens - cached_input_tokens, 0)
    total = (
        uncached * price.input
        + cached_input_tokens * price.cached_input
        + output_tokens * price.output
        + audio_input_tokens * price.audio_input
        + audio_output_tokens * price.audio_output
    )
    return total / 1_000_000
