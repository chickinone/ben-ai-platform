import pytest

from ben_litellm_plugins.governance import decide_routing, normalize_headers, trusted_label

LOCAL = {"mock-local-small", "local-qwen"}


def test_label_from_regular_key_is_ignored():
    headers = {"x-ben-context-label": "confidential"}
    assert trusted_label(headers, {}) is None
    assert trusted_label(headers, None) is None
    assert trusted_label(headers, {"ben_service": "true"}) is None  # phải là boolean True


def test_label_from_service_key_is_trusted_and_normalized():
    assert trusted_label({"x-ben-context-label": " Confidential "}, {"ben_service": True}) == (
        "confidential"
    )


@pytest.mark.parametrize("label", [None, "public", "internal"])
def test_non_sensitive_labels_keep_requested_model(label):
    decision = decide_routing("mock-cloud-small", label, LOCAL, "mock-local-small")
    assert decision.model == "mock-cloud-small"
    assert decision.disable_fallbacks is False


@pytest.mark.parametrize("label", ["confidential", "restricted"])
def test_sensitive_labels_force_local_and_disable_fallbacks(label):
    decision = decide_routing("mock-cloud-small", label, LOCAL, "mock-local-small")
    assert decision.model == "mock-local-small"
    assert decision.disable_fallbacks is True


def test_sensitive_label_keeps_requested_model_when_already_local():
    decision = decide_routing("local-qwen", "confidential", LOCAL, "mock-local-small")
    assert decision.model == "local-qwen"
    assert decision.disable_fallbacks is True


def test_normalize_headers_merges_known_locations_case_insensitively():
    data = {
        "proxy_server_request": {"headers": {"X-Ben-Context-Label": "confidential"}},
        "metadata": {"headers": {"X-Request-Id": "abc"}},
    }
    assert normalize_headers(data) == {"x-ben-context-label": "confidential", "x-request-id": "abc"}
