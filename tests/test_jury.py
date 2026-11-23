"""Tests for the deterministic jury panel."""

from __future__ import annotations

from evaluator.jury import (
    NEEDS_HUMAN_REVIEW,
    SUPPORTED,
    UNSUPPORTED,
    ConservativeJudge,
    JuryPanel,
    KeywordOverlapJudge,
    NumericConsistencyJudge,
)

REFERENCE = "plant de 01 used 15230 kwh in region eu de in january 2026"


def test_keyword_overlap_judge_supports_well_matched_claim():
    judge = KeywordOverlapJudge()
    vote = judge.vote("plant de 01 used 15230 kwh in region eu de", REFERENCE)
    assert vote.verdict == SUPPORTED
    assert "claim terms" in vote.rationale


def test_keyword_overlap_judge_rejects_unrelated_claim():
    judge = KeywordOverlapJudge()
    vote = judge.vote("completely unrelated statement about marketing spend", REFERENCE)
    assert vote.verdict == UNSUPPORTED


def test_numeric_consistency_judge_matches_figures():
    judge = NumericConsistencyJudge()
    vote = judge.vote("the plant used 15230 kwh", REFERENCE)
    assert vote.verdict == SUPPORTED
    assert "15230" in vote.rationale


def test_numeric_consistency_judge_flags_mismatched_figures():
    judge = NumericConsistencyJudge()
    vote = judge.vote("the plant used 999999 kwh", REFERENCE)
    assert vote.verdict == UNSUPPORTED


def test_numeric_consistency_judge_needs_review_when_no_numbers_cited():
    judge = NumericConsistencyJudge()
    vote = judge.vote("the plant used a lot of energy", REFERENCE)
    assert vote.verdict == NEEDS_HUMAN_REVIEW


def test_conservative_judge_requires_strict_overlap():
    judge = ConservativeJudge(supported_threshold=0.6)
    strong_vote = judge.vote("plant de 01 used 15230 kwh in region eu de", REFERENCE)
    weak_vote = judge.vote("it happened at the plant with some kwh", REFERENCE)
    assert strong_vote.verdict == SUPPORTED
    assert weak_vote.verdict == NEEDS_HUMAN_REVIEW


def test_jury_panel_majority_vote():
    panel = JuryPanel()
    verdict = panel.vote("plant de 01 used 15230 kwh in region eu de", REFERENCE)
    assert verdict.verdict == SUPPORTED
    assert len(verdict.votes) == 3
    assert verdict.agreement_ratio > 0.5


def test_jury_panel_falls_back_to_human_review_on_three_way_split():
    class AlwaysSupported:
        name = "always_supported"

        def vote(self, claim, reference_text):
            from evaluator.jury import JudgeVote

            return JudgeVote(judge_name=self.name, verdict=SUPPORTED, rationale="stub")

    class AlwaysUnsupported:
        name = "always_unsupported"

        def vote(self, claim, reference_text):
            from evaluator.jury import JudgeVote

            return JudgeVote(judge_name=self.name, verdict=UNSUPPORTED, rationale="stub")

    class AlwaysNeedsReview:
        name = "always_needs_review"

        def vote(self, claim, reference_text):
            from evaluator.jury import JudgeVote

            return JudgeVote(judge_name=self.name, verdict=NEEDS_HUMAN_REVIEW, rationale="stub")

    panel = JuryPanel(judges=[AlwaysSupported(), AlwaysUnsupported(), AlwaysNeedsReview()])
    verdict = panel.vote("claim", "reference")
    assert verdict.verdict == NEEDS_HUMAN_REVIEW
