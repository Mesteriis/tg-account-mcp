import json
from unittest.mock import Mock

from tg_mcp.errors import LocalError
from tg_mcp.storage import StateStore
from tg_mcp.telemetry import TelemetryStore


def test_telemetry_persists_only_bounded_operation_metadata(tmp_path):
    store = StateStore(tmp_path)
    telemetry = TelemetryStore(store, max_events=2)

    telemetry.record(
        "get_chat_history",
        identity_id="acct_aaaaaaaaaaaaaaaa",
        chat_id="-100123",
        duration_ms=125,
    )
    telemetry.record(
        "send_as_user",
        identity_id="acct_aaaaaaaaaaaaaaaa",
        chat_id="456",
        status="error",
        error_code="rate_limited",
        duration_ms=240,
    )
    telemetry.record(
        "search_messages",
        identity_id="not-an-identity",
        chat_id="not-a-chat",
        duration_ms=12,
    )

    persisted = json.loads((tmp_path / "operations.json").read_text())
    assert len(persisted["events"]) == 2
    assert all("text" not in event and "query" not in event for event in persisted["events"])
    assert persisted["events"][-1]["identity_id"] is None
    assert persisted["events"][-1]["chat_id"] is None

    snapshot = TelemetryStore(store, max_events=2).snapshot(days=14)
    assert snapshot["totals"] == {
        "requests": 2,
        "read": 0,
        "search": 1,
        "send": 1,
        "errors": 1,
        "error_rate": 50.0,
    }
    assert snapshot["by_identity"][0]["identity_id"] == "acct_aaaaaaaaaaaaaaaa"
    assert sum(row["read"] + row["search"] + row["send"] for row in snapshot["hourly_series"]) == 2


def test_telemetry_has_zero_filled_series(tmp_path):
    telemetry = TelemetryStore(StateStore(tmp_path))

    snapshot = telemetry.snapshot(days=7)

    assert len(snapshot["series"]) == 7
    assert all(row["read"] == row["search"] == row["send"] == 0 for row in snapshot["series"])
    assert len(snapshot["hourly_series"]) == 24
    assert all(
        row["read"] == row["search"] == row["send"] == 0 for row in snapshot["hourly_series"]
    )
    assert snapshot["recent"] == []


def test_telemetry_write_failure_does_not_break_operation(tmp_path):
    telemetry = TelemetryStore(StateStore(tmp_path))
    telemetry.store.write_private_json = Mock(side_effect=LocalError("disk unavailable"))

    telemetry.record("get_status")

    assert telemetry.snapshot()["totals"]["requests"] == 1
