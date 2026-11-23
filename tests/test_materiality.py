"""Tests for the double-materiality scorer."""

from __future__ import annotations

import pytest

from materiality.double_materiality_scorer import (
    EsgTopic,
    MaterialityQuadrant,
    classify_quadrant,
    material_topics,
    score_topics,
)


def test_classify_quadrant_double_material():
    assert classify_quadrant(5, 5, threshold=3) == MaterialityQuadrant.DOUBLE_MATERIAL


def test_classify_quadrant_impact_only():
    assert classify_quadrant(5, 1, threshold=3) == MaterialityQuadrant.IMPACT_MATERIAL_ONLY


def test_classify_quadrant_financial_only():
    assert classify_quadrant(1, 5, threshold=3) == MaterialityQuadrant.FINANCIAL_MATERIAL_ONLY


def test_classify_quadrant_not_material():
    assert classify_quadrant(1, 2, threshold=3) == MaterialityQuadrant.NOT_MATERIAL


def test_esg_topic_rejects_out_of_range_rating():
    with pytest.raises(ValueError):
        EsgTopic(topic_id="T1", name="bad", impact_on_world=6, impact_on_financials=3)


def test_score_topics_ranks_by_combined_score_descending():
    topics = [
        EsgTopic(topic_id="T1", name="Low priority", impact_on_world=1, impact_on_financials=1),
        EsgTopic(topic_id="T2", name="Climate transition risk", impact_on_world=5, impact_on_financials=5),
        EsgTopic(topic_id="T3", name="Employee wellbeing", impact_on_world=4, impact_on_financials=2),
    ]
    scored = score_topics(topics, threshold=3)
    assert [t.topic_id for t in scored] == ["T2", "T3", "T1"]
    assert scored[0].quadrant == MaterialityQuadrant.DOUBLE_MATERIAL
    assert scored[1].quadrant == MaterialityQuadrant.IMPACT_MATERIAL_ONLY
    assert scored[2].quadrant == MaterialityQuadrant.NOT_MATERIAL


def test_material_topics_filters_out_not_material():
    topics = [
        EsgTopic(topic_id="T1", name="Low priority", impact_on_world=1, impact_on_financials=1),
        EsgTopic(topic_id="T2", name="Climate transition risk", impact_on_world=5, impact_on_financials=5),
    ]
    scored = score_topics(topics, threshold=3)
    material = material_topics(scored)
    assert len(material) == 1
    assert material[0].topic_id == "T2"
