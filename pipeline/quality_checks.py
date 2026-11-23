"""Data-quality rules and a small grid-carbon-intensity lookup table.

These checks exist so that bad or incomplete source data is *surfaced*, not
silently dropped or silently "fixed". A record with a missing owner, a
negative reading, or a region the control plane does not recognize is still
carried through the pipeline -- it just arrives tagged with ``issues`` so a
human (or a downstream report) can see exactly what is wrong and why an
estimate may be unreliable.
"""

from __future__ import annotations

# Illustrative grid carbon-intensity figures (kg CO2e per kWh), roughly in
# line with published national/regional grid-mix averages. These are
# deliberately simple, static lookup values for a demo control plane -- not a
# live emissions-factor feed -- and are documented as such.
GRID_CARBON_INTENSITY_KG_PER_KWH: dict[str, float] = {
    "EU-DE": 0.380,  # Germany: coal/gas heavy relative to EU peers.
    "EU-FR": 0.056,  # France: nuclear-heavy grid, very low carbon intensity.
    "US-WECC": 0.280,  # US Western Interconnection: mixed hydro/gas/renewables.
    "US-PJM": 0.400,  # US PJM Interconnection: coal/gas heavy.
    "APAC-SG": 0.408,  # Singapore: natural-gas dominated grid.
    "APAC-IN": 0.708,  # India: coal-dominated grid.
}

# Illustrative electricity price (USD per kWh) used only to estimate cost.
GRID_ELECTRICITY_PRICE_USD_PER_KWH: dict[str, float] = {
    "EU-DE": 0.40,
    "EU-FR": 0.23,
    "US-WECC": 0.14,
    "US-PJM": 0.13,
    "APAC-SG": 0.26,
    "APAC-IN": 0.09,
}

# Fallback figures applied (and flagged) when a region code is not in the
# lookup tables above, so an estimate is still produced rather than omitted.
DEFAULT_CARBON_INTENSITY_KG_PER_KWH = 0.475  # roughly a global grid average.
DEFAULT_ELECTRICITY_PRICE_USD_PER_KWH = 0.15

ISSUE_MISSING_OWNER = "missing_owner"
ISSUE_NEGATIVE_KWH = "negative_kwh"
ISSUE_UNMAPPED_REGION = "unmapped_region"


def is_missing_owner(owner: str | None) -> bool:
    """Return True when an owner field is absent or blank."""
    return owner is None or owner.strip() == ""


def is_negative_kwh(kwh: float) -> bool:
    """Return True when a normalized reading is physically implausible."""
    return kwh < 0


def is_unmapped_region(region: str | None) -> bool:
    """Return True when a region code has no entry in the intensity table."""
    return not region or region not in GRID_CARBON_INTENSITY_KG_PER_KWH


def carbon_intensity_for(region: str | None) -> float:
    """Look up kg CO2e/kWh for a region, falling back to a default average."""
    if region and region in GRID_CARBON_INTENSITY_KG_PER_KWH:
        return GRID_CARBON_INTENSITY_KG_PER_KWH[region]
    return DEFAULT_CARBON_INTENSITY_KG_PER_KWH


def electricity_price_for(region: str | None) -> float:
    """Look up USD/kWh for a region, falling back to a default price."""
    if region and region in GRID_ELECTRICITY_PRICE_USD_PER_KWH:
        return GRID_ELECTRICITY_PRICE_USD_PER_KWH[region]
    return DEFAULT_ELECTRICITY_PRICE_USD_PER_KWH


def evaluate_quality(owner: str | None, region: str | None, kwh: float) -> list[str]:
    """Run all quality checks on one normalized reading and list the issues found."""
    issues: list[str] = []
    if is_missing_owner(owner):
        issues.append(ISSUE_MISSING_OWNER)
    if is_negative_kwh(kwh):
        issues.append(ISSUE_NEGATIVE_KWH)
    if is_unmapped_region(region):
        issues.append(ISSUE_UNMAPPED_REGION)
    return issues
