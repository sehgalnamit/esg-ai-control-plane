"""Tests for the greenwashing claim verifier."""

from __future__ import annotations

from pathlib import Path

from claims.greenwashing_claim_verifier import build_reference_text, verify_claim
from evaluator.cascade import ConfidenceGatedCascade
from evaluator.jev_gate import LocalJevStandIn
from evaluator.jury import JuryPanel
from governance.audit_chain import AuditChain
from pipeline.ingest_and_normalize import ingest_csv

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "utility_events.csv"


def _sources():
    return ingest_csv(DATA_PATH)


def test_build_reference_text_includes_source_refs():
    sources = _sources()
    text = build_reference_text(sources)
    assert "meter://plant-de-01/2026-01" in text
    assert "15230" in text


def test_verify_claim_supported_by_sources_is_logged():
    sources = _sources()
    cascade = ConfidenceGatedCascade(
        jev_client=LocalJevStandIn(), jury=JuryPanel(), confidence_threshold=0.5
    )
    audit_chain = AuditChain()
    claim = "meter plant de 01 reported 15230 kwh"

    result = verify_claim(claim, sources, cascade, audit_chain)

    assert result.verdict in {"supported", "unsupported", "needs_human_review"}
    assert len(audit_chain.entries) == 1
    assert audit_chain.entries[0].entry_type == "claim_verification"
    assert audit_chain.entries[0].payload["claim"] == claim
    assert result.audit_entry_hash == audit_chain.entries[0].hash
    assert audit_chain.verify_chain().ok is True


def test_verify_claim_unsupported_fabricated_number():
    sources = _sources()
    cascade = ConfidenceGatedCascade(
        jev_client=LocalJevStandIn(), jury=JuryPanel(), confidence_threshold=0.6
    )
    audit_chain = AuditChain()
    claim = "our facilities achieved a carbon neutral milestone of 999999999 tonnes saved"

    result = verify_claim(claim, sources, cascade, audit_chain)

    assert result.verdict == "unsupported"
    assert result.decided_by == "jev"


def test_multiple_verdicts_preserve_chain_integrity():
    sources = _sources()
    cascade = ConfidenceGatedCascade(
        jev_client=LocalJevStandIn(), jury=JuryPanel(), confidence_threshold=0.5
    )
    audit_chain = AuditChain()

    verify_claim("claim one about 15230 kwh", sources, cascade, audit_chain)
    verify_claim("claim two about something unrelated entirely", sources, cascade, audit_chain)
    verify_claim("claim three about 8820 kwh in us wecc", sources, cascade, audit_chain)

    assert len(audit_chain.entries) == 3
    result = audit_chain.verify_chain()
    assert result.ok is True
    assert result.length == 3


def test_tampering_with_a_verdict_is_detected():
    sources = _sources()
    cascade = ConfidenceGatedCascade(
        jev_client=LocalJevStandIn(), jury=JuryPanel(), confidence_threshold=0.5
    )
    audit_chain = AuditChain()
    verify_claim("claim about 15230 kwh", sources, cascade, audit_chain)
    verify_claim("another claim about 8820 kwh", sources, cascade, audit_chain)

    audit_chain.tamper_with(0, {"claim": "rewritten after the fact", "verdict": "supported"})

    result = audit_chain.verify_chain()
    assert result.ok is False
    assert result.broken_at_index == 0


def test_high_stakes_claim_forces_jury_escalation():
    sources = _sources()
    cascade = ConfidenceGatedCascade(
        jev_client=LocalJevStandIn(),
        jury=JuryPanel(),
        confidence_threshold=0.1,
        always_escalate_high_stakes=True,
    )
    audit_chain = AuditChain()
    claim = "meter plant de 01 reported 15230 kwh"

    result = verify_claim(claim, sources, cascade, audit_chain, high_stakes=True)

    assert result.decided_by == "jury"
