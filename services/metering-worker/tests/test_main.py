from decimal import Decimal

import pytest

from ben_metering_worker.main import InvalidUsageEvent, parse_usage_event


def event(**overrides: str) -> dict[str, str]:
    result = {
        "call_id": "call-1",
        "trace_id": "trace-1",
        "team_id": "3edc0d7b-5f10-5295-bb88-fbe0d4d324f9",
        "model": "mock-cloud-small",
        "call_type": "completion",
        "tokens_in": "12",
        "tokens_out": "7",
        "cost_usd": "0.000123",
        "cache_hit": "false",
        "start_time": "1726653600.000",
        "end_time": "1726653600.125",
    }
    result.update(overrides)
    return result


def test_parses_event_for_usage_schema():
    parsed = parse_usage_event(event(call_type="anthropic_messages", cache_hit="true"))

    assert parsed.endpoint == "/v1/messages"
    assert parsed.tokens_in == 12
    assert parsed.cost_usd == Decimal("0.000123")
    assert parsed.latency_ms == 125
    assert parsed.cache_hit is True


@pytest.mark.parametrize("field,value", [("team_id", "cskh"), ("tokens_in", "-1"), ("model", "")])
def test_rejects_invalid_event(field: str, value: str):
    with pytest.raises(InvalidUsageEvent):
        parse_usage_event(event(**{field: value}))
