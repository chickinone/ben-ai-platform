"""Plugin của Bến cho LiteLLM Proxy (ADR-017).

Module thuần (không import LiteLLM): pii, streaming, governance, metering, mapping_store.
Module gắn vào LiteLLM (chỉ nạp được trong proxy): guardrails, callbacks.
"""
