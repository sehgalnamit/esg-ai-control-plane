"""FastAPI demo surface wiring the control-plane modules together end to end.

This app is deliberately thin: every real calculation lives in the library
modules under ``pipeline/``, ``finops_greenops/``, ``materiality/``,
``taxonomy/``, ``governance/``, ``claims/``, ``federation/``,
``scheduling/``, ``supply_chain/``, and ``reporting/``. The endpoints here
just parse requests, call those modules, and return their Pydantic models as
JSON -- see the README "Demo Script" section for curl examples that
reproduce the full ingest -> quality-check -> GAR -> claim-verification ->
audit-packet flow described in the project pitch.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from claims.greenwashing_claim_verifier import ClaimVerdict, verify_claim
from evaluator.cascade import ConfidenceGatedCascade
from federation.subsidiary_query_layer import (
    FederationLayer,
    RegionAggregate,
    SubsidiaryMetricRow,
    seed_subsidiary_db,
)
from governance.ai_act_system_registry import AiSystem, AiSystemStatus, evaluate_registry
from governance.audit_chain import AuditChain, ChainVerificationResult
from governance.bias_fairness_harness import FairnessReport, GroupScore, evaluate_fairness
from materiality.double_materiality_scorer import EsgTopic, ScoredTopic, score_topics
from pipeline.ingest_and_normalize import GovernedEnergyRecord, ingest_csv, ingest_rows
from reporting.build_audit_packet import AuditPacket, build_audit_packet
from scheduling.carbon_aware_scheduler import (
    CarbonForecastPoint,
    Job,
    ScheduleDecision,
    find_lowest_carbon_schedule,
)
from taxonomy.gar_eu_taxonomy_calculator import CounterpartyExposure, GarResult, compute_gar

# --- Shared, in-process state for this demo app --------------------------
# A single audit chain for the life of the process (every claim-verification
# and audit-packet call appends to it), and a federation layer seeded with a
# couple of simulated subsidiary DuckDB files at startup.

_AUDIT_CHAIN = AuditChain()
_CASCADE = ConfidenceGatedCascade()
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_FEDERATION_DIR = Path(tempfile.gettempdir()) / "esg_ai_control_plane_federation_demo"
_FEDERATION: FederationLayer | None = None


def _seed_federation_demo() -> FederationLayer:
    """Seed two simulated per-subsidiary DuckDB files and attach them read-only."""
    _FEDERATION_DIR.mkdir(parents=True, exist_ok=True)

    seed_subsidiary_db(
        _FEDERATION_DIR / "subsidiary_eu.duckdb",
        [
            SubsidiaryMetricRow(
                metric_id="eu-1",
                region="EU-DE",
                quarter="2026Q1",
                kwh=18130.0,
                kg_co2e=6889.4,
                cost_usd=7252.0,
            ),
            SubsidiaryMetricRow(
                metric_id="eu-2",
                region="EU-FR",
                quarter="2026Q1",
                kwh=15300.0,
                kg_co2e=856.8,
                cost_usd=3519.0,
            ),
        ],
    )
    seed_subsidiary_db(
        _FEDERATION_DIR / "subsidiary_apac.duckdb",
        [
            SubsidiaryMetricRow(
                metric_id="apac-1",
                region="APAC-SG",
                quarter="2026Q1",
                kwh=4100.0,
                kg_co2e=1672.8,
                cost_usd=1066.0,
            ),
            SubsidiaryMetricRow(
                metric_id="apac-2",
                region="APAC-IN",
                quarter="2026Q1",
                kwh=6210.0,
                kg_co2e=4396.7,
                cost_usd=558.9,
            ),
        ],
    )

    layer = FederationLayer()
    layer.attach_subsidiary(_FEDERATION_DIR / "subsidiary_eu.duckdb", "subsidiary_eu")
    layer.attach_subsidiary(_FEDERATION_DIR / "subsidiary_apac.duckdb", "subsidiary_apac")
    return layer


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    global _FEDERATION
    _FEDERATION = _seed_federation_demo()
    yield
    if _FEDERATION is not None:
        _FEDERATION.close()


app = FastAPI(
    title="ESG AI Control Plane",
    description=(
        "A runnable demonstration that ESG reporting is an engineering discipline: "
        "lineage, FinOps/GreenOps telemetry, and AI governance solved inside the "
        "systems that run the business."
    ),
    version="0.1.0",
    lifespan=_lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- 1. Ingestion & quality -------------------------------------------------


@app.post("/ingest", response_model=list[GovernedEnergyRecord])
def ingest(rows: list[dict[str, Any]] | None = None) -> list[GovernedEnergyRecord]:
    """Ingest and normalize utility-event rows, preserving lineage and quality flags.

    If no ``rows`` are supplied in the request body, ingests the bundled
    sample ``data/utility_events.csv`` so the endpoint is curl-able with no
    body at all.
    """
    if rows is not None:
        return ingest_rows(rows)
    return ingest_csv(_DATA_DIR / "utility_events.csv")


# --- 2. Double materiality --------------------------------------------------


@app.post("/materiality/score", response_model=list[ScoredTopic])
def score_materiality(topics: list[EsgTopic], threshold: int = 3) -> list[ScoredTopic]:
    return score_topics(topics, threshold=threshold)


# --- 3. EU Taxonomy / Green Asset Ratio -------------------------------------


@app.post("/taxonomy/gar", response_model=GarResult)
def taxonomy_gar(exposures: list[CounterpartyExposure]) -> GarResult:
    return compute_gar(exposures)


# --- 4. AI Act system registry -----------------------------------------------


@app.post("/governance/ai-act/evaluate", response_model=list[AiSystemStatus])
def ai_act_evaluate(systems: list[AiSystem]) -> list[AiSystemStatus]:
    return evaluate_registry(systems)


# --- 5. Bias / fairness harness ---------------------------------------------


@app.post("/governance/bias/evaluate", response_model=FairnessReport)
def bias_evaluate(scores: list[GroupScore], disparate_impact_threshold: float = 0.8) -> FairnessReport:
    return evaluate_fairness(scores, disparate_impact_threshold=disparate_impact_threshold)


# --- 6. Greenwashing claim verifier (confidence-gated Jev + jury cascade) ---


class ClaimRequest(BaseModel):
    claim: str
    sources: list[GovernedEnergyRecord]
    high_stakes: bool = False


@app.post("/claims/verify", response_model=ClaimVerdict)
def claims_verify(request: ClaimRequest) -> ClaimVerdict:
    return verify_claim(
        request.claim,
        request.sources,
        _CASCADE,
        _AUDIT_CHAIN,
        high_stakes=request.high_stakes,
    )


# --- 7. Zero-copy subsidiary federation --------------------------------------


@app.get("/federation/region-summary", response_model=list[RegionAggregate])
def federation_region_summary() -> list[RegionAggregate]:
    assert _FEDERATION is not None
    return _FEDERATION.cross_subsidiary_region_summary()


@app.get("/federation/global-totals")
def federation_global_totals() -> dict[str, float]:
    assert _FEDERATION is not None
    return _FEDERATION.global_totals()


# --- 8. Carbon-aware scheduling ---------------------------------------------


class ScheduleRequest(BaseModel):
    job: Job
    forecast_points: list[CarbonForecastPoint]


@app.post("/scheduling/find-window", response_model=ScheduleDecision)
def scheduling_find_window(request: ScheduleRequest) -> ScheduleDecision:
    return find_lowest_carbon_schedule(request.job, request.forecast_points)


# --- 9. Audit packet + chain verification -----------------------------------


class AuditPacketRequest(BaseModel):
    records: list[GovernedEnergyRecord]
    gar_result: GarResult
    scored_topics: list[ScoredTopic]
    claim_verdicts: list[ClaimVerdict] = []


@app.post("/reporting/audit-packet", response_model=AuditPacket)
def reporting_audit_packet(request: AuditPacketRequest) -> AuditPacket:
    return build_audit_packet(
        request.records,
        request.gar_result,
        request.scored_topics,
        request.claim_verdicts,
        _AUDIT_CHAIN,
    )


@app.get("/audit/verify", response_model=ChainVerificationResult)
def audit_verify() -> ChainVerificationResult:
    """Walk the process-lifetime audit chain and confirm it has not been tampered with."""
    return _AUDIT_CHAIN.verify_chain()


@app.get("/audit/entries")
def audit_entries() -> list[dict[str, Any]]:
    return [entry.model_dump() for entry in _AUDIT_CHAIN.entries]
