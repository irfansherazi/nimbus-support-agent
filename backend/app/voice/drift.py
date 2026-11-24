"""Spoken-output check (spec §8.2a): did the voice say what the agent answered, and nothing more?

It can't un-say audio that already played, so it doesn't block anything. It makes drift visible: a red
`voice_drift` span in the drawer, and a measurable rate in the evals.
"""

from pydantic import BaseModel

DRIFT_SYSTEM = """You compare what a voice assistant SAID with the ANSWER its support agent gave it to say.
Report drift if the spoken text adds, changes or contradicts any fact, number, date, limit, policy or ID in the
answer. Rephrasing, shortening, greetings and a short holding line are not drift. If the spoken text is cut off
(it ends with "…"), judge only the part that was said."""


class DriftResult(BaseModel):
    drift: bool
    reason: str
