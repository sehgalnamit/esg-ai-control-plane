"""Tests for the supplier ESG graph and decaying attestation trust."""

from __future__ import annotations

import math
from datetime import date

from supply_chain.supplier_esg_graph import SupplierEsgGraph


def test_build_graph_with_supplier_facility_and_signals():
    graph = SupplierEsgGraph()
    graph.add_supplier("SUP-1", name="Acme Steel")
    graph.add_facility("FAC-1", "SUP-1", name="Acme Steel Mill 1")
    graph.add_emissions_signal("EMI-1", "FAC-1", value=1200.0, unit="kg_co2e", source_ref="audit://2026/FAC-1")
    graph.add_labor_signal("LAB-1", "FAC-1", value="no violations found", source_ref="audit://2026/FAC-1")

    assert graph.facilities_for_supplier("SUP-1") == ["FAC-1"]
    assert set(graph.signals_for_facility("FAC-1")) == {"EMI-1", "LAB-1"}


def test_trust_decays_exponentially_over_time():
    graph = SupplierEsgGraph()
    graph.add_supplier("SUP-1")
    graph.add_facility("FAC-1", "SUP-1")
    graph.add_self_attestation(
        "SUP-1",
        "FAC-1",
        claim="no child labor in our supply chain",
        base_trust=0.9,
        stability_days=180.0,
        last_verified=date(2026, 1, 1),
    )

    trust_at_zero_days = graph.current_trust("SUP-1", "FAC-1", as_of=date(2026, 1, 1))
    trust_at_180_days = graph.current_trust("SUP-1", "FAC-1", as_of=date(2026, 6, 30))

    assert trust_at_zero_days == 0.9
    assert trust_at_180_days < trust_at_zero_days
    expected_180 = 0.9 * math.exp(-180 / 180.0)
    assert abs(trust_at_180_days - expected_180) < 1e-6


def test_reverify_resets_clock_and_boosts_trust():
    graph = SupplierEsgGraph()
    graph.add_supplier("SUP-1")
    graph.add_facility("FAC-1", "SUP-1")
    graph.add_self_attestation(
        "SUP-1",
        "FAC-1",
        claim="fair wages paid",
        base_trust=0.7,
        stability_days=90.0,
        last_verified=date(2026, 1, 1),
    )

    stale_trust = graph.current_trust("SUP-1", "FAC-1", as_of=date(2026, 6, 1))
    graph.reverify("SUP-1", "FAC-1", as_of=date(2026, 6, 1), trust_boost=0.1)
    fresh_trust = graph.current_trust("SUP-1", "FAC-1", as_of=date(2026, 6, 1))

    assert fresh_trust > stale_trust
    assert abs(fresh_trust - 0.8) < 1e-9  # 0.7 + 0.1 boost, no decay immediately after reverification


def test_reverify_caps_trust_at_one():
    graph = SupplierEsgGraph()
    graph.add_supplier("SUP-1")
    graph.add_facility("FAC-1", "SUP-1")
    graph.add_self_attestation(
        "SUP-1", "FAC-1", claim="claim", base_trust=0.98, last_verified=date(2026, 1, 1)
    )
    graph.reverify("SUP-1", "FAC-1", as_of=date(2026, 1, 2), trust_boost=0.1)
    assert graph.current_trust("SUP-1", "FAC-1", as_of=date(2026, 1, 2)) == 1.0


def test_needs_reverification_report_flags_stale_claims():
    graph = SupplierEsgGraph()
    graph.add_supplier("SUP-FRESH")
    graph.add_facility("FAC-FRESH", "SUP-FRESH")
    graph.add_self_attestation(
        "SUP-FRESH",
        "FAC-FRESH",
        claim="recently verified",
        base_trust=0.9,
        stability_days=180.0,
        last_verified=date(2026, 5, 1),
    )

    graph.add_supplier("SUP-STALE")
    graph.add_facility("FAC-STALE", "SUP-STALE")
    graph.add_self_attestation(
        "SUP-STALE",
        "FAC-STALE",
        claim="verified a long time ago",
        base_trust=0.9,
        stability_days=90.0,
        last_verified=date(2024, 1, 1),
    )

    report = graph.needs_reverification_report(as_of=date(2026, 6, 1), trust_threshold=0.5)
    flagged_suppliers = {r.supplier_id for r in report}

    assert "SUP-STALE" in flagged_suppliers
    assert "SUP-FRESH" not in flagged_suppliers
    assert report[0].current_trust < 0.5
