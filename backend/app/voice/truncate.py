"""Estimate what the customer actually heard when they interrupted the assistant mid-sentence."""

SPEAKING_RATE_CPS = 15.0  # ~150 words per minute


def truncate_spoken(text: str, spoken_ms: int, chars_per_second: float = SPEAKING_RATE_CPS) -> str:
    """Cut `text` to what fits in `spoken_ms` of speech, at a word boundary, ending with an ellipsis.

    The Realtime API reports how much audio played (audio_end_ms) but its transcript is what was generated, so
    memory would otherwise claim the customer heard sentences they talked over.
    """
    n = int(spoken_ms / 1000 * chars_per_second)
    if n >= len(text):
        return text
    cut = text[:n]
    if not text[n].isspace() and " " in cut:
        cut = cut[: cut.rfind(" ")]  # don't end on half a word
    return cut.rstrip(" ,.;:-") + "…"
