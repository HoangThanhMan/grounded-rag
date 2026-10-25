import pytest

from eval.report import cell, intervals


def _scores(values, key="rate"):
    return [{key: v} for v in values]


def test_constant_values_give_a_zero_width_interval():
    assert intervals(_scores([1.0] * 20), ["rate"], n_boot=500) == {"rate": (1.0, 1.0)}


def test_half_ones_over_a_hundred_questions_matches_the_normal_approximation():
    # p = 0.5, n = 100: standard error 0.05, so the 95% interval is about ±0.098
    lo, hi = intervals(_scores([1.0] * 50 + [0.0] * 50), ["rate"], n_boot=4000)["rate"]
    assert lo == pytest.approx(0.40, abs=0.02)
    assert hi == pytest.approx(0.60, abs=0.02)


def test_questions_outside_a_rate_are_not_in_its_denominator():
    # only the answerable half has a false_abstention value, and all are 0
    scores = _scores([0.0] * 10, "false_abstention") + _scores([None] * 10, "false_abstention")
    assert intervals(scores, ["false_abstention"], n_boot=500) == {"false_abstention": (0.0, 0.0)}


def test_intervals_reproduce_with_the_same_seed():
    scores = _scores([1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0])
    assert intervals(scores, ["rate"], n_boot=300) == intervals(scores, ["rate"], n_boot=300)


def test_cell_shows_the_interval_only_for_rates_that_have_one():
    metrics = {"hallucination_rate": 0.0875, "llm_calls_per_q": 1.0}
    ci = {"hallucination_rate": (0.025, 0.15)}
    assert cell(metrics, ci, "hallucination_rate") == "0.0875 [0.03, 0.15]"
    assert cell(metrics, ci, "llm_calls_per_q") == "1.0"
