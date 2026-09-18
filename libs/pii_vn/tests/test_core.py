import pytest

from ben_pii_vn import Redactor, detect_pii, mask_text, restore_text
from ben_pii_vn.policy import policy_from_metadata


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("Gọi 0912 345 678", "PHONE", "0912 345 678"),
        ("CCCD 001203004567", "CCCD", "001203004567"),
        ("Email lan.nguyen@example.com", "EMAIL", "lan.nguyen@example.com"),
        ("STK: 1234 5678 9012", "BANK", "1234 5678 9012"),
        ("Đơn #A1293 cần kiểm tra", "ORDER", "#A1293"),
        ("Khách hàng: Nguyễn Văn An", "NAME", "Nguyễn Văn An"),
    ],
)
def test_detects_supported_vietnamese_pii(text, kind, value):
    assert (kind, value) in [(entity.kind, entity.value) for entity in detect_pii(text)]


def test_cccd_requires_valid_province_prefix_and_bank_requires_context():
    assert not [entity for entity in detect_pii("CCCD 999203004567") if entity.kind == "CCCD"]
    assert not [entity for entity in detect_pii("Mã 123456789012") if entity.kind == "BANK"]


def test_redactor_preserves_mapping_and_is_idempotent_per_request():
    redactor = Redactor()
    redacted = redactor.redact_text("Gọi 0912345678, đơn #A1293, gọi lại 0912345678")
    assert redacted == "Gọi <PHONE_1>, đơn <ORDER_1>, gọi lại <PHONE_1>"
    assert (
        restore_text(redacted, redactor.mapping) == "Gọi 0912345678, đơn #A1293, gọi lại 0912345678"
    )


def test_mask_never_keeps_raw_supported_values():
    text = "SĐT 0912345678, email lan@example.com, STK 123456789012"
    masked = mask_text(text)
    assert "0912345678" not in masked
    assert "lan@example.com" not in masked
    assert "123456789012" not in masked


def test_missing_pii_restore_metadata_keeps_legacy_restore_default():
    assert policy_from_metadata({"ben_tenant": "legacy-key"}).restore is True
