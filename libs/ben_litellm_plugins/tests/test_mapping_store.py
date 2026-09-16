import asyncio

import pytest

from ben_litellm_plugins.mapping_store import (
    AesGcmCipher,
    InMemoryMappingStore,
    RedisMappingStore,
    store_from_env,
)

KEY_HEX = "11" * 32
MAPPING = {"<PHONE_1>": "0912 345 678"}


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.ttl: dict[str, int] = {}

    async def set(self, key: str, value: bytes, ex: int) -> None:
        self.data[key] = value
        self.ttl[key] = ex

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)


def test_in_memory_store_expires_after_ttl():
    now = [0.0]
    store = InMemoryMappingStore(ttl_s=10, clock=lambda: now[0])
    asyncio.run(store.put("call-1", MAPPING))
    now[0] = 5
    assert asyncio.run(store.get("call-1")) == MAPPING
    now[0] = 11
    assert asyncio.run(store.get("call-1")) == {}


def test_redis_store_encrypts_with_ttl_and_round_trips():
    pytest.importorskip("cryptography")
    fake = FakeRedis()
    store = RedisMappingStore(fake, AesGcmCipher(KEY_HEX), ttl_s=60)

    asyncio.run(store.put("call-1", MAPPING))

    raw = fake.data["ben:pii-map:call-1"]
    assert b"0912" not in raw and b"PHONE" not in raw
    assert fake.ttl["ben:pii-map:call-1"] == 60
    assert asyncio.run(store.get("call-1")) == MAPPING
    assert asyncio.run(store.get("missing")) == {}


def test_ciphertext_cannot_be_replayed_under_another_key():
    pytest.importorskip("cryptography")
    from cryptography.exceptions import InvalidTag

    fake = FakeRedis()
    store = RedisMappingStore(fake, AesGcmCipher(KEY_HEX))
    asyncio.run(store.put("call-1", MAPPING))
    fake.data["ben:pii-map:call-2"] = fake.data["ben:pii-map:call-1"]

    with pytest.raises(InvalidTag):
        asyncio.run(store.get("call-2"))


@pytest.mark.parametrize("bad_key", ["abcd", "zz" * 32])
def test_cipher_rejects_invalid_keys(bad_key):
    with pytest.raises(ValueError):
        AesGcmCipher(bad_key)


def test_store_from_env_defaults_to_memory_and_requires_key_for_redis():
    assert isinstance(store_from_env({}), InMemoryMappingStore)
    with pytest.raises(RuntimeError, match="BEN_PII_STORE_KEY"):
        store_from_env({"BEN_PII_STORE_REDIS_URL": "redis://localhost:6379/2"})
