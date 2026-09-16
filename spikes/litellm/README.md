# Thử nghiệm: LiteLLM Proxy làm lõi gateway của Bến

| | |
|---|---|
| Ngày | 2026-09-15 |
| Câu hỏi | Dùng LiteLLM Proxy (MIT) + plugin của Bến có đáp ứng các yêu cầu guardrail/governance/metering thay vì tự xây gateway (ADR-001)? |
| Phiên bản | `ghcr.io/berriai/litellm:v1.100.1` (bản ổn định mới nhất tại thời điểm thử) |
| Kết luận | **Đạt, có điều kiện** → đề xuất [ADR-017](../../docs/adr/017-litellm-proxy-as-gateway-core.md) |

## Cách chạy

```powershell
.\spikes\litellm\run.ps1          # dựng môi trường + chạy test, kết quả vào results/
.\spikes\litellm\run.ps1 -Down    # dọn
```

Môi trường tách khỏi compose chính: LiteLLM Proxy, Redis, hai mock provider (`mock-cloud` giả làm provider cloud, `mock-local` giả làm model local). Mock ghi lại **nguyên văn body** mọi request để kiểm tra provider thực sự nhận được gì, và trả lời bằng cách lặp lại tin nhắn của user để kiểm tra việc khôi phục PII. Streaming cắt 3 ký tự/chunk để placeholder `<PHONE_1>` bị cắt qua nhiều chunk.

Code của Bến chỉ nằm trong 2 file plugin, không sửa mã nguồn LiteLLM:
- [config/ben_guardrails.py](config/ben_guardrails.py): `BenPIIGuardrail` (che/khôi phục SĐT, gồm streaming), `BenGovernanceGuardrail` (giả lập OPA: nhãn Confidential → model local, tắt fallback).
- [config/ben_callbacks.py](config/ben_callbacks.py): ghi usage event vào Redis Streams (ADR-005).

## Kết quả

Lần chạy cuối: **11 passed, 1 xfailed** ([results/findings.json](results/findings.json)). Log proxy có dòng INFO của plugin cho mọi loại request, chứng minh hook thực sự chạy:

| call_type | Số lần hook PII chạy |
|---|---|
| `acompletion` (`/v1/chat/completions`) | 9 |
| `anthropic_messages` (`/v1/messages` hợp nhất) | 1 |
| `pass_through_endpoint` (`/anthropic/v1/messages`) | 2 |

| # | Rủi ro cần kiểm tra | Kết quả | Bằng chứng |
|---|---|:-:|---|
| 1 | Cache/log lưu PII thô vì chạy trước hook | ✅ sau khắc phục | Cache hit thật (provider chỉ nhận 1 lần, có header `x-litellm-cache-key`), cả hai lần client nhận SĐT đã khôi phục; Redis và log proxy không có SĐT thô. **Lần chạy 1 phát hiện payload logging (thứ Langfuse nhận) chứa response ĐÃ khôi phục SĐT** → khắc phục bằng `turn_off_message_logging: true` |
| 2 | Che PII có đảo ngược, cả streaming | ✅ | Provider nhận `<PHONE_1>`; client nhận SĐT thật; streaming khôi phục đúng dù placeholder bị cắt qua nhiều chunk |
| 3 | Định tuyến theo nhãn; fallback làm rò rỉ sang cloud | ✅ | Hook `pre_call` đổi `model` → router tôn trọng (cloud 0 request). Local lỗi + fallback local→cloud đã cấu hình → `disable_fallbacks` chặn được, client nhận 503, cloud 0 request. Test đối chứng xác nhận fallback hoạt động khi không có nhãn |
| 4 | Guardrail trên endpoint Anthropic | ⚠️ một phần | `/v1/messages` hợp nhất: che + khôi phục đầy đủ. Passthrough `/anthropic`: **có che** trước khi gửi provider, nhưng **không khôi phục** cho client (test 4c xfail) và không tính được chi phí với tên model tự đặt |
| 5 | Metering sang hệ thống của Bến | ✅ | Callback ghi Redis Streams; token khớp usage provider; chi phí khớp đơn giá cấu hình; streaming cũng có event; khớp request bằng header `x-litellm-call-id` |
| 6 | Phụ thuộc tính năng enterprise | ✅ | Không có `LITELLM_LICENSE`; plugin không import `litellm_enterprise`; log không nhắc tính năng enterprise. Lưu ý: `mode` dạng theo tag của guardrail là tính năng enterprise — phải dùng dạng danh sách |

## Phát hiện quan trọng

1. **Payload logging chạy sau khi response đã khôi phục PII.** Mọi callback (Langfuse, OTel...) sẽ nhận SĐT thô nếu không tắt. `turn_off_message_logging: true` loại nội dung khỏi payload nhưng giữ token, chi phí, model → trace trên Langfuse mất nội dung prompt. Nếu cần nội dung, Bến tự ghi bản đã che bằng callback riêng.
2. **Passthrough `/anthropic` không phù hợp với tenant có PII.** Chỉ chạy được một chiều của guardrail. Dùng `/v1/messages` hợp nhất của LiteLLM thay thế: SDK `anthropic` gọi được bình thường và guardrail chạy đủ hai chiều.
3. **`disable_fallbacks` là bắt buộc** khi governance ép model; nếu không, fallback theo cấu hình router có thể gửi dữ liệu mật sang cloud.
4. **Cache key tính trên prompt đã che.** Hai khách khác nhau gửi cùng mẫu câu (chỉ khác SĐT) sẽ dùng chung mục cache; câu trả lời được khôi phục bằng SĐT của từng người nên không lộ chéo trong thử nghiệm này, nhưng cần ADR-007 cân nhắc kỹ với nội dung phụ thuộc người hỏi.

## Giới hạn của thử nghiệm

- **Mock provider**, không gọi Claude/OpenAI thật. Hành vi API thật (tool call, thinking, lỗi) chưa kiểm chứng.
- **1 worker.** Bảng ánh xạ PII nằm trong RAM của tiến trình; nhiều worker hoặc nhiều pod cần kho dùng chung có TTL ngắn (ví dụ Redis, mã hoá) — tức là giá trị gốc sẽ rời RAM của request, cần cân nhắc trong ADR.
- **Nhãn context đọc từ header** do client gửi; production phải nhận từ dịch vụ nội bộ có xác thực.
- **Chưa thử:** virtual key và budget (cần database của LiteLLM), overhead độ trễ, khôi phục PII khi streaming `/v1/messages`, nhiều worker, bản cập nhật LiteLLM làm vỡ plugin.

## Việc cần làm nếu chấp nhận ADR-017

- Tuần 3: thử virtual key + budget với database LiteLLM; gọi Claude thật qua `/v1/messages`; đo overhead so với NFR-1.
- Chuyển bảng ánh xạ PII sang kho dùng chung có TTL; test nhiều worker.
- Plugin thành package `libs/ben_litellm_plugins` có unit test riêng; pin phiên bản LiteLLM và chạy bộ test này trong CI trước mỗi lần nâng cấp.
