"""Jev gate: confidence-scored "fast judge" client contract (Pattern A, stage 1).

TypeSafe AI's Jev model (see https://typesafe.ai/ and
https://docs.typesafe.ai/introduction) answers structured questions about a
piece of state and returns a *confidence* score alongside its answer, so a
caller can decide whether to trust the answer automatically or escalate for
deeper review (https://docs.typesafe.ai/patterns/confidence-routing). This
module implements that contract:

* ``noul`` questions (yes/no) return ``{"type": "noul", "noul": <0-1 float>}``.
  There is no separate confidence field -- distance from 0.5 *is* the
  confidence signal (see :func:`noul_confidence`), per
  https://docs.typesafe.ai/confidence.
* ``choice`` questions return a probability distribution over named options
  plus ``confidence = (n * p_max - 1) / (n - 1)`` for ``n`` options.
* ``score`` questions return a probability distribution over ordered levels,
  ``score = sum(level * p_level)``, and
  ``confidence = max(0, 1 - MAD(p) / MAD(uniform))`` where MAD is the
  (probability-weighted) mean absolute deviation of levels around the score,
  and ``MAD(uniform)`` is that same quantity for a uniform distribution over
  the same levels -- i.e. confidence measures how much more peaked the
  answer distribution is than "I have no idea".

Two client implementations are provided:

* :class:`TypeSafeJevClient` -- a real ``httpx`` adapter for the live Jev API
  (``POST https://api.typesafe.ai/v1/systemone``), active only when the
  ``TYPESAFE_API_KEY`` environment variable is set. It is never required to
  run this repository; the optional ``typesafe-sdk`` package is listed only
  as an optional dependency.
* :class:`LocalJevStandIn` -- a deterministic, fully offline stand-in that
  implements the *identical* contract and confidence math using simple,
  explainable heuristics (token overlap, deterministic hashing). It is **not**
  the real trained Jev model and makes no claim to match its judgment quality
  -- it exists purely so this repository is runnable, testable, and
  deterministic without any API key. See also
  https://deepeval.com/blog/introducing-jev-as-a-judge for third-party
  background on the Jev-as-a-judge pattern.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

TYPESAFE_API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"


class JevQuestion(BaseModel):
    """A single question posed to Jev, matching the real API's request shape."""

    type: Literal["noul", "choice", "score"]
    instructions: str
    criteria: dict[str, Any] = Field(default_factory=dict)


class JevNoulAnswer(BaseModel):
    """Yes/no answer: a single float in [0, 1], with no separate confidence field."""

    type: Literal["noul"] = "noul"
    noul: float = Field(ge=0.0, le=1.0)


class JevChoiceAnswer(BaseModel):
    """Multiple-choice answer: a probability distribution plus derived confidence."""

    type: Literal["choice"] = "choice"
    choice: str
    probabilities: dict[str, float]
    confidence: float


class JevScoreAnswer(BaseModel):
    """Ordinal-score answer: expected value over levels plus derived confidence."""

    type: Literal["score"] = "score"
    score: float
    probabilities: dict[str, float]
    confidence: float


JevAnswer = JevNoulAnswer | JevChoiceAnswer | JevScoreAnswer


def noul_confidence(noul: float) -> float:
    """Confidence signal for a noul answer: distance from the uninformative midpoint 0.5."""
    return abs(noul - 0.5) * 2.0


def choice_confidence(probabilities: dict[str, float]) -> float:
    """Confidence for a choice answer with n options: (n*p_max - 1) / (n - 1)."""
    n = len(probabilities)
    if n <= 1:
        return 1.0
    p_max = max(probabilities.values())
    return max(0.0, (n * p_max - 1) / (n - 1))


def score_confidence(levels: list[float], probabilities: list[float]) -> tuple[float, float]:
    """Compute (score, confidence) for an ordinal distribution over ``levels``.

    ``score`` is the probability-weighted expected level. ``confidence`` compares
    the weighted mean-absolute-deviation of the answer distribution around that
    score to the mean-absolute-deviation of a uniform distribution over the same
    levels: a sharply peaked distribution scores close to 1, a uniform ("no
    idea") distribution scores 0.
    """
    n = len(levels)
    score = sum(level * p for level, p in zip(levels, probabilities, strict=True))
    mad_observed = sum(p * abs(level - score) for level, p in zip(levels, probabilities, strict=True))
    mean_level = sum(levels) / n
    mad_uniform = sum(abs(level - mean_level) for level in levels) / n
    confidence = max(0.0, 1.0 - mad_observed / mad_uniform) if mad_uniform > 0 else 1.0
    return score, confidence


class JevClient(Protocol):
    """Contract shared by the real TypeSafe adapter and the local stand-in."""

    def ask(self, state: str | dict[str, Any], questions: dict[str, JevQuestion]) -> dict[str, JevAnswer]:
        """Answer a batch of named questions about ``state``."""
        ...


