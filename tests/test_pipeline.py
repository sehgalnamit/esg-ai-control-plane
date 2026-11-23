"""Tests for pipeline ingestion, normalization, and data-quality flagging."""

from __future__ import annotations

from pathlib import Path

from pipeline.ingest_and_normalize import ingest_csv, ingest_row, ingest_rows, normalize_to_kwh
from pipeline.quality_checks import (
    ISSUE_MISSING_OWNER,
    ISSUE_NEGATIVE_KWH,
    ISSUE_UNMAPPED_REGION,
    carbon_intensity_for,
)

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "utility_events.csv"


def test_normalize_to_kwh_handles_mwh_and_kwh():
    assert normalize_to_kwh(1, "MWh") == 1000.0
    assert normalize_to_kwh(42, "kWh") == 42.0


def test_normalize_to_kwh_rejects_unknown_unit():
    import pytest

    with pytest.raises(ValueError):
        normalize_to_kwh(1, "therms")


def test_ingest_row_flags_missing_owner():
    row = {
        "event_id": "EVT-X",
        "source_ref": "meter://x",
        "owner": "",
        "region": "EU-DE",
        "kwh": "100",
        "unit": "kWh",
    }
    record = ingest_row(row)
    assert ISSUE_MISSING_OWNER in record.issues
    assert record.status == "flagged"
    assert record.source_ref == "meter://x"


def test_ingest_row_flags_negative_kwh_but_keeps_record():
    row = {
        "event_id": "EVT-Y",
        "source_ref": "meter://y",
        "owner": "team-a",
        "region": "US-PJM",
        "kwh": "-50",
        "unit": "kWh",
    }
    record = ingest_row(row)
    assert ISSUE_NEGATIVE_KWH in record.issues
    assert record.kwh == -50.0
    # Never silently dropped: the record is still returned.
    assert record.event_id == "EVT-Y"


def test_ingest_row_flags_unmapped_region_and_uses_fallback_intensity():
    row = {
        "event_id": "EVT-Z",
        "source_ref": "meter://z",
        "owner": "team-b",
        "region": "XX-UNKNOWN",
        "kwh": "10",
        "unit": "kWh",
    }
    record = ingest_row(row)
    assert ISSUE_UNMAPPED_REGION in record.issues
    assert record.estimated_kg_co2e > 0


def test_ingest_row_converts_mwh_to_kwh():
    row = {
        "event_id": "EVT-W",
        "source_ref": "meter://w",
        "owner": "team-c",
        "region": "EU-FR",
        "kwh": "2.5",
        "unit": "MWh",
    }
    record = ingest_row(row)
    assert record.kwh == 2500.0
    assert record.status == "ok"
    assert record.issues == []
    expected_co2e = 2500.0 * carbon_intensity_for("EU-FR")
    assert abs(record.estimated_kg_co2e - expected_co2e) < 1e-9


def test_ingest_rows_preserves_count():
    rows = [
        {
            "event_id": "EVT-A",
            "source_ref": "meter://a",
            "owner": "team-a",
            "region": "EU-DE",
            "kwh": "1",
            "unit": "kWh",
        },
        {
            "event_id": "EVT-B",
            "source_ref": "meter://b",
            "owner": "",
            "region": "",
            "kwh": "-1",
            "unit": "kWh",
        },
    ]
    records = ingest_rows(rows)
    assert len(records) == 2


def test_ingest_csv_reads_sample_data_and_flags_known_bad_rows():
    records = ingest_csv(DATA_PATH)
    by_id = {r.event_id: r for r in records}

    assert len(records) == 8
    assert ISSUE_MISSING_OWNER in by_id["EVT-0004"].issues
    assert ISSUE_NEGATIVE_KWH in by_id["EVT-0005"].issues
    assert ISSUE_UNMAPPED_REGION in by_id["EVT-0006"].issues

    # MWh rows normalized correctly.
    assert by_id["EVT-0002"].kwh == 12400.0
    assert by_id["EVT-0007"].kwh == 2900.0

    # Every source row is preserved with its source_ref intact.
    assert all(r.source_ref for r in records)
