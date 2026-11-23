"""Double-materiality scoring: which ESG topics matter, and to whom.

"Double materiality" (the concept underlying the EU's CSRD/ESRS reporting
standards) asks two independent questions about each candidate ESG topic:

* **Impact materiality** -- how much does the company affect the world on
  this topic (people, environment, society)?
* **Financial materiality** -- how much could this topic affect the
  company's financial performance (costs, revenue, access to capital)?

A topic can be material on either axis independently, so this module scores
both (1-5 scale), buckets each topic into one of four quadrants, and ranks
which topics clear a configurable materiality threshold.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class MaterialityQuadrant(str, Enum):
    """Which axis (if any) makes a topic material."""

    DOUBLE_MATERIAL = "double_material"  # material on both axes
    IMPACT_MATERIAL_ONLY = "impact_material_only"
    FINANCIAL_MATERIAL_ONLY = "financial_material_only"
    NOT_MATERIAL = "not_material"


class EsgTopic(BaseModel):
    """A candidate ESG topic with 1-5 impact and financial materiality ratings."""

    topic_id: str
    name: str
    impact_on_world: int = Field(ge=1, le=5)
    impact_on_financials: int = Field(ge=1, le=5)

    @field_validator("impact_on_world", "impact_on_financials")
    @classmethod
    def _validate_range(cls, value: int) -> int:
        if not 1 <= value <= 5:
            raise ValueError("materiality ratings must be between 1 and 5")
        return value


class ScoredTopic(BaseModel):
    """An :class:`EsgTopic` after quadrant classification and ranking."""

    topic_id: str
    name: str
    impact_on_world: int
    impact_on_financials: int
    quadrant: MaterialityQuadrant
    combined_score: float
    is_material: bool


def classify_quadrant(
    impact_on_world: int, impact_on_financials: int, threshold: int
) -> MaterialityQuadrant:
    """Bucket a topic into a double-materiality quadrant given a per-axis threshold."""
    impact_material = impact_on_world >= threshold
    financial_material = impact_on_financials >= threshold
    if impact_material and financial_material:
        return MaterialityQuadrant.DOUBLE_MATERIAL
    if impact_material:
        return MaterialityQuadrant.IMPACT_MATERIAL_ONLY
    if financial_material:
        return MaterialityQuadrant.FINANCIAL_MATERIAL_ONLY
    return MaterialityQuadrant.NOT_MATERIAL


def score_topics(topics: list[EsgTopic], threshold: int = 3) -> list[ScoredTopic]:
    """Classify and rank a list of candidate ESG topics.

    A topic is considered material (``is_material=True``) if *either* axis
    meets or exceeds ``threshold`` -- i.e. any quadrant other than
    ``NOT_MATERIAL``. Results are sorted by combined score (the simple
    average of both axes) descending, so the most material topics surface
    first.
    """
    scored = []
    for topic in topics:
        quadrant = classify_quadrant(topic.impact_on_world, topic.impact_on_financials, threshold)
        combined_score = (topic.impact_on_world + topic.impact_on_financials) / 2.0
        scored.append(
            ScoredTopic(
                topic_id=topic.topic_id,
                name=topic.name,
                impact_on_world=topic.impact_on_world,
                impact_on_financials=topic.impact_on_financials,
                quadrant=quadrant,
                combined_score=combined_score,
                is_material=quadrant != MaterialityQuadrant.NOT_MATERIAL,
            )
        )
    scored.sort(key=lambda t: t.combined_score, reverse=True)
    return scored


def material_topics(scored: list[ScoredTopic]) -> list[ScoredTopic]:
    """Filter down to topics flagged as material, already ranked by score."""
    return [t for t in scored if t.is_material]
