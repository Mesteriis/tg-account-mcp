from types import SimpleNamespace

import pytest

from tg_mcp.archive import ArchiveStore
from tg_mcp.errors import GatewayError
from tg_mcp.loading import AdaptiveLoading
from tg_mcp.storage import StateStore


@pytest.fixture
def loader(tmp_path):
    clock = SimpleNamespace(now=10000.0)

    async def sleep(seconds):
        clock.now += seconds

    return AdaptiveLoading(
        ArchiveStore(StateStore(tmp_path)), "account-a", clock=lambda: clock.now, sleep=sleep
    ), clock


async def test_flood_wait_persists_and_does_not_block_other_accounts(loader):
    policy, clock = loader
    with pytest.raises(GatewayError, match="rate_limited"):
        async with policy.request():
            raise GatewayError("rate_limited", "Wait", 180)
    assert policy.state()["interval"] == 4
    reopened = AdaptiveLoading(policy.archive, policy.account, clock=lambda: clock.now)
    with pytest.raises(GatewayError, match="load_paused"):
        async with reopened.request():
            pytest.fail("Server cooldown was ignored")
    assert reopened.state()["limits"] == 1
    other = AdaptiveLoading(policy.archive, "account-b", clock=lambda: clock.now)
    async with other.request():
        pass
    clock.now += 181
    async with policy.request():
        pass
    assert policy.state()["interval"] == 4


async def test_two_hours_of_active_success_reduce_gradually_but_idle_does_not(loader):
    policy, clock = loader
    state = policy.state()
    state["interval"] = 20
    policy.save(state)
    async with policy.request():
        pass
    clock.now += 7201
    async with policy.request():
        pass
    assert policy.state()["interval"] == 20  # Idle is not evidence of healthy throughput.
    for _ in range(25):
        clock.now += 300
        async with policy.request():
            pass
    assert policy.state()["interval"] == 16
    assert policy.state()["stable_since"] > 0


async def test_limit_cap_and_busy_gate(loader):
    policy, clock = loader
    for _ in range(8):
        clock.now += 1000
        with pytest.raises(GatewayError):
            async with policy.request():
                raise GatewayError("rate_limited", "Wait", 5)
    assert policy.state()["interval"] == 60
    clock.now += 1000
    async with policy.request():
        with pytest.raises(GatewayError, match="load_paused"):
            async with policy.request():
                pytest.fail("Concurrent background request entered")
    assert policy.state()["limits"] == 8


async def test_maximum_interval_still_allows_consecutive_pages(loader):
    policy, clock = loader
    state = policy.state()
    state["interval"] = 60
    policy.save(state)
    first = clock.now
    for _ in range(3):
        async with policy.request():
            pass
    assert clock.now == first + 120
