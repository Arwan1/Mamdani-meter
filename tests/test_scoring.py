from __future__ import annotations

from nyc_civic.scoring import ChildScore, aggregate_scores, normalize_value, percentile_ranks
from nyc_civic.schemas import ScoreStatus


def test_target_normalization_clips_and_is_monotone() -> None:
    assert normalize_value(-1, method="target", direction="higher_better", target=10, floor=0) == 0
    assert normalize_value(5, method="target", direction="higher_better", target=10, floor=0) == 50
    assert normalize_value(12, method="target", direction="higher_better", target=10, floor=0) == 100


def test_lower_is_better_mirrors_target_score() -> None:
    assert normalize_value(10, method="target", direction="lower_better", target=0, floor=10) == 0
    assert normalize_value(5, method="target", direction="lower_better", target=0, floor=10) == 50
    assert normalize_value(0, method="target", direction="lower_better", target=0, floor=10) == 100


def test_coverage_does_not_turn_missing_data_into_zero() -> None:
    result = aggregate_scores(
        [
            ChildScore(score=90, coverage=1, status=ScoreStatus.OK),
            ChildScore(score=None, coverage=0, status=ScoreStatus.UNAVAILABLE),
        ],
        minimum_coverage=0.6,
    )
    assert result.status == ScoreStatus.INSUFFICIENT_COVERAGE
    assert result.score is None
    assert result.coverage == 0.5


def test_relative_ranks_invert_for_lower_is_better() -> None:
    values = {"a": 1.0, "b": 2.0, "c": 3.0}
    assert percentile_ranks(values, "higher_better") == {"a": 0.0, "b": 50.0, "c": 100.0}
    assert percentile_ranks(values, "lower_better") == {"a": 100.0, "b": 50.0, "c": 0.0}
