import pytest

from ben_metering_worker.audit import InvalidAuditEvent, parse_audit_event


def test_parses_safe_guardrail_audit_event():
    event = parse_audit_event(
        {
            "ts": "1735689600",
            "actor": "tenant:cskh",
            "action": "guardrail.pii_redacted",
            "resource": "request:abc",
            "detail": '{"count":2,"mode":"redact"}',
        }
    )
    assert event.actor == "tenant:cskh"
    assert event.detail == {"count": 2, "mode": "redact"}


@pytest.mark.parametrize(
    "detail",
    ['{"prompt":"raw"}', '{"evidence":"raw"}', '{"metrics":{"text":"raw"}}', "[]"],
)
def test_rejects_audit_detail_that_could_contain_request_content(detail):
    with pytest.raises(InvalidAuditEvent):
        parse_audit_event(
            {
                "ts": "1735689600",
                "actor": "tenant:cskh",
                "action": "guardrail.pii_redacted",
                "resource": "request:abc",
                "detail": detail,
            }
        )
