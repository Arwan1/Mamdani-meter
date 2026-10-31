from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import mean
from typing import Iterable, Literal

from nyc_civic.schemas import ScoreStatus


Direction = Literal["higher_better", "lower_better"]


def clip_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def normalize_value(
    value: float,
    *,
    method: str,
    direction: Direction,
    target: float | None = None,
    floor: float | None = None,
) -> float | None:
    """Pure target/benchmark normalization. Relative values use percentile_ranks."""
    if not isfinite(value):
        return None
    if method == "descriptive":
        return None
    if method == "relative":
        raise ValueError("Use percentile_ranks for relative normalization")
    if method not in {"target", "benchmark"} or target is None or floor is None:
        raise ValueError("target and floor are required for target/benchmark normalization")
    if target == floor:
        raise ValueError("target and floor must be different")
    if direction == "higher_better":
        raw_score = 100 * (value - floor) / (target - floor)
    else:
        raw_score = 100 * (floor - value) / (floor - target)
    return clip_score(raw_score)


def percentile_ranks(values: dict[str, float], direction: Direction) -> dict[str, float]:
    """Return inclusive 0–100 percentile ranks with average ranks for ties."""
    if not values:
        return {}
    sorted_values = sorted(values.items(), key=lambda item: item[1])
    count = len(sorted_values)
    ranks: dict[str, float] = {}
    index = 0
    while index < count:
        end = index
        while end + 1 < count and sorted_values[end + 1][1] == sorted_values[index][1]:
            end += 1
        percentile = 100.0 if count == 1 else 100 * ((index + end) / 2) / (count - 1)
        for position in range(index, end + 1):
            ranks[sorted_values[position][0]] = percentile
        index = end + 1
    if direction == "lower_better":
        return {geo_id: 100 - score for geo_id, score in ranks.items()}
    return ranks


@dataclass(frozen=True)
class ChildScore:
    score: float | None
    coverage: float
    status: ScoreStatus
    weight: float = 1.0


@dataclass(frozen=True)
class AggregateResult:
    score: float | None
    coverage: float
    status: ScoreStatus


def aggregate_scores(children: Iterable[ChildScore], minimum_coverage: float) -> AggregateResult:
    """Aggregate only scored children; missing data lowers coverage but never becomes zero."""
    scored = [child for child in children if child.status != ScoreStatus.DESCRIPTIVE]
    if not scored:
        return AggregateResult(None, 0.0, ScoreStatus.DESCRIPTIVE)
    total_weight = sum(child.weight for child in scored)
    if total_weight <= 0:
        raise ValueError("Aggregate weights must sum to a positive number")
    coverage = sum(
        child.weight * (child.coverage if child.status == ScoreStatus.OK else 0)
        for child in scored
    ) / total_weight
    available = [child for child in scored if child.status == ScoreStatus.OK and child.score is not None]
    if coverage < minimum_coverage:
        return AggregateResult(None, coverage, ScoreStatus.INSUFFICIENT_COVERAGE)
    if not available:
        return AggregateResult(None, coverage, ScoreStatus.UNAVAILABLE)
    available_weight = sum(child.weight for child in available)
    score = sum(child.weight * float(child.score) for child in available) / available_weight
    return AggregateResult(round(score, 2), round(coverage, 4), ScoreStatus.OK)


def citywide_mean(values: Iterable[float]) -> float | None:
    usable = list(values)
    return round(mean(usable), 2) if usable else None


def population_weighted_mean(values: Iterable[tuple[float, int]]) -> float | None:
    usable = [(score, population) for score, population in values if population > 0]
    denominator = sum(population for _, population in usable)
    if not denominator:
        return None
    return round(sum(score * population for score, population in usable) / denominator, 2)
