"""Greenwashing claim verifier: check a drafted sustainability claim against lineage-backed source data.

Takes a drafted sustainability-report sentence (e.g. "We cut plant emissions
by switching to renewable power in Germany") plus the governed energy
records produced by :mod:`pipeline.ingest_and_normalize`, and uses the
confidence-gated Jev + jury cascade (:mod:`evaluator.cascade`) to classify it
as ``supported``, ``unsupported``, or ``needs_human_review``. Every verdict
is appended to a :class:`~governance.audit_chain.AuditChain` so a regulator
or auditor can later prove the claim was checked, when, against what source
records, and that the record of that check has not been altered since.
"""

from __future__ import annotations

from pydantic import BaseModel

from evaluator.cascade import ConfidenceGatedCascade
from evaluator.jev_gate import JevQuestion
from governance.audit_chain import AuditChain, AuditEntry
from pipeline.ingest_and_normalize import GovernedEnergyRecord

CLAIM_SUPPORT_QUESTION_ID = "claim_supported_by_sources"
CLAIM_SUPPORT_INSTRUCTIONS = "Is this claim directly supported by the provided source records?"


class ClaimVerdict(BaseModel):
    """Result of verifying one sustainability claim, with full source traceability."""

    claim: str
    verdict: str  # "supported" | "unsupported" | "needs_human_review"
    decided_by: str  # "jev" | "jury"
    confidence: float
    rationale: str
    source_refs: list[str]
    audit_entry_hash: str


def build_reference_text(sources: list[GovernedEnergyRecord]) -> str:
    """Render governed source records into a plain-text blob the evaluator can check claims against."""
    lines = []
    for record in sources:
        lines.append(
            f"source_ref={record.source_ref} event_id={record.event_id} region={record.region} "
            f"kwh={record.kwh} estimated_kg_co2e={record.estimated_kg_co2e:.1f} "
            f"estimated_cost_usd={record.estimated_cost_usd:.2f} status={record.status} "
            f"issues={','.join(record.issues) or 'none'}"
        )
    return "\n".join(lines)


def verify_claim(
    claim: str,
    sources: list[GovernedEnergyRecord],
    cascade: ConfidenceGatedCascade,
    audit_chain: AuditChain,
    *,
    high_stakes: bool = False,
) -> ClaimVerdict:
    """Verify one claim against its source records and log the verdict to the audit chain."""
    reference_text = build_reference_text(sources)
    question = JevQuestion(
        type="noul",
        instructions=CLAIM_SUPPORT_INSTRUCTIONS,
        criteria={"reference_text": reference_text},
    )
    decision = cascade.evaluate(
        state=claim,
        question_id=CLAIM_SUPPORT_QUESTION_ID,
        question=question,
        reference_text=reference_text,
        high_stakes=high_stakes,
    )

    source_refs = [s.source_ref for s in sources]
    entry: AuditEntry = audit_chain.append(
        "claim_verification",
        {
            "claim": claim,
            "verdict": decision.verdict,
            "decided_by": decision.decided_by,
            "confidence": decision.confidence,
            "source_refs": source_refs,
            "rationale": decision.rationale,
        },
    )

    return ClaimVerdict(
        claim=claim,
        verdict=decision.verdict,
        decided_by=decision.decided_by,
        confidence=decision.confidence,
        rationale=decision.rationale,
        source_refs=source_refs,
        audit_entry_hash=entry.hash,
    )
