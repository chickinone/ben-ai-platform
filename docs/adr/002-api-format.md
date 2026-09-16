# ADR-002: API thống nhất kiểu OpenAI kèm passthrough API gốc từng provider

- **Trạng thái:** Đã chấp nhận — sửa đổi bởi ADR-017 (xem cuối file)
- **Ngày:** 2026-09-14
- **Liên quan:** FR-G1, FR-G2, FR-G8, ADR-001

## Bối cảnh

Các team đang dùng cả SDK `openai` và SDK `anthropic`. Hai API khác nhau đáng kể:

| | Anthropic Messages API | OpenAI Chat Completions |
|---|---|---|
| Endpoint | `POST /v1/messages` | `POST /v1/chat/completions` |
| Xác thực | `x-api-key` + `anthropic-version` | `Authorization: Bearer` |
| Tính năng riêng | Prompt caching có điều khiển, thinking, citations, một số loại tool | Responses API, một số loại tool |
| Usage | `input_tokens` không gồm token cache; có trường cache riêng | `prompt_tokens` đã gồm token cache |

Nếu gateway chỉ có một API chung, team dùng Claude mất tính năng gốc; nếu chỉ có passthrough, không có chỗ để router chọn model và không đổi được provider mà không sửa code app.

## Tiêu chí đánh giá

1. App hiện có chuyển sang Bến bằng cách đổi `base_url` + key, không sửa logic.
2. Không làm mất tính năng gốc của provider.
3. Có chỗ cho router chọn model và cho việc đổi provider.
4. Mọi đường đi đều qua chung chuỗi auth, quota, guardrail, governance, metering.

## Các phương án

### Phương án 1 — Chỉ API thống nhất (format OpenAI)
- Ưu: một format, router làm việc ở mọi request; app dễ đổi provider.
- Nhược: tính năng riêng của Claude phải ép qua trường mở rộng hoặc mất; dịch format hai chiều dễ sai ở tool call và streaming.

### Phương án 2 — Chỉ passthrough
- Ưu: tương thích tuyệt đối với SDK gốc; gateway không phải dịch format.
- Nhược: không có router; đổi provider phải sửa code app; mục tiêu tiết kiệm chi phí bằng routing không đạt.

### Phương án 3 — API thống nhất + passthrough cho từng provider
- Ưu: team chọn theo nhu cầu; router hoạt động ở API thống nhất; tính năng gốc giữ nguyên ở passthrough.
- Nhược: hai bộ endpoint; metering phải đọc usage theo từng provider ở cả response thường và stream.

## Quyết định

Chọn **phương án 3**:

| Loại | Đường dẫn | Router |
|---|---|---|
| Thống nhất | `/v1/chat/completions`, `/v1/embeddings`, `/v1/models` | Có (`model: "auto"` hoặc `tier:*`) |
| Passthrough Anthropic | `/anthropic/v1/messages`, `/anthropic/v1/messages/count_tokens` | Không (model do app chỉ định, phải nằm trong `allowed_models`) |
| Passthrough OpenAI | `/openai/v1/chat/completions`, `/openai/v1/responses` | Không |

- Gateway nhận key của Bến ở cả `Authorization: Bearer` và `x-api-key`.
- Passthrough **vẫn** chạy auth, quota, guardrail (che PII trong nội dung text), governance, metering; chỉ bỏ router và bước chuẩn hoá format.
- Metering chuẩn hoá usage về cấu trúc chung `Usage(input, output, cache_read, cache_write)` bằng parser riêng từng provider.

## Hệ quả

- (+) Hai đường tích hợp đều chỉ đổi 2 dòng code ở app.
- (+) Đo được riêng tỉ lệ traffic đi qua router để đánh giá mục tiêu tiết kiệm.
- (−) Che PII trong passthrough phải hiểu cấu trúc message của từng provider (text block, tool result).
- (−) Hai bộ contract test (SDK `openai` và `anthropic`) phải chạy trong CI.
- Kiểm chứng: contract test tuần 3; đối chiếu chi phí NFR-9 tuần 4.

## Điều kiện xem lại

- Một chuẩn API chung được cả hai provider hỗ trợ đầy đủ tính năng.
- Traffic passthrough > 70% tổng traffic (router ít giá trị) hoặc < 5% (passthrough không đáng duy trì).

## Sửa đổi 2026-09-15 (ADR-017)

Gateway hiện thực bằng LiteLLM Proxy. Thử nghiệm cho thấy passthrough `/anthropic` chỉ chạy guardrail một chiều (che nhưng không khôi phục PII). Vì vậy:

| Nhu cầu | Trước | Sau |
|---|---|---|
| SDK `openai`, router chọn model | `/v1/chat/completions` của Bến | `/v1/chat/completions` của LiteLLM |
| SDK `anthropic`, định dạng gốc | Passthrough `/anthropic/v1/messages` | **`/v1/messages` hợp nhất của LiteLLM** — guardrail chạy cả hai chiều |
| Passthrough nguyên byte | Mở cho mọi tenant | Chỉ mở cho tenant không có dữ liệu cá nhân, nếu thật sự cần |

Nguyên tắc "app chỉ đổi `base_url` + key" giữ nguyên.
