"""Tests for the bias/fairness harness, including a hard-to-abate-sector scenario."""

from __future__ import annotations

from governance.bias_fairness_harness import GroupScore, evaluate_fairness, selection_rates


def test_selection_rates_basic():
    scores = [
        GroupScore(entity_id="E1", group="a", score=0.9, selected=True),
        GroupScore(entity_id="E2", group="a", score=0.8, selected=True),
        GroupScore(entity_id="E3", group="b", score=0.3, selected=False),
        GroupScore(entity_id="E4", group="b", score=0.4, selected=False),
    ]
    rates = selection_rates(scores)
    by_group = {r.group: r for r in rates}
    assert by_group["a"].selection_rate == 1.0
    assert by_group["b"].selection_rate == 0.0


def test_evaluate_fairness_flags_disadvantaged_group():
    scores = [
        GroupScore(entity_id=f"A{i}", group="favored", score=0.9, selected=True) for i in range(8)
    ] + [
        GroupScore(entity_id=f"B{i}", group="disfavored", score=0.2, selected=False) for i in range(8)
    ] + [GroupScore(entity_id="B8", group="disfavored", score=0.9, selected=True)]
    report = evaluate_fairness(scores, disparate_impact_threshold=0.8)
    assert report.reference_group == "favored"
    assert "disfavored" in report.flagged_groups
    assert report.disparate_impact_ratios["disfavored"] < 0.8


def test_evaluate_fairness_no_flag_when_rates_similar():
    scores = [
        GroupScore(entity_id=f"A{i}", group="a", score=0.9, selected=(i < 8)) for i in range(10)
    ] + [GroupScore(entity_id=f"B{i}", group="b", score=0.9, selected=(i < 7)) for i in range(10)]
    report = evaluate_fairness(scores, disparate_impact_threshold=0.8)
    assert report.flagged_groups == []


def test_hard_to_abate_sector_penalized_by_naive_esg_screen():
    """Synthetic scenario: a naive ESG score ranks purely by absolute emissions.

    Steel/cement/aviation ("hard-to-abate") counterparties have inherently
    high absolute emissions regardless of transition effort, while software
    counterparties have low absolute emissions almost by default. A naive
    screen that rejects the highest-emissions half of counterparties will
    disproportionately exclude the hard-to-abate sector -- exactly the kind
    of bias this harness exists to catch before it drives capital-allocation
    decisions.
    """
    hard_to_abate_emissions = [950, 980, 900, 999, 970, 910, 940, 960]
    software_emissions = [10, 15, 8, 20, 12, 9, 14, 11]

    all_emissions = hard_to_abate_emissions + software_emissions
    cutoff = sorted(all_emissions)[len(all_emissions) // 2]  # median: naive "approve below median" rule

    scores = []
    for i, emissions in enumerate(hard_to_abate_emissions):
        scores.append(
            GroupScore(
                entity_id=f"HTA-{i}",
                group="hard_to_abate",
                score=float(emissions),
                selected=emissions < cutoff,
            )
        )
    for i, emissions in enumerate(software_emissions):
        scores.append(
            GroupScore(
                entity_id=f"SW-{i}",
                group="software",
                score=float(emissions),
                selected=emissions < cutoff,
            )
        )

    report = evaluate_fairness(scores, disparate_impact_threshold=0.8)
    assert report.reference_group == "software"
    assert "hard_to_abate" in report.flagged_groups
    assert report.disparate_impact_ratios["hard_to_abate"] == 0.0
