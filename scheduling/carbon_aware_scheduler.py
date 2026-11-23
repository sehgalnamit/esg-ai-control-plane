"""Carbon-aware job scheduling: pick the lowest-carbon feasible region/time-window.

Given a job with a duration, an expected energy draw, a deadline, and a set
of candidate regions, and a table of predicted grid carbon-intensity by
region and hour, :func:`find_lowest_carbon_schedule` searches every feasible
(region, start-hour) combination that finishes before the deadline and
returns the one with the lowest average carbon intensity. If no feasible
window exists at all (e.g. the forecast doesn't cover the needed hours, or
the deadline is too tight), that is reported explicitly via ``issues``
rather than returning a misleading schedule.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CarbonForecastPoint(BaseModel):
    """One predicted grid carbon-intensity reading for a region at a given hour."""

    region: str
    hour: int = Field(ge=0)
    kg_co2e_per_kwh: float = Field(ge=0)


class Job(BaseModel):
    """A schedulable job with a duration, energy draw, deadline, and eligible regions."""

    job_id: str
    duration_hours: int = Field(gt=0)
    expected_kwh_per_hour: float = Field(ge=0)
    eligible_regions: list[str]
    earliest_start_hour: int = Field(ge=0)
    deadline_hour: int  # job must finish (start + duration) by this hour, inclusive


class ScheduleDecision(BaseModel):
    """The scheduler's chosen window, or an explicit explanation if none was feasible."""

    job_id: str
    feasible: bool
    region: str | None = None
    start_hour: int | None = None
    end_hour: int | None = None
    avg_carbon_intensity_kg_per_kwh: float | None = None
    estimated_kg_co2e: float | None = None
    issues: list[str] = Field(default_factory=list)


def build_forecast_lookup(points: list[CarbonForecastPoint]) -> dict[tuple[str, int], float]:
    """Index forecast points by (region, hour) for O(1) window lookups."""
    return {(p.region, p.hour): p.kg_co2e_per_kwh for p in points}


def find_lowest_carbon_schedule(job: Job, forecast_points: list[CarbonForecastPoint]) -> ScheduleDecision:
    """Find the lowest-average-carbon-intensity feasible window for a job."""
    lookup = build_forecast_lookup(forecast_points)
    issues: list[str] = []

    if not job.eligible_regions:
        issues.append("no_eligible_regions")
        return ScheduleDecision(job_id=job.job_id, feasible=False, issues=issues)

    latest_start = job.deadline_hour - job.duration_hours
    if latest_start < job.earliest_start_hour:
        issues.append("deadline_too_tight_for_duration")
        return ScheduleDecision(job_id=job.job_id, feasible=False, issues=issues)

    best: ScheduleDecision | None = None
    any_window_had_full_coverage = False

    for region in job.eligible_regions:
        for start in range(job.earliest_start_hour, latest_start + 1):
            hours = range(start, start + job.duration_hours)
            intensities = [lookup.get((region, h)) for h in hours]
            if any(v is None for v in intensities):
                continue  # incomplete forecast coverage for this window; skip, don't guess
            any_window_had_full_coverage = True
            avg_intensity = sum(intensities) / len(intensities)
            total_kg_co2e = avg_intensity * job.expected_kwh_per_hour * job.duration_hours
            if best is None or total_kg_co2e < best.estimated_kg_co2e:
                best = ScheduleDecision(
                    job_id=job.job_id,
                    feasible=True,
                    region=region,
                    start_hour=start,
                    end_hour=start + job.duration_hours,
                    avg_carbon_intensity_kg_per_kwh=avg_intensity,
                    estimated_kg_co2e=total_kg_co2e,
                )

    if best is None:
        if not any_window_had_full_coverage:
            issues.append("insufficient_forecast_coverage")
        return ScheduleDecision(job_id=job.job_id, feasible=False, issues=issues)

    return best
