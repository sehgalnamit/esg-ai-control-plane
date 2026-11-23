"""Confidence-gated Jev + jury cascade (Pattern A).

Ask Jev first: it is fast/cheap and returns a confidence score alongside its
answer (https://docs.typesafe.ai/confidence). If that confidence clears a
configurable threshold, act on it automatically. If the question is
ambiguous (low confidence) or explicitly high-stakes, escalate to the
:class:`~evaluator.jury.JuryPanel` for a slower, more nuanced, rationale-bearing
verdict. This mirrors the confidence-routing pattern described at
https://docs.typesafe.ai/patterns/confidence-routing.
"""

from __future__ import annotations

from pydantic import BaseModel

from evaluator.jev_gate import (
    JevAnswer,
    JevClient,
    JevQuestion,
    get_default_jev_client,
    noul_confidence,
)
from evaluator.jury import JuryPanel, JuryVerdict

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
NEEDS_HUMAN_REVIEW = "needs_human_review"


class CascadeDecision(BaseModel):
    """Outcome of running the confidence-gated cascade once."""

    verdict: str
    decided_by: str  # "jev" or "jury"
    confidence: float
    jev_answer: JevAnswer
    jury_verdict: JuryVerdict | None = None
    rationale: str


def _jev_verdict_and_confidence(answer: JevAnswer) -> tuple[str, float]:
    if answer.type == "noul":
        confidence = noul_confidence(answer.noul)
        verdict = SUPPORTED if answer.noul >= 0.5 else UNSUPPORTED
        return verdict, confidence
    if answer.type == "choice":
        return answer.choice, answer.confidence
    # "score": no direct supported/unsupported mapping, surface the raw score as a string
    return str(answer.score), answer.confidence


class ConfidenceGatedCascade:
    """Ask Jev first; escalate to the jury only when confidence is insufficient."""

    def __init__(
        self,
        jev_client: JevClient | None = None,
        jury: JuryPanel | None = None,
        confidence_threshold: float = 0.6,
        always_escalate_high_stakes: bool = False,
    ):
        self.jev_client = jev_client or get_default_jev_client()
        self.jury = jury or JuryPanel()
        self.confidence_threshold = confidence_threshold
        self.always_escalate_high_stakes = always_escalate_high_stakes

    def evaluate(
        self,
        state: str | dict,
        question_id: str,
        question: JevQuestion,
        *,
        reference_text: str = "",
        high_stakes: bool = False,
    ) -> CascadeDecision:
        """Run the cascade for a single question.

        ``reference_text`` is forwarded to the jury panel (it is also expected
        inside ``question.criteria["reference_text"]`` for the Jev stage).
        Set ``high_stakes=True`` to force escalation to the jury even when Jev
        is confident, for claims whose consequences warrant a second opinion
        regardless of Jev's self-reported confidence.
        """
        answers = self.jev_client.ask(state, {question_id: question})
        answer = answers[question_id]
        verdict, confidence = _jev_verdict_and_confidence(answer)

        should_escalate = confidence < self.confidence_threshold or (
            high_stakes and self.always_escalate_high_stakes
        )

        if not should_escalate:
            return CascadeDecision(
                verdict=verdict,
                decided_by="jev",
                confidence=confidence,
                jev_answer=answer,
                jury_verdict=None,
                rationale=(
                    f"Jev confidence {confidence:.2f} >= threshold {self.confidence_threshold:.2f}; "
                    "acted automatically without escalation."
                ),
            )

        claim_text = state if isinstance(state, str) else str(state)
        jury_verdict = self.jury.vote(claim_text, reference_text)
        return CascadeDecision(
            verdict=jury_verdict.verdict,
            decided_by="jury",
            confidence=confidence,
            jev_answer=answer,
            jury_verdict=jury_verdict,
            rationale=(
                f"Jev confidence {confidence:.2f} < threshold {self.confidence_threshold:.2f} "
                f"(or high-stakes override); escalated to jury panel, which voted "
                f"'{jury_verdict.verdict}' with {jury_verdict.agreement_ratio:.0%} agreement."
            ),
        )
