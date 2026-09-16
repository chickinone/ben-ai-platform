"""Kho ánh xạ placeholder → giá trị gốc, dùng chung giữa hook pre_call và post_call.

- InMemoryMappingStore: một tiến trình (dev, unit test).
- RedisMappingStore: nhiều worker/pod. Giá trị mã hoá AES-256-GCM, TTL ngắn (ADR-017).
  Associated data là tên key Redis → không thể chép bản mã sang request khác.
"""

import json
import os
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol


class MappingStore(Protocol):
    async def put(self, key: str, mapping: dict[str, str]) -> None: ...

    async def get(self, key: str) -> dict[str, str]: ...


class InMemoryMappingStore:
    def __init__(self, ttl_s: float = 300, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl_s = ttl_s
        self._clock = clock
        self._items: dict[str, tuple[float, dict[str, str]]] = {}

    async def put(self, key: str, mapping: dict[str, str]) -> None:
        now = self._clock()
        self._items = {k: v for k, v in self._items.items() if now - v[0] <= self._ttl_s}
        self._items[key] = (now, dict(mapping))

    async def get(self, key: str) -> dict[str, str]:
        item = self._items.get(key)
        if item is None or self._clock() - item[0] > self._ttl_s:
            return {}
        return dict(item[1])


class AesGcmCipher:
    NONCE_SIZE = 12

    def __init__(self, key_hex: str) -> None:
        try:
            key = bytes.fromhex(key_hex)
        except ValueError as exc:
            raise ValueError("BEN_PII_STORE_KEY phải là chuỗi hex") from exc
        if len(key) != 32:
            raise ValueError("BEN_PII_STORE_KEY phải dài 64 ký tự hex (32 byte)")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes, associated_data: bytes) -> bytes:
        nonce = os.urandom(self.NONCE_SIZE)
        return nonce + self._aead.encrypt(nonce, plaintext, associated_data)

    def decrypt(self, blob: bytes, associated_data: bytes) -> bytes:
        nonce, ciphertext = blob[: self.NONCE_SIZE], blob[self.NONCE_SIZE :]
        return self._aead.decrypt(nonce, ciphertext, associated_data)


class RedisMappingStore:
    def __init__(
        self,
        client: Any,
        cipher: AesGcmCipher,
        ttl_s: int = 300,
        prefix: str = "ben:pii-map:",
    ) -> None:
        self._client = client
        self._cipher = cipher
        self._ttl_s = ttl_s
        self._prefix = prefix

    async def put(self, key: str, mapping: dict[str, str]) -> None:
        redis_key = self._prefix + key
        payload = json.dumps(mapping, ensure_ascii=False).encode("utf-8")
        blob = self._cipher.encrypt(payload, redis_key.encode("utf-8"))
        await self._client.set(redis_key, blob, ex=self._ttl_s)

    async def get(self, key: str) -> dict[str, str]:
        redis_key = self._prefix + key
        blob = await self._client.get(redis_key)
        if not blob:
            return {}
        return json.loads(self._cipher.decrypt(blob, redis_key.encode("utf-8")))


def store_from_env(environ: Mapping[str, str] = os.environ) -> MappingStore:
    url = environ.get("BEN_PII_STORE_REDIS_URL")
    if not url:
        return InMemoryMappingStore()
    key_hex = environ.get("BEN_PII_STORE_KEY")
    if not key_hex:
        raise RuntimeError(
            "Có BEN_PII_STORE_REDIS_URL nhưng thiếu BEN_PII_STORE_KEY: "
            "không lưu giá trị gốc lên Redis khi chưa mã hoá"
        )
    import redis.asyncio as redis

    return RedisMappingStore(
        redis.Redis.from_url(url),
        AesGcmCipher(key_hex),
        ttl_s=int(environ.get("BEN_PII_STORE_TTL_S", "300")),
    )
