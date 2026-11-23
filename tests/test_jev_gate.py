"""Tests for the Jev gate contract, confidence math, and the offline stand-in."""

from __future__ import annotations

import os

import pytest

from evaluator.jev_gate import (
    JevQuestion,
    LocalJevStandIn,
    TypeSafeJevClient,
    choice_confidence,
    get_default_jev_client,
    noul_confidence,
    score_confidence,
)


def test_noul_confidence_at_extremes_and_midpoint():
    assert noul_confidence(0.5) == 0.0
    assert noul_confidence(1.0) == pytest.approx(1.0)
    assert noul_confidence(0.0) == pytest.approx(1.0)


def test_choice_confidence_two_options_formula():
    # n=2: confidence = 2*p_max - 1
    assert choice_confidence({"a": 0.5, "b": 0.5}) == pytest.approx(0.0)
    assert choice_confidence({"a": 1.0, "b": 0.0}) == pytest.approx(1.0)
    assert choice_confidence({"a": 0.75, "b": 0.25}) == pytest.approx(0.5)


def test_choice_confidence_single_option_is_fully_confident():
    assert choice_confidence({"only": 1.0}) == 1.0


def test_score_confidence_peaked_distribution_is_high_confidence():
    levels = [1.0, 2.0, 3.0, 4.0, 5.0]
    peaked = [0.0, 0.0, 1.0, 0.0, 0.0]
    score, confidence = score_confidence(levels, peaked)
    assert score == 3.0
    assert confidence == pytest.approx(1.0)


def test_score_confidence_uniform_distribution_is_zero_confidence():
    levels = [1.0, 2.0, 3.0, 4.0, 5.0]
    uniform = [0.2, 0.2, 0.2, 0.2, 0.2]
    _, confidence = score_confidence(levels, uniform)
    assert confidence == pytest.approx(0.0, abs=1e-9)


def test_local_stand_in_noul_high_overlap_yields_high_noul():
    client = LocalJevStandIn()
    question = JevQuestion(
        type="noul",
        instructions="is the claim supported?",
        criteria={"reference_text": "the plant used 15230 kwh in region eu de"},
    )
    answers = client.ask("the plant used 15230 kwh in region eu de", {"q1": question})
    assert answers["q1"].type == "noul"
    assert answers["q1"].noul == pytest.approx(1.0)


def test_local_stand_in_noul_no_overlap_yields_low_noul():
    client = LocalJevStandIn()
    question = JevQuestion(
        type="noul",
        instructions="is the claim supported?",
        criteria={"reference_text": "completely unrelated reference text about something else"},
    )
    answers = client.ask("totally different claim with zero shared words whatsoever", {"q1": question})
    assert answers["q1"].noul < 0.2


def test_local_stand_in_choice_returns_valid_distribution():
    client = LocalJevStandIn()
    question = JevQuestion(
        type="choice", instructions="pick one", criteria={"options": ["red", "green", "blue"]}
    )
    answers = client.ask("some state", {"q1": question})
    answer = answers["q1"]
    assert answer.type == "choice"
    assert answer.choice in {"red", "green", "blue"}
    assert abs(sum(answer.probabilities.values()) - 1.0) < 1e-9
    assert 0.0 <= answer.confidence <= 1.0


def test_local_stand_in_score_returns_valid_score():
    client = LocalJevStandIn()
    question = JevQuestion(type="score", instructions="rate it", criteria={"levels": [1, 2, 3, 4, 5]})
    answers = client.ask("some state", {"q1": question})
    answer = answers["q1"]
    assert answer.type == "score"
    assert 1.0 <= answer.score <= 5.0
    assert 0.0 <= answer.confidence <= 1.0


def test_local_stand_in_is_deterministic():
    client = LocalJevStandIn()
    question = JevQuestion(type="choice", instructions="pick", criteria={"options": ["a", "b"]})
    first = client.ask("state-x", {"q1": question})
    second = client.ask("state-x", {"q1": question})
    assert first["q1"].probabilities == second["q1"].probabilities


def test_typesafe_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        TypeSafeJevClient()


def test_get_default_jev_client_returns_local_stand_in_without_api_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    client = get_default_jev_client()
    assert isinstance(client, LocalJevStandIn)


def test_get_default_jev_client_returns_typesafe_client_with_api_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    client = get_default_jev_client()
    assert isinstance(client, TypeSafeJevClient)
    assert os.environ["TYPESAFE_API_KEY"] == "test-key"
