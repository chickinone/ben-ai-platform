import asyncio

import pytest

from ben_litellm_plugins.rate_limits import (
    WINDOW_SECONDS,
    consume_request,
    estimate_request_tokens,
    policy_from_metadata,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> int:
        assert numkeys == 1
        key, amount, _ttl = keys_and_args
        key = str(key)
        self.values[key] = self.values.get(key, 0) + int(str(amount))
        return self.values[key]


def test_policy_is_only_enabled_by_server_metadata():
    assert policy_from_metadata({"ben_tenant": "cskh"}) is None
    assert policy_from_metadata({"ben_tenant": "cskh", "ben_rpm_limit": 1}) is None
    assert policy_from_metadata({"ben_tenant": "cskh", "ben_rpm_limit": 1, "ben_tpm_limit": 2})


@pytest.mark.parametrize("field,value", [("ben_rpm_limit", 0), ("ben_tpm_limit", "wrong")])
def test_policy_rejects_invalid_limit(field, value):
    metadata = {"ben_tenant": "cskh", "ben_rpm_limit": 2, "ben_tpm_limit": 10}
    metadata[field] = value
    with pytest.raises(ValueError):
        policy_from_metadata(metadata)


def test_shared_counter_rejects_second_request_from_another_worker():
    async def scenario():
        policy = policy_from_metadata(
            {"ben_tenant": "cskh", "ben_rpm_limit": 1, "ben_tpm_limit": 10_000}
        )
        assert policy is not None
        redis = FakeRedis()
        first = await consume_request(redis, policy, {"messages": [{"content": "one"}]}, now=120)
        second = await consume_request(redis, policy, {"messages": [{"content": "two"}]}, now=120)
        return first, second

    assert asyncio.run(scenario()) == ((True, None), (False, "rpm"))


def test_counter_resets_in_next_minute_bucket():
    async def scenario():
        policy = policy_from_metadata(
            {"ben_tenant": "finance", "ben_rpm_limit": 1, "ben_tpm_limit": 10_000}
        )
        assert policy is not None
        redis = FakeRedis()
        before = await consume_request(redis, policy, {"prompt": "one"}, now=0)
        after = await consume_request(redis, policy, {"prompt": "two"}, now=WINDOW_SECONDS)
        return before, after

    assert asyncio.run(scenario()) == ((True, None), (True, None))


def test_tpm_estimate_includes_a_safe_default_completion_budget():
    assert estimate_request_tokens({"messages": [{"content": "hello"}]}) >= 256
