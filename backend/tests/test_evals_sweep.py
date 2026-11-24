import pytest

from app.evals.sweep import LabelledScore, choose, sweep


def labelled(scores_escalate, scores_answer):
    return [LabelledScore(s, True) for s in scores_escalate] + [LabelledScore(s, False) for s in scores_answer]


def test_sweep_reports_precision_recall_and_leaks():
    data = labelled([0.10, 0.20, 0.40], [0.35, 0.60, 0.70])
    [row] = sweep(data, lows=[0.30], highs=[0.50])
    assert row.escalate_recall == pytest.approx(2 / 3)  # 0.40 escalate item sits in the grey band
    assert row.escalate_precision == 1.0
    assert row.high_band_leaks == 0  # no escalate item scores >= 0.50
    assert row.grey_rate == pytest.approx(2 / 6)


def test_choose_obvious_thresholds():
    data = labelled([0.10, 0.18, 0.25], [0.50, 0.55, 0.70])
    best = choose(sweep(data, lows=[x / 100 for x in range(20, 61)], highs=[x / 100 for x in range(20, 71)]))
    assert 0.25 < best.t_low <= 0.50
    assert best.escalate_recall == 1.0 and best.escalate_precision == 1.0 and best.high_band_leaks == 0


def test_choose_never_lets_an_out_of_scope_query_into_the_high_band():
    data = labelled([0.10, 0.48], [0.45, 0.60])
    best = choose(sweep(data, lows=[0.2, 0.3, 0.4, 0.5], highs=[0.4, 0.5, 0.6]))
    assert best.t_high > 0.48
