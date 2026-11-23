"""Tests for the EU Taxonomy Green Asset Ratio calculator."""

from __future__ import annotations

from taxonomy.gar_eu_taxonomy_calculator import (
    CounterpartyExposure,
    compute_gar,
    per_counterparty_contributions,
)


def _sample_exposures() -> list[CounterpartyExposure]:
    return [
        CounterpartyExposure(
            counterparty_id="CP-1",
            source_ref="loan-book://2026/CP-1",
            exposure_type="loan",
            exposure_amount_usd=1_000_000,
            taxonomy_eligible=True,
            taxonomy_aligned_fraction=1.0,
        ),
        CounterpartyExposure(
            counterparty_id="CP-2",
            source_ref="loan-book://2026/CP-2",
            exposure_type="debt",
            exposure_amount_usd=500_000,
            taxonomy_eligible=True,
            taxonomy_aligned_fraction=0.4,
        ),
        CounterpartyExposure(
            counterparty_id="CP-3",
            source_ref="loan-book://2026/CP-3",
            exposure_type="equity",
            exposure_amount_usd=250_000,
            taxonomy_eligible=False,
            taxonomy_aligned_fraction=0.0,
        ),
    ]


def test_compute_gar_basic_ratio():
    result = compute_gar(_sample_exposures())
    assert result.total_exposure_usd == 1_750_000
    assert result.eligible_exposure_usd == 1_500_000
    assert result.aligned_exposure_usd == 1_000_000 + 500_000 * 0.4
    assert result.green_asset_ratio == (1_000_000 + 200_000) / 1_500_000
    assert result.counterparty_count == 3


def test_compute_gar_no_eligible_exposure_returns_none_ratio():
    exposures = [
        CounterpartyExposure(
            counterparty_id="CP-X",
            source_ref="loan-book://2026/CP-X",
            exposure_type="loan",
            exposure_amount_usd=100.0,
            taxonomy_eligible=False,
        )
    ]
    result = compute_gar(exposures)
    assert result.eligible_exposure_usd == 0.0
    assert result.green_asset_ratio is None


def test_per_counterparty_contributions_traceable():
    contributions = per_counterparty_contributions(_sample_exposures())
    by_id = {c.counterparty_id: c for c in contributions}
    assert by_id["CP-1"].aligned_amount_usd == 1_000_000
    assert by_id["CP-2"].aligned_amount_usd == 200_000
    assert by_id["CP-3"].aligned_amount_usd == 0.0
    assert by_id["CP-3"].source_ref == "loan-book://2026/CP-3"
