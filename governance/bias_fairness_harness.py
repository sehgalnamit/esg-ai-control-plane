"""Bias/fairness harness for scoring-model outputs across labeled groups.

Any scoring model used in an ESG context -- a credit-risk model, a vendor
screening score, an internal "ESG score" used to gate investment or
procurement decisions -- can encode bias against specific groups even when
no group label is an explicit input. This harness computes standard
fairness metrics (selection rate, disparate-impact ratio, demographic-parity
difference) across labeled groups and flags gaps that exceed a configurable
threshold, so a biased screen is caught before it silently drives decisions.

The headline worked example (see ``tests/test_bias_fairness_harness.py``) is
a naive ESG screening score that ranks counterparties purely by *absolute*
emissions: this systematically penalizes "hard-to-abate" sectors (steel,
cement, aviation, shipping) relative to low-emissions sectors like software,
regardless of each sector's actual transition effort or trajectory -- a
well-documented failure mode of simplistic ESG screens.
"""

from __future__ import annotations

from pydantic import BaseModel


class GroupScore(BaseModel):
    """One scored entity, labeled with its group, for fairness evaluation."""

    entity_id: str
    group: str
    score: float
    selected: bool  # whether the scoring model's decision selected/approved this entity


class GroupSelectionRate(BaseModel):
    """Selection rate for one group."""

    group: str
    count: int
    selected_count: int
    selection_rate: float


class FairnessReport(BaseModel):
    """Pairwise fairness metrics between the best-off group and every other group."""

    reference_group: str
    reference_selection_rate: float
    group_rates: list[GroupSelectionRate]
    disparate_impact_ratios: dict[str, float]  # group -> ratio vs reference
    demographic_parity_differences: dict[str, float]  # group -> |rate - reference_rate|
    flagged_groups: list[str]  # groups whose disparate-impact ratio falls below threshold


def selection_rates(scores: list[GroupScore]) -> list[GroupSelectionRate]:
    """Compute the selection (positive-outcome) rate for each group."""
    buckets: dict[str, dict[str, int]] = {}
    for item in scores:
        bucket = buckets.setdefault(item.group, {"count": 0, "selected": 0})
        bucket["count"] += 1
        if item.selected:
            bucket["selected"] += 1
    return [
        GroupSelectionRate(
            group=group,
            count=bucket["count"],
            selected_count=bucket["selected"],
            selection_rate=bucket["selected"] / bucket["count"] if bucket["count"] else 0.0,
        )
        for group, bucket in sorted(buckets.items())
    ]


def evaluate_fairness(
    scores: list[GroupScore],
    *,
    disparate_impact_threshold: float = 0.8,
) -> FairnessReport:
    """Evaluate disparate impact and demographic parity across groups.

    Uses the group with the highest selection rate as the reference (this
    mirrors the US EEOC "four-fifths rule" convention, generalized to an ESG
    screening context: a disparate-impact ratio below ``disparate_impact_threshold``
    -- 0.8 by default -- relative to the best-off group flags a group as
    disproportionately disadvantaged by the scoring model).
    """
    rates = selection_rates(scores)
    if not rates:
        return FairnessReport(
            reference_group="",
            reference_selection_rate=0.0,
            group_rates=[],
            disparate_impact_ratios={},
            demographic_parity_differences={},
            flagged_groups=[],
        )

    reference = max(rates, key=lambda r: r.selection_rate)
    ratios: dict[str, float] = {}
    parity_diffs: dict[str, float] = {}
    flagged: list[str] = []

    for rate in rates:
        ratio = (
            rate.selection_rate / reference.selection_rate if reference.selection_rate > 0 else 0.0
        )
        ratios[rate.group] = ratio
        parity_diffs[rate.group] = abs(rate.selection_rate - reference.selection_rate)
        if rate.group != reference.group and ratio < disparate_impact_threshold:
            flagged.append(rate.group)

    return FairnessReport(
        reference_group=reference.group,
        reference_selection_rate=reference.selection_rate,
        group_rates=rates,
        disparate_impact_ratios=ratios,
        demographic_parity_differences=parity_diffs,
        flagged_groups=flagged,
    )
