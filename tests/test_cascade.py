"""Tests for the confidence-gated Jev + jury cascade."""

from __future__ import annotations

from evaluator.cascade import ConfidenceGatedCascade
from evaluator.jev_gate import JevQuestion, LocalJevStandIn
from evaluator.jury import JuryPanel

REFERENCE_TEXT = "plant de 01 used 15230 kwh in region eu de january 2026"


def _question(reference_text: str) -> JevQuestion:
    return JevQuestion(
        type="noul",
        instructions="is this claim directly supported by the provided source records?",
        criteria={"reference_text": reference_text},
    )


def test_cascade_acts_automatically_when_claim_matches_source():
    cascade = ConfidenceGatedCascade(
        jev_client=LocalJevStandIn(), jury=JuryPanel(), confidence_threshold=0.6
    )
    decision = cascade.evaluate(
        state=REFERENCE_TEXT,
        question_id="claim_supported",
        question=_question(REFERENCE_TEXT),
        reference_text=REFERENCE_TEXT,
    )
    assert decision.decided_by == "jev"
    assert decision.verdict == "supported"
    assert decision.jury_verdict is None


def test_cascade_acts_automatically_unsupported_when_no_overlap():
    cascade = ConfidenceGatedCascade(
        jev_client=LocalJevStandIn(), jury=JuryPanel(), confidence_threshold=0.6
    )
    unrelated_claim = "totally unrelated marketing statement with zero shared words"
    decision = cascade.evaluate(
        state=unrelated_claim,
        question_id="claim_supported",
        question=_question(REFERENCE_TEXT),
        reference_text=REFERENCE_TEXT,
    )
    assert decision.decided_by == "jev"
    assert decision.verdict == "unsupported"


def test_cascade_escalates_to_jury_when_ambiguous():
    cascade = ConfidenceGatedCascade(
        jev_client=LocalJevStandIn(), jury=JuryPanel(), confidence_threshold=0.95
    )
    partial_claim = "plant de 01 used some kwh last quarter"
    decision = cascade.evaluate(
        state=partial_claim,
        question_id="claim_supported",
        question=_question(REFERENCE_TEXT),
        reference_text=REFERENCE_TEXT,
    )
    assert decision.decided_by == "jury"
    assert decision.jury_verdict is not None
    assert len(decision.jury_verdict.votes) == 3
    assert decision.verdict in {"supported", "unsupported", "needs_human_review"}


def test_cascade_forces_escalation_for_high_stakes_claims():
    cascade = ConfidenceGatedCascade(
        jev_client=LocalJevStandIn(),
        jury=JuryPanel(),
        confidence_threshold=0.1,
        always_escalate_high_stakes=True,
    )
    # This claim would normally auto-act (perfect overlap -> full confidence),
    # but high_stakes=True forces a jury review regardless.
    decision = cascade.evaluate(
        state=REFERENCE_TEXT,
        question_id="claim_supported",
        question=_question(REFERENCE_TEXT),
        reference_text=REFERENCE_TEXT,
        high_stakes=True,
    )
    assert decision.decided_by == "jury"