def _parse_answer(raw: dict[str, Any]) -> JevAnswer:
    answer_type = raw.get("type")
    if answer_type == "noul":
        return JevNoulAnswer(noul=raw["noul"])
    if answer_type == "choice":
        return JevChoiceAnswer(
            choice=raw["choice"], probabilities=raw["probabilities"], confidence=raw["confidence"]
        )
    if answer_type == "score":
        return JevScoreAnswer(
            score=raw["score"], probabilities=raw["probabilities"], confidence=raw["confidence"]
        )
    raise ValueError(f"unrecognized Jev answer type: {answer_type!r}")


class TypeSafeJevClient:
    """Real adapter for the TypeSafe Jev API (https://typesafe.ai/).

    Requires the ``httpx`` package (already a core dependency) and a
    ``TYPESAFE_API_KEY``. Never required to run this repository -- see
    :class:`LocalJevStandIn` for the offline default.
    """

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL, timeout: float = 30.0):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "TYPESAFE_API_KEY is not set. TypeSafeJevClient requires a real API key; "
                "use LocalJevStandIn for offline/deterministic runs."
            )
        self.model = model
        self.timeout = timeout

    def ask(self, state: str | dict[str, Any], questions: dict[str, JevQuestion]) -> dict[str, JevAnswer]:
        import httpx

        payload = {
            "state": state,
            "model": self.model,
            "questions": {qid: q.model_dump() for qid, q in questions.items()},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = httpx.post(TYPESAFE_API_URL, json=payload, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        answers = data.get("answers", data)
        return {qid: _parse_answer(raw) for qid, raw in answers.items()}


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _state_to_text(state: str | dict[str, Any]) -> str:
    return state if isinstance(state, str) else json.dumps(state, sort_keys=True, default=str)


def _deterministic_weights(seed: str, n: int) -> list[float]:
    """Deterministic, reproducible pseudo-distribution derived from a text seed."""
    weights = []
    for i in range(n):
        digest = hashlib.sha256(f"{seed}|{i}".encode()).hexdigest()
        weights.append(int(digest[:8], 16))
    total = sum(weights)
    return [w / total for w in weights]


class LocalJevStandIn:
    """Deterministic, offline stand-in for the real Jev model.

    This is **not** the real trained TypeSafe Jev model -- it is a simple,
    explainable heuristic (token-overlap for ``noul`` questions, deterministic
    hashing for ``choice``/``score`` questions) that implements the identical
    request/response contract and confidence math so the rest of this
    repository can run fully offline and deterministically.

    For ``noul`` questions, the heuristic compares token overlap (Jaccard
    similarity) between the serialized ``state`` and an optional
    ``criteria["reference_text"]`` supplied with the question: high overlap
    maps to a ``noul`` close to 1 ("yes"), low overlap maps close to 0 ("no").
    """

    def ask(self, state: str | dict[str, Any], questions: dict[str, JevQuestion]) -> dict[str, JevAnswer]:
        answers: dict[str, JevAnswer] = {}
        state_text = _state_to_text(state)
        for qid, question in questions.items():
            if question.type == "noul":
                reference_text = str(question.criteria.get("reference_text", ""))
                similarity = _jaccard(_tokenize(state_text), _tokenize(reference_text))
                answers[qid] = JevNoulAnswer(noul=similarity)
            elif question.type == "choice":
                options = list(question.criteria.get("options", ["yes", "no"]))
                weights = _deterministic_weights(f"{state_text}|{question.instructions}", len(options))
                probabilities = dict(zip(options, weights, strict=True))
                choice = max(probabilities, key=lambda k: probabilities[k])
                answers[qid] = JevChoiceAnswer(
                    choice=choice,
                    probabilities=probabilities,
                    confidence=choice_confidence(probabilities),
                )
            elif question.type == "score":
                levels = [float(x) for x in question.criteria.get("levels", [1, 2, 3, 4, 5])]
                weights = _deterministic_weights(f"{state_text}|{question.instructions}", len(levels))
                score, confidence = score_confidence(levels, weights)
                probabilities = {str(level): weight for level, weight in zip(levels, weights, strict=True)}
                answers[qid] = JevScoreAnswer(score=score, probabilities=probabilities, confidence=confidence)
            else:  # pragma: no cover - guarded by Literal typing
                raise ValueError(f"unrecognized question type: {question.type!r}")
        return answers


def get_default_jev_client() -> JevClient:
    """Return the real client if ``TYPESAFE_API_KEY`` is set, else the offline stand-in."""
    if os.environ.get("TYPESAFE_API_KEY"):
        return TypeSafeJevClient()
    return LocalJevStandIn()
