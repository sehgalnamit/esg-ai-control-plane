"""Tests for FinOps/GreenOps roll-up metrics."""

from __future__ import annotations

from pathlib import Path

from finops_greenops.efficiency_metrics import (
    ai_workload_efficiency,
    ai_workload_efficiency_by_owner,
    ai_workload_efficiency_from_csv,
    rollup_by_owner_region,
)
from pipeline.ingest_and_normalize import ingest_csv

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_rollup_by_owner_region_aggregates_correctly():
    records = ingest_csv(DATA_DIR / "utility_events.csv")
    rollups = rollup_by_owner_region(records)

    facilities_eu_de = next(r for r in rollups if r.owner == "facilities-eu" and r.region == "EU-DE")
    assert facilities_eu_de.record_count == 2
    assert facilities_eu_de.total_kwh == 15230 + 2900
    assert facilities_eu_de.carbon_per_dollar is not None
    assert facilities_eu_de.flagged_count == 0

    unassigned = next(r for r in rollups if r.owner == "unassigned")
    assert unassigned.flagged_count >= 1


def test_rollup_handles_zero_cost_without_crashing():
    from pipeline.ingest_and_normalize import GovernedEnergyRecord

    zero_cost_record = GovernedEnergyRecord(
        event_id="EVT-ZERO",
        source_ref="meter://zero",
        owner="team-z",
        region="EU-DE",
        kwh=0.0,
        estimated_kg_co2e=0.0,
        estimated_cost_usd=0.0,
        status="ok",
        issues=[],
    )
    rollups = rollup_by_owner_region([zero_cost_record])
    assert rollups[0].carbon_per_dollar is None


def test_ai_workload_efficiency_computes_carbon_per_compute_unit():
    rows = [
        {
            "workload_id": "WL-1",
            "owner": "ml-platform-team",
            "region": "EU-FR",
            "gpu_hours": "100",
            "kwh": "100",
            "compute_units": "50",
        }
    ]
    results = ai_workload_efficiency(rows)
    assert len(results) == 1
    item = results[0]
    assert item.carbon_per_compute_unit is not None
    assert item.carbon_per_compute_unit == item.estimated_kg_co2e / 50


def test_ai_workload_efficiency_from_sample_csv():
    results = ai_workload_efficiency_from_csv(DATA_DIR / "ai_workload_metrics.csv")
    assert len(results) == 6
    by_owner = ai_workload_efficiency_by_owner(results)
    assert "ml-platform-team" in by_owner
    assert by_owner["ml-platform-team"]["carbon_per_gpu_hour"] is not None

    # France (nuclear-heavy grid) should be meaningfully less carbon-intensive
    # per kWh than India (coal-heavy grid) for comparable workloads.
    fr_item = next(r for r in results if r.region == "EU-FR")
    in_item = next(r for r in results if r.region == "APAC-IN")
    assert (fr_item.estimated_kg_co2e / fr_item.kwh) < (in_item.estimated_kg_co2e / in_item.kwh)
