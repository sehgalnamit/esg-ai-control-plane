"""Tests for the zero-copy DuckDB subsidiary federation layer."""

from __future__ import annotations

import duckdb
import pytest

from federation.subsidiary_query_layer import (
    FederationLayer,
    SubsidiaryMetricRow,
    seed_subsidiary_db,
)


def _rows(subsidiary_tag: str) -> list[SubsidiaryMetricRow]:
    return [
        SubsidiaryMetricRow(
            metric_id=f"{subsidiary_tag}-M1",
            region="EU-DE",
            quarter="2026Q1",
            kwh=1000.0,
            kg_co2e=380.0,
            cost_usd=400.0,
        ),
        SubsidiaryMetricRow(
            metric_id=f"{subsidiary_tag}-M2",
            region="US-PJM",
            quarter="2026Q1",
            kwh=500.0,
            kg_co2e=200.0,
            cost_usd=65.0,
        ),
    ]


@pytest.fixture
def subsidiary_dbs(tmp_path):
    paths = {}
    for name in ["sub_a", "sub_b", "sub_c"]:
        path = tmp_path / f"{name}.duckdb"
        seed_subsidiary_db(path, _rows(name))
        paths[name] = path
    return paths


def test_cross_subsidiary_region_summary_aggregates_only(subsidiary_dbs):
    layer = FederationLayer()
    layer.attach_subsidiary(subsidiary_dbs["sub_a"], "sub_a")
    layer.attach_subsidiary(subsidiary_dbs["sub_b"], "sub_b")

    summary = layer.cross_subsidiary_region_summary()

    assert len(summary) == 4  # 2 subsidiaries x 2 regions
    eu_de_sub_a = next(r for r in summary if r.subsidiary == "sub_a" and r.region == "EU-DE")
    assert eu_de_sub_a.total_kwh == 1000.0
    assert eu_de_sub_a.total_kg_co2e == 380.0

    # Only aggregate fields are present -- no row-level metric_id leaks through.
    assert not hasattr(summary[0], "metric_id")

    layer.close()


def test_out_of_scope_subsidiary_never_appears_in_results(subsidiary_dbs):
    """sub_c is seeded on disk but never attached -- its rows must never appear."""
    layer = FederationLayer()
    layer.attach_subsidiary(subsidiary_dbs["sub_a"], "sub_a")
    layer.attach_subsidiary(subsidiary_dbs["sub_b"], "sub_b")

    summary = layer.cross_subsidiary_region_summary()
    subsidiaries_seen = {r.subsidiary for r in summary}

    assert subsidiaries_seen == {"sub_a", "sub_b"}
    assert "sub_c" not in subsidiaries_seen

    # Directly querying the un-attached subsidiary must fail -- it is not
    # reachable through this federation connection at all.
    with pytest.raises(duckdb.Error):
        layer.con.execute("SELECT * FROM sub_c.esg_metrics").fetchall()

    layer.close()


def test_global_totals_rolls_up_across_subsidiaries(subsidiary_dbs):
    layer = FederationLayer()
    layer.attach_subsidiary(subsidiary_dbs["sub_a"], "sub_a")
    layer.attach_subsidiary(subsidiary_dbs["sub_b"], "sub_b")

    totals = layer.global_totals()

    assert totals["total_kwh"] == 2 * (1000.0 + 500.0)
    assert totals["total_cost_usd"] == 2 * (400.0 + 65.0)

    layer.close()


def test_attached_aliases_tracks_only_what_was_attached(subsidiary_dbs):
    layer = FederationLayer()
    layer.attach_subsidiary(subsidiary_dbs["sub_a"], "sub_a")
    assert layer.attached_aliases == ["sub_a"]
    layer.close()
