"""Tests for the audit-packet builder, tying several modules together end-to-end."""

from __future__ import annotations

from pathlib import Path

from claims.greenwashing_claim_verifier import verify_claim
from evaluator.cascade import ConfidenceGatedCascade
from evaluator.jev_gate import LocalJevStandIn
from evaluator.jury import JuryPanel
from governance.audit_chain import AuditChain
from materiality.double_materiality_scorer import EsgTopic, score_topics
from pipeline.ingest_and_normalize import ingest_csv
from reporting.build_audit_packet import build_audit_packet, export_packet_json
from taxonomy.gar_eu_taxonomy_calculator import CounterpartyExposure, compute_gar

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "utility_events.csv"


def test_build_audit_packet_assembles_all_inputs():
    records = ingest_csv(DATA_PATH)

    exposures = [
        CounterpartyExposure(
            counterparty_id="CP-1",
            source_ref="loan-book://CP-1",
            exposure_type="loan",
            exposure_amount_usd=1_000_000,
            taxonomy_eligible=True,
            taxonomy_aligned_fraction=0.6,
        )
    ]
    gar_result = compute_gar(exposures)

    topics = [
        EsgTopic(topic_id="T1", name="Climate transition risk", impact_on_world=5, impact_on_financials=4),
        EsgTopic(topic_id="T2", name="Office recycling", impact_on_world=1, impact_on_financials=1),
    ]
    scored_topics = score_topics(topics, threshold=3)

    audit_chain = AuditChain()
    cascade = ConfidenceGatedCascade(
        jev_client=LocalJevStandIn(), jury=JuryPanel(), confidence_threshold=0.5
    )
    claim_verdict = verify_claim(
        "meter plant de 01 reported 15230 kwh", records, cascade, audit_chain
    )

    packet = build_audit_packet(records, gar_result, scored_topics, [claim_verdict], audit_chain)

    assert len(packet.sources) == len(records)
    assert packet.quality_flag_counts.get("missing_owner", 0) >= 1
    assert packet.green_asset_ratio == gar_result.green_asset_ratio
    assert len(packet.material_topics) == 1
    assert packet.material_topics[0].topic_id == "T1"
    assert len(packet.claim_verdicts) == 1
    assert packet.chain_verification.ok is True
    # Building the packet itself appended one more entry (claim verdict + packet).
    assert len(audit_chain.entries) == 2


def test_export_packet_json_round_trips_as_valid_json():
    import json

    records = ingest_csv(DATA_PATH)
    gar_result = compute_gar([])
    audit_chain = AuditChain()
    packet = build_audit_packet(records, gar_result, [], [], audit_chain)

    serialized = export_packet_json(packet)
    reloaded = json.loads(serialized)

    assert reloaded["audit_entry_hash"] == packet.audit_entry_hash
    assert reloaded["green_asset_ratio"] is None
