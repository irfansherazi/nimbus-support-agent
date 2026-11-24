"""Choose the confidence-band thresholds from labelled queries instead of guessing them.

Each labelled query has the top retrieval score it gets and whether it SHOULD escalate (out of scope). For a pair
(t_low, t_high):
- score <  t_low            -> escalated without answering        (we want every out-of-scope query here)
- t_low <= score < t_high   -> answered only if the source check passes (costs a model call, so keep it small)
- score >= t_high           -> answered without a check            (an out-of-scope query here is a "leak")
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LabelledScore:
    score: float
    should_escalate: bool


@dataclass(frozen=True)
class SweepRow:
    t_low: float
    t_high: float
    escalate_precision: float  # of the queries escalated outright, the share that should escalate
    escalate_recall: float  # of the queries that should escalate, the share escalated outright
    high_band_leaks: int  # out-of-scope queries answered with no source check
    grey_rate: float  # share of all queries that need the source check


def sweep(data: list[LabelledScore], lows: list[float], highs: list[float]) -> list[SweepRow]:
    positives = [d for d in data if d.should_escalate]
    rows = []
    for t_low in lows:
        for t_high in highs:
            if t_high < t_low:
                continue
            escalated = [d for d in data if d.score < t_low]
            tp = sum(d.should_escalate for d in escalated)
            rows.append(
                SweepRow(
                    t_low=round(t_low, 4),
                    t_high=round(t_high, 4),
                    escalate_precision=tp / len(escalated) if escalated else 1.0,
                    escalate_recall=tp / len(positives) if positives else 1.0,
                    high_band_leaks=sum(d.should_escalate and d.score >= t_high for d in data),
                    grey_rate=sum(t_low <= d.score < t_high for d in data) / len(data),
                )
            )
    return rows


def choose(rows: list[SweepRow], min_precision: float = 0.9) -> SweepRow:
    """No leaks first; then precision >= min_precision; then highest recall; then the smallest grey band.

    Ties are broken by taking the middle candidate, so the thresholds sit in the gap between the classes rather
    than touching a data point.
    """
    fewest_leaks = min(r.high_band_leaks for r in rows)
    pool = [r for r in rows if r.high_band_leaks == fewest_leaks]
    precise = [r for r in pool if r.escalate_precision >= min_precision] or pool
    best_recall = max(r.escalate_recall for r in precise)
    top = [r for r in precise if r.escalate_recall == best_recall]
    least_grey = min(r.grey_rate for r in top)
    tied = sorted((r for r in top if r.grey_rate == least_grey), key=lambda r: (r.t_low, r.t_high))
    return tied[len(tied) // 2]
