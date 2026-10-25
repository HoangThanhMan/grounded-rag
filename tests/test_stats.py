import pytest

from eval import stats


def test_mcnemar_counts_only_discordant_pairs():
    # 10 questions both get right, 6 only A gets right, 0 only B: p = 2 * (1/2)^6
    a = [1] * 16 + [0] * 4
    b = [1] * 10 + [0] * 6 + [0] * 4
    assert stats.mcnemar_p(a, b) == pytest.approx(2 * 0.5**6, abs=1e-4)
    assert stats.mcnemar_p([1, 0, 1], [1, 0, 1]) == 1.0


def test_paired_difference_and_its_interval():
    a = [1] * 30 + [0] * 70
    b = [1] * 10 + [0] * 90
    out = stats.paired(a, b, n_boot=4000)
    assert out["diff"] == 0.2
    lo, hi = out["ci"]
    assert lo > 0 and hi < 0.4
    assert out["p_boot"] < 0.01 and out["p_mcnemar"] < 0.01


def test_identical_configurations_are_not_different():
    a = [1, 0, 1, 1, 0, 0, 1, 0]
    out = stats.paired(a, list(a), n_boot=500)
    assert out["diff"] == 0 and out["p_boot"] == 1.0 and out["p_mcnemar"] == 1.0


def test_paired_needs_the_same_questions():
    with pytest.raises(ValueError):
        stats.paired([1, 0], [1])


def test_p95_interval_comes_from_the_resampled_latencies():
    scores = [{"latency_ms": v} for v in range(1, 101)]
    ci = stats.intervals(scores, [], n_boot=2000,
                         percentiles={"latency_p95_ms": ("latency_ms", 0.95)})
    lo, hi = ci["latency_p95_ms"]
    assert 88 <= lo <= 96 <= hi <= 100


def _case(qid, kind, status, conf, wrong):
    return {"id": qid, "type": kind, "status": status, "conf": conf, "wrong": wrong}


def test_risk_coverage_trades_answered_share_for_risk():
    # three answered answerable questions; the least confident one is wrong
    cases = [_case("a1", "answerable", "answered", 0.9, False),
             _case("a2", "answerable", "answered", 0.8, False),
             _case("a3", "answerable", "answered", 0.2, True),
             _case("a4", "answerable", "abstained", None, None)]
    out = stats.risk_coverage(cases, lambda c: c["conf"], lambda c: c["wrong"])
    by_t = {p["threshold"]: p for p in out["points"]}
    assert by_t[0.9] == {"threshold": 0.9, "coverage": 0.25, "risk": 0.0, "kept": 1}
    assert by_t[0.2]["coverage"] == 0.75 and by_t[0.2]["risk"] == pytest.approx(0.3333, abs=1e-3)
    # area: flat at 0 from 0.25 to 0.5, then a ramp to 0.333 at 0.75
    assert out["aurc"] == pytest.approx(0.25 * 0.3333 / 2, abs=1e-3)


def test_guard_confidence_is_the_weakest_claim():
    case = {"claims": [{"entailment": 0.9}, {"entailment": 0.4}, {"entailment": None}]}
    assert stats.guard_confidence(case) == 0.4
    assert stats.guard_confidence({"claims": []}) is None


def test_over_seeds_reports_mean_and_spread():
    assert stats.over_seeds([0.1, 0.2, 0.3]) == (0.2, 0.1)
    assert stats.over_seeds([0.5]) == (0.5, 0.0)
