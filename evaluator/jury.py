"""LLM-jury: a small panel of judges that votes with a textual rationale.

This is stage 2 of the confidence-gated cascade (Pattern A): when Jev's
confidence is too low to act automatically, the state is escalated to a
panel of judges who each cast a vote with a plain-language rationale. By
default the panel is made of deterministic, offline "stub" judges (no LLM
call, no API key) so the whole cascade stays runnable and testable without
external dependencies -- a real deployment could swap in LLM-backed judges
behind the same :class:`Judge` protocol.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
NEEDS_HUMAN_REVIEW = "needs_human_review"


class JudgeVote(BaseModel):
    """One judge's vote plus its rationale."""

    judge_name: str
    verdict: str
    rationale: str


class JuryVerdict(BaseModel):
    """The panel's aggregated decision."""

    verdict: str
    votes: list[JudgeVote]
    agreement_ratio: float  # fraction of votes agreeing with the final verdict


class Judge(Protocol):
    """Contract for a single panel member."""

    name: str

    def vote(self, claim: str, reference_text: str) -> JudgeVote:
        """Cast a vote on whether ``claim`` is supported by ``reference_text``."""
        ...


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


class KeywordOverlapJudge:
    """Votes based on word-level overlap between the claim and the reference text."""

    name = "keyword_overlap_judge"

    def __init__(self, supported_threshold: float = 0.35):
        self.supported_threshold = supported_threshold

    def vote(self, claim: str, reference_text: str) -> JudgeVote:
        claim_tokens = _tokens(claim)
        ref_tokens = _tokens(reference_text)
        overlap = claim_tokens & ref_tokens
        ratio = len(overlap) / len(claim_tokens) if claim_tokens else 0.0
        if ratio >= self.supported_threshold:
            verdict = SUPPORTED
            rationale = (
                f"{len(overlap)}/{len(claim_tokens)} claim terms "
                f"({', '.join(sorted(overlap)) or 'none'}) appear in the source records."
            )
        else:
            verdict = UNSUPPORTED
            rationale = (
                f"Only {len(overlap)}/{len(claim_tokens)} claim terms appear in the "
                "source records -- insufficient lexical overlap."
            )
        return JudgeVote(judge_name=self.name, verdict=verdict, rationale=rationale)


class NumericConsistencyJudge:
    """Votes based on whether numbers cited in the claim appear in the source records."""

    name = "numeric_consistency_judge"

    def vote(self, claim: str, reference_text: str) -> JudgeVote:
        claim_numbers = _numbers(claim)
        ref_numbers = _numbers(reference_text)
        if not claim_numbers:
            return JudgeVote(
                judge_name=self.name,
                verdict=NEEDS_HUMAN_REVIEW,
                rationale="Claim cites no specific figures to cross-check against source records.",
            )
        matched = claim_numbers & ref_numbers
        if matched:
            verdict = SUPPORTED
            rationale = f"Claim figures {sorted(matched)} match values present in the source records."
        else:
            verdict = UNSUPPORTED
            rationale = (
                f"Claim figures {sorted(claim_numbers)} do not match any value in the source records."
            )
        return JudgeVote(judge_name=self.name, verdict=verdict, rationale=rationale)


class ConservativeJudge:
    """A stricter judge: only votes 'supported' on very strong lexical overlap."""

    name = "conservative_judge"

    def __init__(self, supported_threshold: float = 0.6):
        self.supported_threshold = supported_threshold

    def vote(self, claim: str, reference_text: str) -> JudgeVote:
        claim_tokens = _tokens(claim)
        ref_tokens = _tokens(reference_text)
        ratio = len(claim_tokens & ref_tokens) / len(claim_tokens) if claim_tokens else 0.0
        if ratio >= self.supported_threshold:
            return JudgeVote(
                judge_name=self.name,
                verdict=SUPPORTED,
                rationale=f"Overlap ratio {ratio:.2f} clears the strict bar of {self.supported_threshold}.",
            )
        return JudgeVote(
            judge_name=self.name,
            verdict=NEEDS_HUMAN_REVIEW,
            rationale=(
                f"Overlap ratio {ratio:.2f} does not clear the strict bar of "
                f"{self.supported_threshold}; recommend human review rather than guessing."
            ),
        )


def default_judges() -> list[Any]:
    """The default deterministic, offline panel of three stub judges."""
    return [KeywordOverlapJudge(), NumericConsistencyJudge(), ConservativeJudge()]


class JuryPanel:
    """A panel of judges that votes by majority, falling back to human review on ties."""

    def __init__(self, judges: list[Judge] | None = None):
        self.judges = judges if judges is not None else default_judges()

    def vote(self, claim: str, reference_text: str) -> JuryVerdict:
        votes = [judge.vote(claim, reference_text) for judge in self.judges]
        tally: dict[str, int] = {}
        for v in votes:
            tally[v.verdict] = tally.get(v.verdict, 0) + 1

        max_count = max(tally.values())
        winners = [verdict for verdict, count in tally.items() if count == max_count]
        if len(winners) > 1:
            final_verdict = NEEDS_HUMAN_REVIEW
        else:
            final_verdict = winners[0]

        agreement_ratio = tally.get(final_verdict, 0) / len(votes) if votes else 0.0
        return JuryVerdict(verdict=final_verdict, votes=votes, agreement_ratio=agreement_ratio)
