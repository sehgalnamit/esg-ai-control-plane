"""Zero-copy federation across per-subsidiary DuckDB files.

Each subsidiary owns its own small DuckDB file with its own ``esg_metrics``
table -- nobody copies subsidiary rows into a shared central table. Instead,
:class:`FederationLayer` uses DuckDB's ``ATTACH`` to let a single connection
see multiple separate database files, and pushes aggregation *down* into
each attached database before combining only the (already-aggregated)
results. Raw, row-level data for a subsidiary is only visible to a query
if that subsidiary's file has been explicitly attached -- there is no way to
read rows from a subsidiary that was never attached, and the cross-subsidiary
helper methods below only ever return aggregates, never individual rows.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from pydantic import BaseModel

ESG_METRICS_SCHEMA = """
CREATE TABLE esg_metrics (
    metric_id VARCHAR,
    region VARCHAR,
    quarter VARCHAR,
    kwh DOUBLE,
    kg_co2e DOUBLE,
    cost_usd DOUBLE
)
"""


class SubsidiaryMetricRow(BaseModel):
    """One row to seed into a subsidiary's local ``esg_metrics`` table."""

    metric_id: str
    region: str
    quarter: str
    kwh: float
    kg_co2e: float
    cost_usd: float


class RegionAggregate(BaseModel):
    """An aggregated (never row-level) cross-subsidiary result."""

    subsidiary: str
    region: str
    total_kwh: float
    total_kg_co2e: float
    total_cost_usd: float


def seed_subsidiary_db(path: str | Path, rows: list[SubsidiaryMetricRow]) -> None:
    """Create (or overwrite) a standalone per-subsidiary DuckDB file with sample ESG metrics."""
    path = Path(path)
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    try:
        con.execute(ESG_METRICS_SCHEMA)
        for row in rows:
            con.execute(
                "INSERT INTO esg_metrics VALUES (?, ?, ?, ?, ?, ?)",
                [row.metric_id, row.region, row.quarter, row.kwh, row.kg_co2e, row.cost_usd],
            )
    finally:
        con.close()


class FederationLayer:
    """A single DuckDB connection federating only the subsidiary databases it has attached."""

    def __init__(self) -> None:
        self.con = duckdb.connect(":memory:")
        self._attached_aliases: list[str] = []

    def attach_subsidiary(self, path: str | Path, alias: str) -> None:
        """Attach one subsidiary's DuckDB file under a query alias, read-only."""
        self.con.execute(f"ATTACH '{Path(path)}' AS {alias} (READ_ONLY)")
        self._attached_aliases.append(alias)

    @property
    def attached_aliases(self) -> list[str]:
        return list(self._attached_aliases)

    def cross_subsidiary_region_summary(self, aliases: list[str] | None = None) -> list[RegionAggregate]:
        """Aggregate kWh/CO2e/cost by subsidiary+region, pushing aggregation into each attached DB.

        Only attached aliases may be queried; passing an alias that was never
        attached raises a DuckDB error rather than silently returning data.
        Every per-subsidiary SELECT aggregates (SUM) before the UNION ALL, so
        no row-level ``metric_id`` ever crosses between subsidiaries or back
        to the caller.
        """
        aliases = aliases if aliases is not None else self._attached_aliases
        parts = [
            f"SELECT '{alias}' AS subsidiary, region, "
            f"SUM(kwh) AS total_kwh, SUM(kg_co2e) AS total_kg_co2e, SUM(cost_usd) AS total_cost_usd "
            f"FROM {alias}.esg_metrics GROUP BY region"
            for alias in aliases
        ]
        sql = " UNION ALL ".join(parts) + " ORDER BY subsidiary, region"
        result = self.con.execute(sql).fetchall()
        columns = [d[0] for d in self.con.description]
        return [RegionAggregate(**dict(zip(columns, row, strict=True))) for row in result]

    def global_totals(self, aliases: list[str] | None = None) -> dict[str, float]:
        """Roll the per-subsidiary region aggregates up into one global total."""
        summary = self.cross_subsidiary_region_summary(aliases)
        return {
            "total_kwh": sum(r.total_kwh for r in summary),
            "total_kg_co2e": sum(r.total_kg_co2e for r in summary),
            "total_cost_usd": sum(r.total_cost_usd for r in summary),
        }

    def close(self) -> None:
        self.con.close()
