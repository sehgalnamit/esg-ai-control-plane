"""Supplier ESG graph: supplier -> facility -> emissions/labor-signal lineage with decaying trust.

Models a supply chain as a directed graph (via ``networkx``): suppliers
connect to the facilities they operate or source from, and facilities
connect to emissions/labor signal nodes that carry the actual reported
data plus a ``source_ref`` for traceability. Supplier *self-attestations*
(a supplier's own claim about a facility, not independently verified) are
modeled as edges whose trust decays exponentially with time since the last
re-verification: ``trust = base_trust * exp(-t / stability)``. Re-verifying
an attestation resets the clock and can boost its base trust. Stale,
long-unverified attestations surface in :func:`needs_reverification_report`
so they get flagged for follow-up rather than being treated as permanently
reliable.
"""

from __future__ import annotations

import math
from datetime import date

import networkx as nx
from pydantic import BaseModel


class NeedsReverification(BaseModel):
    """One self-attestation edge whose trust has decayed below a threshold."""

    supplier_id: str
    facility_id: str
    current_trust: float
    base_trust: float
    days_since_verification: int
    last_verified: date
    claim: str


class SupplierEsgGraph:
    """A directed supplier -> facility -> signal graph with decaying attestation trust."""

    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()

    def add_supplier(self, supplier_id: str, name: str | None = None) -> None:
        self.graph.add_node(supplier_id, kind="supplier", name=name or supplier_id)

    def add_facility(self, facility_id: str, supplier_id: str, name: str | None = None) -> None:
        self.graph.add_node(facility_id, kind="facility", name=name or facility_id)
        self.graph.add_edge(supplier_id, facility_id, kind="operates")

    def add_emissions_signal(
        self, signal_id: str, facility_id: str, value: float, unit: str, source_ref: str
    ) -> None:
        self.graph.add_node(
            signal_id, kind="emissions_signal", value=value, unit=unit, source_ref=source_ref
        )
        self.graph.add_edge(facility_id, signal_id, kind="reports")

    def add_labor_signal(self, signal_id: str, facility_id: str, value: str, source_ref: str) -> None:
        self.graph.add_node(signal_id, kind="labor_signal", value=value, source_ref=source_ref)
        self.graph.add_edge(facility_id, signal_id, kind="reports")

    def add_self_attestation(
        self,
        supplier_id: str,
        facility_id: str,
        claim: str,
        *,
        base_trust: float = 0.9,
        stability_days: float = 180.0,
        last_verified: date,
    ) -> None:
        """Record a supplier's unverified self-attestation about a facility."""
        self.graph.add_edge(
            supplier_id,
            facility_id,
            kind="self_attestation",
            claim=claim,
            base_trust=base_trust,
            stability_days=stability_days,
            last_verified=last_verified,
        )

    def current_trust(self, supplier_id: str, facility_id: str, as_of: date) -> float:
        """Compute the current (decayed) trust of a self-attestation edge."""
        edge = self.graph.edges[supplier_id, facility_id]
        days_elapsed = (as_of - edge["last_verified"]).days
        return edge["base_trust"] * math.exp(-days_elapsed / edge["stability_days"])

    def reverify(
        self, supplier_id: str, facility_id: str, as_of: date, trust_boost: float = 0.05
    ) -> None:
        """Re-verify an attestation: reset its clock and (optionally) boost its base trust."""
        edge = self.graph.edges[supplier_id, facility_id]
        edge["base_trust"] = min(1.0, edge["base_trust"] + trust_boost)
        edge["last_verified"] = as_of

    def self_attestation_edges(self) -> list[tuple[str, str]]:
        """List all (supplier_id, facility_id) pairs backed by a self-attestation."""
        return [
            (u, v) for u, v, data in self.graph.edges(data=True) if data.get("kind") == "self_attestation"
        ]

    def needs_reverification_report(
        self, as_of: date, trust_threshold: float = 0.5
    ) -> list[NeedsReverification]:
        """List self-attestations whose decayed trust has fallen below ``trust_threshold``."""
        report = []
        for supplier_id, facility_id in self.self_attestation_edges():
            edge = self.graph.edges[supplier_id, facility_id]
            trust = self.current_trust(supplier_id, facility_id, as_of)
            if trust < trust_threshold:
                report.append(
                    NeedsReverification(
                        supplier_id=supplier_id,
                        facility_id=facility_id,
                        current_trust=trust,
                        base_trust=edge["base_trust"],
                        days_since_verification=(as_of - edge["last_verified"]).days,
                        last_verified=edge["last_verified"],
                        claim=edge["claim"],
                    )
                )
        report.sort(key=lambda r: r.current_trust)
        return report

    def facilities_for_supplier(self, supplier_id: str) -> list[str]:
        """List facility node IDs reachable from a supplier via 'operates' edges."""
        return [
            v
            for _, v, data in self.graph.out_edges(supplier_id, data=True)
            if data.get("kind") == "operates"
        ]

    def signals_for_facility(self, facility_id: str) -> list[str]:
        """List signal node IDs reachable from a facility via 'reports' edges."""
        return [
            v
            for _, v, data in self.graph.out_edges(facility_id, data=True)
            if data.get("kind") == "reports"
        ]
