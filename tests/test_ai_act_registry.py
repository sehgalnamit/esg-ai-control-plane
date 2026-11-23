"""Tests for the EU AI Act system registry module."""

from __future__ import annotations

from datetime import date, timedelta

from governance.ai_act_system_registry import (
    AiRiskTier,
    AiSystem,
    evaluate_registry,
    evaluate_system,
    next_signoff_due_date,
    overdue_high_risk_systems,
)

TODAY = date(2026, 6, 1)


def test_prohibited_system_flagged():
    system = AiSystem(system_id="S1", name="Social scoring tool", risk_tier=AiRiskTier.PROHIBITED)
    status = evaluate_system(system, as_of=TODAY)
    assert status.is_prohibited is True
    assert "prohibited_system_in_use" in status.issues


def test_high_risk_system_with_recent_signoff_is_not_overdue():
    system = AiSystem(
        system_id="S2",
        name="Credit scoring model",
        risk_tier=AiRiskTier.HIGH_RISK,
        required_controls=["bias_audit", "human_oversight_plan"],
        controls_completed=["bias_audit", "human_oversight_plan"],
        last_signoff_date=TODAY - timedelta(days=10),
        last_signoff_owner="risk-team",
    )
    status = evaluate_system(system, as_of=TODAY, high_risk_signoff_cadence_days=90)
    assert status.signoff_overdue is False
    assert status.missing_controls == []


def test_high_risk_system_overdue_for_signoff_is_flagged():
    system = AiSystem(
        system_id="S3",
        name="Hiring screening model",
        risk_tier=AiRiskTier.HIGH_RISK,
        required_controls=["bias_audit"],
        controls_completed=["bias_audit"],
        last_signoff_date=TODAY - timedelta(days=200),
        last_signoff_owner="risk-team",
    )
    status = evaluate_system(system, as_of=TODAY, high_risk_signoff_cadence_days=90)
    assert status.signoff_overdue is True
    assert "human_oversight_signoff_overdue" in status.issues


def test_high_risk_system_missing_signoff_entirely_is_overdue():
    system = AiSystem(system_id="S4", name="Unsigned-off model", risk_tier=AiRiskTier.HIGH_RISK)
    status = evaluate_system(system, as_of=TODAY)
    assert status.signoff_overdue is True
    assert "missing_human_oversight_signoff" in status.issues


def test_missing_required_controls_flagged():
    system = AiSystem(
        system_id="S5",
        name="Minimal risk chatbot",
        risk_tier=AiRiskTier.MINIMAL_RISK,
        required_controls=["transparency_notice"],
        controls_completed=[],
    )
    status = evaluate_system(system, as_of=TODAY)
    assert status.missing_controls == ["transparency_notice"]
    assert "missing_required_controls" in status.issues


def test_overdue_high_risk_systems_filters_correctly():
    systems = [
        AiSystem(
            system_id="S3",
            name="Overdue",
            risk_tier=AiRiskTier.HIGH_RISK,
            last_signoff_date=TODAY - timedelta(days=200),
        ),
        AiSystem(
            system_id="S2",
            name="On time",
            risk_tier=AiRiskTier.HIGH_RISK,
            last_signoff_date=TODAY - timedelta(days=10),
        ),
        AiSystem(system_id="S6", name="GPAI model", risk_tier=AiRiskTier.GPAI),
    ]
    statuses = evaluate_registry(systems, as_of=TODAY, high_risk_signoff_cadence_days=90)
    overdue = overdue_high_risk_systems(statuses)
    assert [s.system_id for s in overdue] == ["S3"]


def test_next_signoff_due_date():
    system = AiSystem(
        system_id="S2",
        name="Credit scoring model",
        risk_tier=AiRiskTier.HIGH_RISK,
        last_signoff_date=date(2026, 1, 1),
    )
    assert next_signoff_due_date(system, cadence_days=90) == date(2026, 1, 1) + timedelta(days=90)


def test_next_signoff_due_date_none_without_prior_signoff():
    system = AiSystem(system_id="S4", name="No signoff", risk_tier=AiRiskTier.HIGH_RISK)
    assert next_signoff_due_date(system) is None
