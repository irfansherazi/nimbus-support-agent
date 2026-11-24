"""Spoken-output check (spec §8.2a): did the voice say what the agent answered, and nothing more?

It can't un-say audio that already played, so it doesn't block anything. It makes drift visible: a red
`voice_drift` span in the drawer, and a measurable rate in the evals.
"""

from pydantic import BaseModel

DRIFT_SYSTEM = """You compare what a voice assistant SAID with the ANSWER its support agent gave it to say.
Report drift if the spoken text adds, changes or contradicts any fact, number, date, limit, policy or ID in the
answer. Rephrasing, shortening, greetings and a short holding line are not drift. If the spoken text is cut off
(it ends with "…"), judge only the part that was said."""


CLAIM_SYSTEM = """A voice assistant replied WITHOUT consulting the support agent or its policy documents.
Report drift if the reply states any specific fact about Nimbus policy, prices, plans, limits, timeframes,
procedures or the customer's account (amounts, dates, IDs, statuses). Greetings, thanks, holding lines, asking the
customer to repeat or clarify, and offers to help are not drift."""


class DriftResult(BaseModel):
    drift: bool
    reason: str
