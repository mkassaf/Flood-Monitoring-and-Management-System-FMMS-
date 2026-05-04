"""Unit tests for RedundancyTracker using a mock Redis client."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from rule_engine.redundancy_tracker import RedundancyTracker


def _make_redis(initial_count: int = 2, fault_count: int = 0) -> MagicMock:
    redis = MagicMock()
    redis.incr = AsyncMock(side_effect=lambda key: fault_count + 1)
    redis.expire = AsyncMock()
    redis.get = AsyncMock(return_value=str(fault_count) if fault_count > 0 else None)
    redis.delete = AsyncMock()

    # Track decrement calls
    counts = {"val": initial_count}

    async def decr(key: str) -> int:
        counts["val"] -= 1
        return counts["val"]

    async def incr_op(key: str) -> int:
        counts["val"] += 1
        return counts["val"]

    async def set_op(key: str, val: int, nx: bool = False) -> None:
        pass

    redis.decr = AsyncMock(side_effect=decr)
    redis.set = AsyncMock(side_effect=set_op)
    return redis


@pytest.mark.asyncio
async def test_single_sensor_fault_causes_high_malfunction():
    redis = _make_redis(initial_count=1, fault_count=0)
    # incr returns 1 (first fault), decr returns 0
    redis.incr = AsyncMock(return_value=1)
    counts = {"val": 1}
    async def decr(k): counts["val"] -= 1; return counts["val"]
    redis.decr = AsyncMock(side_effect=decr)

    tracker = RedundancyTracker(redis_client=redis)
    alerts = await tracker.on_sensor_reading(
        sensor_id="s1", area_id="a1", parameters=["water_level_m"], status=0, ts_event="2024-01-01T00:00:00+00:00"
    )
    assert len(alerts) == 2  # malfunction + priority
    kinds = {a.kind for a in alerts}
    assert "malfunction" in kinds
    assert "priority" in kinds
    assert all(a.severity == "high" for a in alerts)


@pytest.mark.asyncio
async def test_two_sensors_one_fault_low_malfunction():
    redis = _make_redis(initial_count=2, fault_count=0)
    redis.incr = AsyncMock(return_value=1)
    counts = {"val": 2}
    async def decr(k): counts["val"] -= 1; return counts["val"]
    redis.decr = AsyncMock(side_effect=decr)

    tracker = RedundancyTracker(redis_client=redis)
    alerts = await tracker.on_sensor_reading(
        sensor_id="s1", area_id="a1", parameters=["water_level_m"], status=0, ts_event="2024-01-01T00:00:00+00:00"
    )
    assert len(alerts) == 1
    assert alerts[0].kind == "malfunction"
    assert alerts[0].severity == "low"


@pytest.mark.asyncio
async def test_recovery_emits_no_alert():
    redis = MagicMock()
    redis.get = AsyncMock(return_value="1")  # prior fault count
    redis.delete = AsyncMock()
    redis.incr = AsyncMock(return_value=1)

    tracker = RedundancyTracker(redis_client=redis)
    alerts = await tracker.on_sensor_reading(
        sensor_id="s1", area_id="a1", parameters=["water_level_m"], status=1, ts_event="2024-01-01T00:00:00+00:00"
    )
    assert alerts == []
    redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_second_consecutive_fault_does_not_decrement_again():
    redis = MagicMock()
    redis.incr = AsyncMock(return_value=2)  # Second fault → fault_count=2, not 1
    redis.expire = AsyncMock()

    tracker = RedundancyTracker(redis_client=redis)
    alerts = await tracker.on_sensor_reading(
        sensor_id="s1", area_id="a1", parameters=["water_level_m"], status=0, ts_event="2024-01-01T00:00:00+00:00"
    )
    assert alerts == []  # No decrement on repeated faults
