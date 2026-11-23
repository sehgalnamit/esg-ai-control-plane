"""End-to-end smoke tests for the FastAPI demo app.

These exercise the same request/response path a real caller (or the README's
curl-based Demo Script) would use, across every module wired into
``app/main.py``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def setup_module() -> None:
    client.__enter__()


def teardown_module() -> None:
    client.__exit__(None, None, None)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ingest_default_sample_data() -> None:
    response = client.post("/ingest", json=None)
    assert response.status_code == 200
    records = response.json()
    assert len(records) == 8
    # EVT-0004 has no owner in the sample CSV -- quality flag must surface, not be dropped.
    by_id = {r["event_id"]: r for r in records}
    assert "missing_owner" in by_id["EVT-0004"]["issues"]
    assert "unmapped_region" in by_id["EVT-0006"]["issues"]


def test_materiality_score() -> None:
    topics = [
        {"topic_id": "t1", "name": "Scope 1 emissions", "impact_on_world": 5, "impact_on_financials": 4},
        {"topic_id": "t2", "name": "Office recycling", "impact_on_world": 2, "impact_on_financials": 1},
    ]
    response = client.post("/materiality/score", json=topics)
    assert response.status_code == 200
    scored = response.json()
    assert scored[0]["topic_id"] == "t1"
    assert scored[0]["is_material"] is True
    assert scored[1]["is_material"] is False


def test_taxonomy_gar() -> None:
    exposures = [
        {
            "counterparty_id": "c1",
            "source_ref": "report://c1/2026",
            "exposure_type": "loan",
            "exposure_amount_usd": 1000.0,
            "taxonomy_eligible": True,
            "taxonomy_aligned_fraction": 0.5,
        },
        {
            "counterparty_id": "c2",
            "source_ref": "report://c2/2026",
            "exposure_type": "loan",
            "exposure_amount_usd": 500.0,
            "taxonomy_eligible": False,
            "taxonomy_aligned_fraction": 0.0,
        },
    ]
    response = client.post("/taxonomy/gar", json=exposures)
    assert response.status_code == 200
    result = response.json()
    assert result["eligible_exposure_usd"] == 1000.0
    assert result["green_asset_ratio"] == 0.5


def test_claim_verification_and_audit_chain() -> None:
    ingest_response = client.post("/ingest", json=None)
    sources = ingest_response.json()

    claim_response = client.post(
        "/claims/verify",
        json={
            "claim": "We reduced emissions at our plant-de-01 facility.",
            "sources": sources,
            "high_stakes": False,
        },
    )
    assert claim_response.status_code == 200
    verdict = claim_response.json()
    assert verdict["verdict"] in {"supported", "unsupported", "needs_human_review"}
    assert verdict["audit_entry_hash"]

    verify_response = client.get("/audit/verify")
    assert verify_response.status_code == 200
    assert verify_response.json()["ok"] is True


def test_federation_global_totals_only_aggregates() -> None:
    response = client.get("/federation/global-totals")
    assert response.status_code == 200
    totals = response.json()
    assert totals["total_kwh"] > 0
    assert set(totals) == {"total_kwh", "total_kg_co2e", "total_cost_usd"}


def test_scheduling_find_window() -> None:
    response = client.post(
        "/scheduling/find-window",
        json={
            "job": {
                "job_id": "job-1",
                "duration_hours": 2,
                "expected_kwh_per_hour": 10.0,
                "eligible_regions": ["EU-FR", "EU-DE"],
                "earliest_start_hour": 0,
                "deadline_hour": 4,
            },
            "forecast_points": [
                {"region": "EU-FR", "hour": h, "kg_co2e_per_kwh": 0.05} for h in range(0, 5)
            ]
            + [{"region": "EU-DE", "hour": h, "kg_co2e_per_kwh": 0.38} for h in range(0, 5)],
        },
    )
    assert response.status_code == 200
    decision = response.json()
    assert decision["feasible"] is True
    assert decision["region"] == "EU-FR"  # lower carbon-intensity region should win
