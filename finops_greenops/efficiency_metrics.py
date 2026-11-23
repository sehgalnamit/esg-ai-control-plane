"""FinOps/GreenOps roll-ups: cost + carbon-intensity metrics per team/owner/region.

Takes the governed records produced by :mod:`pipeline.ingest_and_normalize`
(and the AI-workload CSV) and rolls them up into per-owner / per-region
aggregates, plus the two headline GreenOps ratios used throughout this
control plane:

* **carbon-per-dollar** -- kg CO2e emitted per USD of (energy) spend, a
  signal for whether a team's spending is buying cleaner or dirtier energy.
* **carbon-per-compute-unit** -- kg CO2e per unit of AI compute (GPU-hour or
  an abstract ``compute_units`` column), used to track whether AI workloads
  are getting more or less carbon-efficient over time.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pipeline.ingest_and_normalize import GovernedEnergyRecord
from pipeline.quality_checks import carbon_intensity_for


class OwnerRegionRollup(BaseModel):
    """Aggregated cost/carbon figures for one owner+region pair."""

    owner: str
    region: str
    total_kwh: float
    total_kg_co2e: float
    total_cost_usd: float
    record_count: int
    flagged_count: int
    carbon_per_dollar: float | None = None  # kg CO2e / USD spent


class AiWorkloadEfficiency(BaseModel):
    """Carbon efficiency of one AI workload record."""

    workload_id: str
    owner: str
    region: str
    gpu_hours: float
    kwh: float
    compute_units: float
    estimated_kg_co2e: float
    carbon_per_gpu_hour: float | None = None
    carbon_per_compute_unit: float | None = None


def rollup_by_owner_region(records: list[GovernedEnergyRecord]) -> list[OwnerRegionRollup]:
    """Roll up governed energy records into owner+region cost/carbon aggregates."""
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        owner = record.owner or "unassigned"
        region = record.region or "unmapped"
        key = (owner, region)
        bucket = buckets.setdefault(
            key,
            {"total_kwh": 0.0, "total_kg_co2e": 0.0, "total_cost_usd": 0.0, "count": 0, "flagged": 0},
        )
        bucket["total_kwh"] += record.kwh
        bucket["total_kg_co2e"] += record.estimated_kg_co2e
        bucket["total_cost_usd"] += record.estimated_cost_usd
        bucket["count"] += 1
        if record.status != "ok":
            bucket["flagged"] += 1

    rollups = []
    for (owner, region), bucket in sorted(buckets.items()):
        cost = bucket["total_cost_usd"]
        carbon_per_dollar = (bucket["total_kg_co2e"] / cost) if cost else None
        rollups.append(
            OwnerRegionRollup(
                owner=owner,
                region=region,
                total_kwh=bucket["total_kwh"],
                total_kg_co2e=bucket["total_kg_co2e"],
                total_cost_usd=cost,
                record_count=bucket["count"],
                flagged_count=bucket["flagged"],
                carbon_per_dollar=carbon_per_dollar,
            )
        )
    return rollups


def _read_ai_workload_csv(path: str | Path) -> list[dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def ai_workload_efficiency(rows: list[dict[str, Any]]) -> list[AiWorkloadEfficiency]:
    """Compute carbon-per-compute-unit and carbon-per-gpu-hour for AI workloads."""
    results = []
    for row in rows:
        region = (row.get("region") or "").strip() or None
        kwh = float(row["kwh"])
        gpu_hours = float(row["gpu_hours"])
        compute_units = float(row["compute_units"])
        intensity = carbon_intensity_for(region)
        kg_co2e = kwh * intensity

        carbon_per_gpu_hour = (kg_co2e / gpu_hours) if gpu_hours else None
        carbon_per_compute_unit = (kg_co2e / compute_units) if compute_units else None

        results.append(
            AiWorkloadEfficiency(
                workload_id=row["workload_id"],
                owner=row["owner"],
                region=region or "unmapped",
                gpu_hours=gpu_hours,
                kwh=kwh,
                compute_units=compute_units,
                estimated_kg_co2e=kg_co2e,
                carbon_per_gpu_hour=carbon_per_gpu_hour,
                carbon_per_compute_unit=carbon_per_compute_unit,
            )
        )
    return results


def ai_workload_efficiency_from_csv(path: str | Path) -> list[AiWorkloadEfficiency]:
    """Load the AI-workload-metrics CSV and compute per-workload carbon efficiency."""
    return ai_workload_efficiency(_read_ai_workload_csv(path))


def ai_workload_efficiency_by_owner(
    efficiencies: list[AiWorkloadEfficiency],
) -> dict[str, dict[str, float]]:
    """Summarize AI-workload carbon efficiency per owning team."""
    buckets: dict[str, dict[str, float]] = {}
    for item in efficiencies:
        bucket = buckets.setdefault(
            item.owner, {"total_kg_co2e": 0.0, "total_gpu_hours": 0.0, "total_compute_units": 0.0}
        )
        bucket["total_kg_co2e"] += item.estimated_kg_co2e
        bucket["total_gpu_hours"] += item.gpu_hours
        bucket["total_compute_units"] += item.compute_units

    summary = {}
    for owner, bucket in buckets.items():
        gpu_hours = bucket["total_gpu_hours"]
        compute_units = bucket["total_compute_units"]
        summary[owner] = {
            **bucket,
            "carbon_per_gpu_hour": (bucket["total_kg_co2e"] / gpu_hours) if gpu_hours else None,
            "carbon_per_compute_unit": (bucket["total_kg_co2e"] / compute_units) if compute_units else None,
        }
    return summary
