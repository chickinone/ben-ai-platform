from types import SimpleNamespace

import pytest

from ben_litellm_plugins.pii import Redactor, restore_response, restore_text


@pytest.mark.parametrize("phone", ["0912 345 678", "0912345678", "0912.345.678", "+84 912 345 678"])
def test_redacts_vietnamese_phone_formats(phone):
    redactor = Redactor()
    assert redactor.redact_text(f"Gọi {phone} giúp tôi") == "Gọi <PHONE_1> giúp tôi"
    assert redactor.mapping == {"<PHONE_1>": phone}


def test_redacts_cccd_before_phone():
    redactor = Redactor()
    text = redactor.redact_text("CCCD 001203004567, SĐT 0912345678")
    assert text == "CCCD <CCCD_1>, SĐT <PHONE_1>"


def test_same_value_reuses_placeholder_and_new_values_increment():
    redactor = Redactor()
    text = redactor.redact_text("0912345678, 0912345678, 0987654321")
    assert text == "<PHONE_1>, <PHONE_1>, <PHONE_2>"


def test_leaves_other_numbers_untouched():
    text = "Đơn 12345 giá 250000đ, mã vận đơn 1234567890"
    assert Redactor().redact_text(text) == text


def test_redacts_openai_and_anthropic_request_shapes():
    data = {
        "system": [{"type": "text", "text": "Khách có SĐT 0912345678"}],
        "messages": [
            {"role": "user", "content": "Gọi 0912 345 678"},
            {"role": "user", "content": [{"type": "text", "text": "CCCD 001203004567"}]},
        ],
    }
    redactor = Redactor()
    assert redactor.redact_request(data) == 3
    # messages được che trước system prompt nên nhận số thứ tự nhỏ hơn
    assert data["messages"][0]["content"] == "Gọi <PHONE_1>"
    assert data["system"][0]["text"] == "Khách có SĐT <PHONE_2>"
    assert data["messages"][1]["content"][0]["text"] == "CCCD <CCCD_1>"


def test_restore_text_keeps_unknown_placeholders():
    assert restore_text("<PHONE_1> và <PHONE_9>", {"<PHONE_1>": "0912"}) == "0912 và <PHONE_9>"


def test_restore_openai_style_response_object():
    message = SimpleNamespace(content="Đã gọi <PHONE_1>")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    restore_response(response, {"<PHONE_1>": "0912 345 678"})
    assert message.content == "Đã gọi 0912 345 678"


def test_restore_anthropic_style_response_dict():
    response = {"content": [{"type": "text", "text": "SĐT <PHONE_1>"}, {"type": "tool_use"}]}
    restore_response(response, {"<PHONE_1>": "0912 345 678"})
    assert response["content"][0]["text"] == "SĐT 0912 345 678"
