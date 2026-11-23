"""Ingest heterogeneous utility/energy records into a governed, lineage-preserving shape.

Source rows arrive with inconsistent units (``kWh`` vs ``MWh``), occasionally
missing owners, and region codes that may not exist in the control plane's
grid-carbon-intensity table. :func:`ingest_rows` and :func:`ingest_csv` never
drop or "fix" a bad row silently -- they normalize what can be normalized,
estimate what can be estimated, and attach explicit ``issues`` plus the
original ``source_ref`` so every number stays traceable back to its origin.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pipeline.quality_checks import (
    carbon_intensity_for,
    electricity_price_for,
    evaluate_quality,
)

# Unit conversion factors into kWh, the normalized unit used throughout the
# control plane.
_UNIT_TO_KWH: dict[str, float] = {
    "kwh": 1.0,
    "mwh": 1000.0,
    "wh": 0.001,
}


class GovernedEnergyRecord(BaseModel):
    """A normalized, lineage-preserving energy reading with explicit quality flags."""

    event_id: str
    source_ref: str
    owner: str | None = None
    region: str | None = None
    kwh: float
    estimated_kg_co2e: float
    estimated_cost_usd: float
    status: str
    issues: list[str] = Field(default_factory=list)


def normalize_to_kwh(value: float, unit: str) -> float:
    """Convert a raw numeric reading to kWh given its reported unit.

    Raises ``ValueError`` for a genuinely unknown unit rather than silently
    guessing -- callers should catch this and surface it as a quality issue
    if they choose to proceed with an assumption.
    """
    key = unit.strip().lower()
    if key not in _UNIT_TO_KWH:
        raise ValueError(f"unrecognized unit: {unit!r}")
    return value * _UNIT_TO_KWH[key]


def ingest_row(row: dict[str, Any]) -> GovernedEnergyRecord:
    """Normalize a single heterogeneous raw row into a :class:`GovernedEnergyRecord`."""
    event_id = str(row["event_id"])
    source_ref = str(row["source_ref"])
    owner = (row.get("owner") or "").strip() or None
    region = (row.get("region") or "").strip() or None
    raw_unit = str(row.get("unit", "kWh"))
    issues: list[str] = []

    try:
        kwh = normalize_to_kwh(float(row["kwh"]), raw_unit)
    except ValueError:
        # Unknown unit: fall back to treating the raw number as kWh, but
        # flag it so the estimate is known to be unreliable.
        kwh = float(row["kwh"])
        issues.append("unrecognized_unit")

    issues.extend(evaluate_quality(owner, region, kwh))

    intensity = carbon_intensity_for(region)
    price = electricity_price_for(region)
    estimated_kg_co2e = kwh * intensity
    estimated_cost_usd = kwh * price

    status = "ok" if not issues else "flagged"

    return GovernedEnergyRecord(
        event_id=event_id,
        source_ref=source_ref,
        owner=owner,
        region=region,
        kwh=kwh,
        estimated_kg_co2e=estimated_kg_co2e,
        estimated_cost_usd=estimated_cost_usd,
        status=status,
        issues=issues,
    )


def ingest_rows(rows: list[dict[str, Any]]) -> list[GovernedEnergyRecord]:
    """Normalize a batch of raw rows, preserving one record per input row."""
    return [ingest_row(row) for row in rows]


def ingest_csv(path: str | Path) -> list[GovernedEnergyRecord]:
    """Read a CSV of raw utility events and normalize every row."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    return ingest_rows(rows)
