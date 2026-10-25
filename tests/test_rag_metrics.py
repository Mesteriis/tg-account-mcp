import pytest

from tg_mcp.rag_metrics import RAGMetrics

SCOPE = ("model", (("account", "chat"),), ("account",))


def sample_window(metrics, *, incoming=2, processed=5):
    for t in range(0, 61, 10):
        metrics.observe(t, SCOPE, 1000 + incoming * t, 100 + processed * t, processed * t)


def test_eta_uses_net_queue_drain_and_background_processing_rate():
    metrics = RAGMetrics()
    sample_window(metrics)
    result = metrics.snapshot(60, SCOPE, 720)
    assert result["index_per_second"] == 5
    assert result["incoming_per_second"] == 2
    assert result["queue_per_second"] == -3
    assert result["queue_change"] == -180
    assert result["eta_seconds"] == 240
    assert result["state"] == "draining"


@pytest.mark.parametrize("incoming,state", [(5, "stalled"), (7, "growing")])
def test_non_shrinking_queue_has_no_eta(incoming, state):
    metrics = RAGMetrics()
    sample_window(metrics, incoming=incoming)
    result = metrics.snapshot(60, SCOPE, 900)
    assert result["state"] == state
    assert result["eta_seconds"] is None


def test_warmup_stale_paused_blocked_and_empty_queue():
    metrics = RAGMetrics()
    assert metrics.snapshot(0, SCOPE, 900)["state"] == "warming"
    metrics.observe(0, SCOPE, 1000, 100, 0)
    assert metrics.snapshot(20, SCOPE, 900)["index_per_second"] is None
    sample_window(metrics)
    assert metrics.snapshot(91, SCOPE, 700)["state"] == "stale"
    assert metrics.snapshot(60, SCOPE, 700, paused=True)["state"] == "paused"
    blocked = metrics.snapshot(60, SCOPE, 700, blocked=True)
    assert blocked["state"] == "blocked" and blocked["eta_seconds"] is None
    complete = metrics.snapshot(60, SCOPE, 0)
    assert complete["state"] == "complete" and complete["eta_seconds"] == 0


@pytest.mark.parametrize("change", ["model", "scope", "purge", "gap", "counter"])
def test_discontinuities_reset_the_window(change):
    metrics = RAGMetrics()
    sample_window(metrics)
    scope, stamp, eligible, indexed, processed = SCOPE, 70, 1140, 450, 350
    if change in ["model", "scope"]:
        scope = (change, (), ())
    elif change == "purge":
        eligible = 900
    elif change == "gap":
        stamp = 100
    else:
        processed = 0
    metrics.observe(stamp, scope, eligible, indexed, processed)
    assert metrics.snapshot(stamp, scope, eligible - indexed)["state"] == "warming"
    assert len(metrics.samples) == 1


def test_history_is_bounded_and_rates_use_recent_window():
    metrics = RAGMetrics()
    for t in range(0, 601, 10):
        metrics.observe(t, SCOPE, 10000, 1000 + t, t if t < 500 else 500 + 2 * (t - 500))
    result = metrics.snapshot(600, SCOPE, 8400)
    assert len(metrics.samples) <= 32
    assert result["window_seconds"] == 60
    assert result["index_per_second"] == 2
    assert result["history"][0]["age_seconds"] == 300

    assert max(p["age_seconds"] for p in metrics.snapshot(610, SCOPE, 8400)["history"]) <= 300
