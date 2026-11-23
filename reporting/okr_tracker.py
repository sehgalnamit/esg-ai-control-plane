"""OKR tracker: ESG objectives with measurable key results rolled up from computed metrics.

Each :class:`Objective` carries 3-5 measurable :class:`KeyResult` entries.
Rather than tracking progress by hand, :func:`update_key_results_from_metrics`
pulls current values from whatever this control plane has already computed
(GAR, carbon-per-dollar, fairness gaps, overdue AI-Act sign-offs, ...), keyed
by ``kr_id``, and :func:`evaluate_objective` rolls those up into an overall
on-track/at-risk/off-track status.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, field_validator


class KeyResultDirection(str, Enum):
    """Whether a higher or lower current value represents progress."""

    INCREASE = "increase"
    DECREASE = "decrease"


class KeyResult(BaseModel):
    """One measurable key result under an ESG objective."""

    kr_id: str
    description: str
    target_value: float
    direction: KeyResultDirection
    unit: str = ""
    current_value: float | None = None


class Objective(BaseModel):
    """An ESG objective with 3-5 measurable key results."""

    objective_id: str
    name: str
    key_results: list[KeyResult]

    @field_validator("key_results")
    @classmethod
    def _validate_key_result_count(cls, value: list[KeyResult]) -> list[KeyResult]:
        if not 3 <= len(value) <= 5:
            raise ValueError("an objective must have between 3 and 5 key results")
        return value


class KeyResultStatus(BaseModel):
    """A key result's computed progress."""

    kr_id: str
    description: str
    current_value: float | None
    target_value: float
    progress_ratio: float | None
    on_track: bool | None  # None when current_value is missing


class ObjectiveStatus(BaseModel):
    """An objective's rolled-up status across all of its key results."""

    objective_id: str
    name: str
    key_result_statuses: list[KeyResultStatus]
    overall_status: str  # "on_track" | "at_risk" | "off_track"


def update_key_results_from_metrics(objective: Objective, metrics: dict[str, float]) -> Objective:
    """Return a copy of ``objective`` with key-result current values pulled from ``metrics``."""
    updated = [
        kr.model_copy(update={"current_value": metrics[kr.kr_id]}) if kr.kr_id in metrics else kr
        for kr in objective.key_results
    ]
    return objective.model_copy(update={"key_results": updated})


def _key_result_status(kr: KeyResult) -> KeyResultStatus:
    if kr.current_value is None:
        return KeyResultStatus(
            kr_id=kr.kr_id,
            description=kr.description,
            current_value=None,
            target_value=kr.target_value,
            progress_ratio=None,
            on_track=None,
        )

    if kr.direction == KeyResultDirection.INCREASE:
        on_track = kr.current_value >= kr.target_value
        if kr.target_value != 0:
            progress_ratio = min(kr.current_value / kr.target_value, 1.0)
        else:
            progress_ratio = 1.0 if on_track else 0.0
    else:  # DECREASE: lower current value is better
        on_track = kr.current_value <= kr.target_value
        progress_ratio = (
            min(kr.target_value / kr.current_value, 1.0)
            if kr.current_value > 0
            else (1.0 if on_track else 0.0)
        )

    return KeyResultStatus(
        kr_id=kr.kr_id,
        description=kr.description,
        current_value=kr.current_value,
        target_value=kr.target_value,
        progress_ratio=max(0.0, progress_ratio),
        on_track=on_track,
    )


def evaluate_objective(objective: Objective) -> ObjectiveStatus:
    """Roll up an objective's key results into an overall status."""
    statuses = [_key_result_status(kr) for kr in objective.key_results]
    trackable = [s for s in statuses if s.on_track is not None]

    if not trackable:
        overall = "off_track"
    else:
        on_track_count = sum(1 for s in trackable if s.on_track)
        ratio = on_track_count / len(trackable)
        if ratio == 1.0:
            overall = "on_track"
        elif ratio >= 0.5:
            overall = "at_risk"
        else:
            overall = "off_track"

    return ObjectiveStatus(
        objective_id=objective.objective_id,
        name=objective.name,
        key_result_statuses=statuses,
        overall_status=overall,
    )
