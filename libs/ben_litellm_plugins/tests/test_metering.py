from ben_litellm_plugins.metering import build_usage_event


def test_builds_event_from_standard_logging_payload():
    kwargs = {
        "litellm_call_id": "call-1",
        "stream": True,
        "standard_logging_object": {
            "trace_id": "trace-1",
            "model_group": "mock-cloud-small",
            "model": "openai/mock-cloud-small",
            "call_type": "acompletion",
            "prompt_tokens": 22,
            "completion_tokens": 12,
            "response_cost": 8.2e-05,
            "cache_hit": None,
            "startTime": 1.0,
            "endTime": 2.5,
            "metadata": {
                "user_api_key_team_id": "team-1",
                "user_api_key_team_alias": "cskh",
                "user_api_key_hash": "hash-1",
                "user_api_key_alias": "cskh-app",
            },
        },
    }
    event = build_usage_event(kwargs)
    assert event["call_id"] == "call-1"
    assert event["team_id"] == "team-1"
    assert event["team_alias"] == "cskh"
    assert event["tokens_in"] == "22"
    assert event["tokens_out"] == "12"
    assert float(event["cost_usd"]) == 8.2e-05
    assert event["stream"] == "True"
    assert event["cache_hit"] == "False"
    assert all(isinstance(value, str) for value in event.values())


def test_missing_payload_produces_empty_but_valid_event():
    event = build_usage_event({})
    assert event["call_id"] == ""
    assert event["tokens_in"] == "0"
    assert event["cost_usd"] == "0"
