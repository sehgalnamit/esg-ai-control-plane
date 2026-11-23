"""EU AI Act-aligned registry of AI systems in use.

The EU AI Act classifies AI systems into risk tiers -- ``prohibited``,
``high_risk``, ``limited_risk``, ``minimal_risk``, and a separate track for
``gpai`` (general-purpose AI models) -- with obligations that scale with
risk. This module is a lightweight registry: each AI system is tagged with
its risk tier, a checklist of required controls, and the date/owner of its
last human-oversight sign-off. High-risk systems whose sign-off has lapsed
past a configurable cadence are flagged as overdue so they surface in
governance review rather than silently drifting out of compliance.
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import Enum

from pydantic import BaseModel, Field


class AiRiskTier(str, Enum):
    """EU AI Act risk tiers."""

    PROHIBITED = "prohibited"
    HIGH_RISK = "high_risk"
    LIMITED_RISK = "limited_risk"
    MINIMAL_RISK = "minimal_risk"
    GPAI = "gpai"


# Default maximum number of days between human-oversight sign-offs for a
# high-risk system before it is considered overdue. Configurable per call.
DEFAULT_HIGH_RISK_SIGNOFF_CADENCE_DAYS = 90


class AiSystem(BaseModel):
    """One AI system entry in the registry."""

    system_id: str
    name: str
    risk_tier: AiRiskTier
    required_controls: list[str] = Field(default_factory=list)
    controls_completed: list[str] = Field(default_factory=list)
    last_signoff_date: date | None = None
    last_signoff_owner: str | None = None


class AiSystemStatus(BaseModel):
    """A registry entry plus derived compliance flags."""

    system_id: str
    name: str
    risk_tier: AiRiskTier
    missing_controls: list[str]
    is_prohibited: bool
    signoff_overdue: bool
    days_since_signoff: int | None
    issues: list[str]


def _missing_controls(system: AiSystem) -> list[str]:
    completed = set(system.controls_completed)
    return [c for c in system.required_controls if c not in completed]


def evaluate_system(
    system: AiSystem,
    *,
    as_of: date | None = None,
    high_risk_signoff_cadence_days: int = DEFAULT_HIGH_RISK_SIGNOFF_CADENCE_DAYS,
) -> AiSystemStatus:
    """Evaluate one AI system's compliance status against the AI Act tiers."""
    as_of = as_of or date.today()
    missing = _missing_controls(system)
    is_prohibited = system.risk_tier == AiRiskTier.PROHIBITED

    days_since_signoff: int | None = None
    signoff_overdue = False
    issues: list[str] = []

    if is_prohibited:
        issues.append("prohibited_system_in_use")

    if system.risk_tier == AiRiskTier.HIGH_RISK:
        if system.last_signoff_date is None:
            signoff_overdue = True
            issues.append("missing_human_oversight_signoff")
        else:
            days_since_signoff = (as_of - system.last_signoff_date).days
            if days_since_signoff > high_risk_signoff_cadence_days:
                signoff_overdue = True
                issues.append("human_oversight_signoff_overdue")

    if missing:
        issues.append("missing_required_controls")

    return AiSystemStatus(
        system_id=system.system_id,
        name=system.name,
        risk_tier=system.risk_tier,
        missing_controls=missing,
        is_prohibited=is_prohibited,
        signoff_overdue=signoff_overdue,
        days_since_signoff=days_since_signoff,
        issues=issues,
    )


def evaluate_registry(
    systems: list[AiSystem],
    *,
    as_of: date | None = None,
    high_risk_signoff_cadence_days: int = DEFAULT_HIGH_RISK_SIGNOFF_CADENCE_DAYS,
) -> list[AiSystemStatus]:
    """Evaluate every system in a registry."""
    return [
        evaluate_system(s, as_of=as_of, high_risk_signoff_cadence_days=high_risk_signoff_cadence_days)
        for s in systems
    ]


def overdue_high_risk_systems(statuses: list[AiSystemStatus]) -> list[AiSystemStatus]:
    """Filter to high-risk systems overdue for a human-oversight sign-off."""
    return [s for s in statuses if s.risk_tier == AiRiskTier.HIGH_RISK and s.signoff_overdue]


def next_signoff_due_date(
    system: AiSystem, cadence_days: int = DEFAULT_HIGH_RISK_SIGNOFF_CADENCE_DAYS
) -> date | None:
    """Compute when a system's next human-oversight sign-off is due, if applicable."""
    if system.last_signoff_date is None:
        return None
    return system.last_signoff_date + timedelta(days=cadence_days)
