"""EU Taxonomy Green Asset Ratio (GAR) calculator.

The Green Asset Ratio is a disclosure metric introduced under the EU
Taxonomy Regulation / EBA ITS for banks: the share of a bank's
taxonomy-*eligible* exposures (loans, debt, equity to in-scope
counterparties) that are also taxonomy-*aligned* (i.e. substantially
contribute to an environmental objective without significant harm to the
others). This module computes GAR from a list of counterparty exposures and
preserves per-counterparty traceability (``source_ref``) so every input to
the ratio can be audited back to its origin.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CounterpartyExposure(BaseModel):
    """One counterparty's exposure, tagged for EU Taxonomy eligibility/alignment."""

    counterparty_id: str
    source_ref: str
    exposure_type: str  # e.g. "loan", "debt", "equity"
    exposure_amount_usd: float = Field(ge=0)
    taxonomy_eligible: bool
    # Fraction (0-1) of this exposure that is taxonomy-aligned. A plain bool
    # `True` is treated as fully aligned (1.0); callers may instead supply a
    # partial fraction when only part of a counterparty's activity qualifies.
    taxonomy_aligned_fraction: float = Field(default=0.0, ge=0.0, le=1.0)


class GarResult(BaseModel):
    """Computed Green Asset Ratio plus the inputs it was derived from."""

    total_exposure_usd: float
    eligible_exposure_usd: float
    aligned_exposure_usd: float
    green_asset_ratio: float | None  # aligned / eligible; None if no eligible exposure
    counterparty_count: int


class CounterpartyContribution(BaseModel):
    """Per-counterparty traceability of how it feeds into the GAR calculation."""

    counterparty_id: str
    source_ref: str
    exposure_amount_usd: float
    taxonomy_eligible: bool
    aligned_amount_usd: float


def compute_gar(exposures: list[CounterpartyExposure]) -> GarResult:
    """Compute the Green Asset Ratio across a list of counterparty exposures.

    GAR = total taxonomy-aligned exposure / total taxonomy-eligible exposure.
    Non-eligible exposures contribute to neither the numerator nor the
    (eligible) denominator, matching the EBA GAR definition, which excludes
    out-of-scope counterparties (e.g. sovereigns, some SMEs) from the ratio.
    """
    total = 0.0
    eligible = 0.0
    aligned = 0.0
    for exposure in exposures:
        total += exposure.exposure_amount_usd
        if exposure.taxonomy_eligible:
            eligible += exposure.exposure_amount_usd
            aligned += exposure.exposure_amount_usd * exposure.taxonomy_aligned_fraction

    ratio = (aligned / eligible) if eligible > 0 else None
    return GarResult(
        total_exposure_usd=total,
        eligible_exposure_usd=eligible,
        aligned_exposure_usd=aligned,
        green_asset_ratio=ratio,
        counterparty_count=len(exposures),
    )


def per_counterparty_contributions(
    exposures: list[CounterpartyExposure],
) -> list[CounterpartyContribution]:
    """Build a per-counterparty trace of exposure/alignment feeding the GAR."""
    return [
        CounterpartyContribution(
            counterparty_id=e.counterparty_id,
            source_ref=e.source_ref,
            exposure_amount_usd=e.exposure_amount_usd,
            taxonomy_eligible=e.taxonomy_eligible,
            aligned_amount_usd=(
                e.exposure_amount_usd * e.taxonomy_aligned_fraction if e.taxonomy_eligible else 0.0
            ),
        )
        for e in exposures
    ]
