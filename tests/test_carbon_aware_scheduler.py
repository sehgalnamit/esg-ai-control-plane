"""Tests for the carbon-aware scheduler."""

from __future__ import annotations

from scheduling.carbon_aware_scheduler import (
    CarbonForecastPoint,
    Job,
    find_lowest_carbon_schedule,
)


def _forecast() -> list[CarbonForecastPoint]:
    points = []
    # EU-DE: dirty during the day, clean at night (hours 0-3).
    de_intensity = {0: 0.1, 1: 0.1, 2: 0.1, 3: 0.1, 4: 0.5, 5: 0.5, 6: 0.5, 7: 0.5}
    # US-PJM: uniformly moderate.
    pjm_intensity = {h: 0.3 for h in range(8)}
    for hour, value in de_intensity.items():
        points.append(CarbonForecastPoint(region="EU-DE", hour=hour, kg_co2e_per_kwh=value))
    for hour, value in pjm_intensity.items():
        points.append(CarbonForecastPoint(region="US-PJM", hour=hour, kg_co2e_per_kwh=value))
    return points


def test_picks_lowest_carbon_window_within_deadline():
    job = Job(
        job_id="JOB-1",
        duration_hours=2,
        expected_kwh_per_hour=100.0,
        eligible_regions=["EU-DE", "US-PJM"],
        earliest_start_hour=0,
        deadline_hour=8,
    )
    decision = find_lowest_carbon_schedule(job, _forecast())
    assert decision.feasible is True
    assert decision.region == "EU-DE"
    assert decision.start_hour == 0
    assert decision.avg_carbon_intensity_kg_per_kwh == 0.1
    assert decision.estimated_kg_co2e == 0.1 * 100.0 * 2


def test_tight_deadline_forces_dirtier_window():
    job = Job(
        job_id="JOB-2",
        duration_hours=2,
        expected_kwh_per_hour=100.0,
        eligible_regions=["EU-DE"],
        earliest_start_hour=5,
        deadline_hour=7,
    )
    decision = find_lowest_carbon_schedule(job, _forecast())
    assert decision.feasible is True
    assert decision.start_hour == 5
    assert decision.avg_carbon_intensity_kg_per_kwh == 0.5


def test_infeasible_deadline_shorter_than_duration():
    job = Job(
        job_id="JOB-3",
        duration_hours=3,
        expected_kwh_per_hour=10.0,
        eligible_regions=["EU-DE"],
        earliest_start_hour=0,
        deadline_hour=2,
    )
    decision = find_lowest_carbon_schedule(job, _forecast())
    assert decision.feasible is False
    assert "deadline_too_tight_for_duration" in decision.issues


def test_no_eligible_regions_flagged():
    job = Job(
        job_id="JOB-4",
        duration_hours=1,
        expected_kwh_per_hour=10.0,
        eligible_regions=[],
        earliest_start_hour=0,
        deadline_hour=5,
    )
    decision = find_lowest_carbon_schedule(job, _forecast())
    assert decision.feasible is False
    assert "no_eligible_regions" in decision.issues


def test_insufficient_forecast_coverage_flagged_not_guessed():
    job = Job(
        job_id="JOB-5",
        duration_hours=2,
        expected_kwh_per_hour=10.0,
        eligible_regions=["APAC-SG"],  # no forecast data for this region at all
        earliest_start_hour=0,
        deadline_hour=5,
    )
    decision = find_lowest_carbon_schedule(job, _forecast())
    assert decision.feasible is False
    assert "insufficient_forecast_coverage" in decision.issues
