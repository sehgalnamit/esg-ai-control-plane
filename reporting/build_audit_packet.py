"""Assemble a single, lineage-backed, hash-chained audit packet.

Pulls together the outputs of several other modules -- governed source
records, the Green Asset Ratio, the double-materiality ranking, and
claim-verification verdicts -- into one exportable artifact, and appends a
summary of that packet to the shared :class:`~governance.audit_chain.AuditChain`
so the packet itself is tamper-evident and traceable back to the sources
that produced it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel

from claims.greenwashing_claim_verifier import ClaimVerdict
from governance.audit_chain import AuditChain, ChainVerificationResult
from materiality.double_materiality_scorer import ScoredTopic, material_topics
from pipeline.ingest_and_normalize import GovernedEnergyRecord
from taxonomy.gar_eu_taxonomy_calculator import GarResult


class SourceSummary(BaseModel):
    """A lineage-preserving one-line summary of a governed source record."""

    event_id: str
    source_ref: str
    status: str
    issues: list[str]


class AuditPacket(BaseModel):
    """One exportable, lineage-backed, hash-chained ESG audit packet."""

    generated_at: str
    sources: list[SourceSummary]
    quality_flag_counts: dict[str, int]
    green_asset_ratio: float | None
    material_topics: list[ScoredTopic]
    claim_verdicts: list[ClaimVerdict]
    chain_verification: ChainVerificationResult
    audit_entry_hash: str


def _quality_flag_counts(records: list[GovernedEnergyRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for issue in record.issues:
            counts[issue] = counts.get(issue, 0) + 1
    return counts


def build_audit_packet(
    records: list[GovernedEnergyRecord],
    gar_result: GarResult,
    scored_topics: list[ScoredTopic],
    claim_verdicts: list[ClaimVerdict],
    audit_chain: AuditChain,
) -> AuditPacket:
    """Assemble one audit packet and append its fingerprint to the audit chain."""
    sources = [
        SourceSummary(event_id=r.event_id, source_ref=r.source_ref, status=r.status, issues=r.issues)
        for r in records
    ]
    quality_flag_counts = _quality_flag_counts(records)
    material = material_topics(scored_topics)

    entry = audit_chain.append(
        "audit_packet",
        {
            "source_count": len(records),
            "quality_flag_counts": quality_flag_counts,
            "green_asset_ratio": gar_result.green_asset_ratio,
            "material_topic_count": len(material),
            "claim_verdict_count": len(claim_verdicts),
        },
    )

    return AuditPacket(
        generated_at=datetime.now(UTC).isoformat(),
        sources=sources,
        quality_flag_counts=quality_flag_counts,
        green_asset_ratio=gar_result.green_asset_ratio,
        material_topics=material,
        claim_verdicts=claim_verdicts,
        chain_verification=audit_chain.verify_chain(),
        audit_entry_hash=entry.hash,
    )


def export_packet_json(packet: AuditPacket) -> str:
    """Serialize an audit packet as pretty-printed JSON for export/download."""
    return json.dumps(packet.model_dump(mode="json"), indent=2, sort_keys=True)
