"""Tests for the OKR tracker."""

from __future__ import annotations

import pytest

from reporting.okr_tracker import (
    KeyResult,
    KeyResultDirection,
    Objective,
    evaluate_objective,
    update_key_results_from_metrics,
)


def _sample_objective() -> Objective:
    return Objective(
        objective_id="OBJ-1",
        name="Reduce AI workload carbon intensity",
        key_results=[
            KeyResult(
                kr_id="gar_ratio",
                description="Green Asset Ratio >= 0.4",
                target_value=0.4,
                direction=KeyResultDirection.INCREASE,
            ),
            KeyResult(
                kr_id="carbon_per_compute_unit",
                description="Carbon per compute unit <= 3.0 kg",
                target_value=3.0,
                direction=KeyResultDirection.DECREASE,
                unit="kg_co2e/unit",
            ),
            KeyResult(
                kr_id="overdue_high_risk_signoffs",
                description="Overdue high-risk AI Act sign-offs == 0",
                target_value=0.0,
                direction=KeyResultDirection.DECREASE,
            ),
        ],
    )


def test_objective_requires_between_three_and_five_key_results():
    with pytest.raises(ValueError):
        Objective(
            objective_id="OBJ-BAD",
            name="Too few",
            key_results=[
                KeyResult(
                    kr_id="only_one", description="x", target_value=1.0, direction="increase"
                )
            ],
        )


def test_update_key_results_from_metrics_fills_current_values():
    objective = _sample_objective()
    metrics = {"gar_ratio": 0.5, "carbon_per_compute_unit": 2.0, "overdue_high_risk_signoffs": 0.0}
    updated = update_key_results_from_metrics(objective, metrics)
    values = {kr.kr_id: kr.current_value for kr in updated.key_results}
    assert values == metrics


def test_evaluate_objective_on_track_when_all_key_results_met():
    objective = _sample_objective()
    metrics = {"gar_ratio": 0.5, "carbon_per_compute_unit": 2.0, "overdue_high_risk_signoffs": 0.0}
    updated = update_key_results_from_metrics(objective, metrics)
    status = evaluate_objective(updated)
    assert status.overall_status == "on_track"
    assert all(s.on_track for s in status.key_result_statuses)


def test_evaluate_objective_at_risk_when_some_key_results_missed():
    objective = _sample_objective()
    metrics = {"gar_ratio": 0.2, "carbon_per_compute_unit": 2.0, "overdue_high_risk_signoffs": 0.0}
    updated = update_key_results_from_metrics(objective, metrics)
    status = evaluate_objective(updated)
    assert status.overall_status == "at_risk"


def test_evaluate_objective_off_track_when_most_key_results_missed():
    objective = _sample_objective()
    metrics = {"gar_ratio": 0.1, "carbon_per_compute_unit": 10.0, "overdue_high_risk_signoffs": 3.0}
    updated = update_key_results_from_metrics(objective, metrics)
    status = evaluate_objective(updated)
    assert status.overall_status == "off_track"


def test_missing_current_value_is_not_on_track_but_doesnt_crash():
    objective = _sample_objective()
    status = evaluate_objective(objective)  # no metrics supplied at all
    assert status.overall_status == "off_track"
    assert all(s.on_track is None for s in status.key_result_statuses)
