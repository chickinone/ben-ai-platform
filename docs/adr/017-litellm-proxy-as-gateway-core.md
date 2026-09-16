# ADR-017: Dùng LiteLLM Proxy làm lõi gateway, mở rộng bằng plugin của Bến

- **Trạng thái:** Đã chấp nhận (2026-09-15, chủ dự án) — thay thế ADR-001, sửa đổi ADR-002
- **Ngày:** 2026-09-15
- **Liên quan:** ADR-001, ADR-002, ADR-005, ADR-007, FR-G1 → FR-G9, FR-D2, NFR-1, NFR-7

## Bối cảnh

ADR-001 chọn tự xây gateway với lý do guardrail và governance khó cắm vào sản phẩm có sẵn. Khi xem lại, lý do đó chưa được kiểm chứng: LiteLLM là mã nguồn mở (MIT, trừ thư mục `enterprise/`) và có cơ chế guardrail tuỳ biến với hook `pre_call` sửa được request, `post_call` sửa được response, hook streaming, cùng callback logging.

Đã chạy thử nghiệm với 6 rủi ro cụ thể ([spikes/litellm](../../spikes/litellm/README.md)) trên LiteLLM v1.100.1, dùng mock provider ghi lại nguyên văn request.

## Tiêu chí đánh giá

1. Không PII thô tới provider, cache, log, payload logging (NFR-7).
2. Governance ép model và không bị fallback làm rò rỉ (FR-D2).
3. Endpoint tương thích SDK `openai` và `anthropic` (ADR-002).
4. Metering chính xác sang hệ thống của Bến (ADR-005, NFR-9).
5. Không phụ thuộc tính năng enterprise.
6. Công sức hiện thực và rủi ro bảo trì.

## Các phương án

### Phương án 1 — Tự xây toàn bộ (ADR-001)
- Ưu: kiểm soát tuyệt đối thứ tự và hành vi khi lỗi.
- Nhược: tự viết lại adapter provider, định dạng stream, bảng giá, virtual key, budget, fallback — những phần LiteLLM đã có và đã được kiểm chứng rộng rãi.

### Phương án 2 — Fork LiteLLM và sửa mã lõi
- Ưu: sửa được mọi chỗ.
- Nhược: LiteLLM phát hành rất dày; fork = tự gộp bản vá bảo mật và xử lý xung đột vô thời hạn.

### Phương án 3 — LiteLLM Proxy + plugin của Bến (không sửa lõi)
- Ưu: thử nghiệm đạt 5/6 rủi ro đầy đủ, rủi ro còn lại có cách tránh; tiết kiệm khoảng 1,5 tuần; plugin nhỏ, test được độc lập.
- Nhược: phụ thuộc thứ tự hook và hành vi nội bộ của LiteLLM có thể đổi giữa các phiên bản; một số giới hạn phải chấp nhận (xem Hệ quả).

### Phương án 4 — Gateway của Bến dùng thư viện LiteLLM làm adapter
- Ưu: kiểm soát thứ tự tuyệt đối, vẫn tận dụng phần dịch format và bảng giá.
- Nhược: vẫn phải tự viết virtual key, budget, router, cache, passthrough.

## Quyết định

Chọn **phương án 3**, với các điều kiện bắt buộc rút ra từ thử nghiệm:

1. **Endpoint:** chỉ mở `/v1/chat/completions`, `/v1/embeddings` và `/v1/messages` (hợp nhất) cho tenant có dữ liệu cá nhân. **Không mở passthrough `/anthropic`** cho các tenant đó, vì guardrail chỉ chạy một chiều.
2. **Logging:** bật `turn_off_message_logging`; nếu cần nội dung trong trace, Bến tự ghi bản đã che bằng callback riêng.
3. **Governance:** hook ép model phải đặt `disable_fallbacks`.
4. **Guardrail:** dùng `mode` dạng danh sách + `default_on`; không dùng `mode` theo tag (enterprise).
5. **Nâng cấp:** pin phiên bản LiteLLM; bộ test thử nghiệm chạy trong CI và phải xanh trước mỗi lần nâng cấp.

## Hệ quả

- (+) Có ngay: nhiều provider, virtual key, budget, fallback, cache, định dạng stream, bảng giá model.
- (+) Code của Bến tập trung vào phần khác biệt: PII tiếng Việt, OPA, provenance, metering theo schema Bến.
- (−) Bảng ánh xạ PII phải chuyển sang kho dùng chung có TTL khi chạy nhiều worker → giá trị gốc rời khỏi RAM của một request; cần mã hoá và TTL ngắn.
- (−) Trace trên Langfuse không có nội dung prompt/response nếu không tự ghi bản đã che.
- (−) Cache key tính trên prompt đã che → cần xem lại ở ADR-007 với nội dung phụ thuộc người hỏi.
- (−) Thêm một hệ thống có database riêng (LiteLLM dùng Postgres cho key, budget, spend log) → dữ liệu chi phí có ở hai nơi; `usage_events` của Bến vẫn là nguồn cho báo cáo.
- ADR-002 cần sửa: "passthrough API gốc" → dùng `/v1/messages` hợp nhất của LiteLLM cho Anthropic.
- Lộ trình tuần 3–4 đổi: thay vì viết adapter và router, làm plugin, virtual key/budget, đo overhead.

## Việc phải kiểm chứng (tuần 3–4)

- [x] Virtual key và budget với database LiteLLM, không cần license (tuần 3 — `tests/integration`). **Ngân sách là giới hạn mềm:** hạn mức 0,0002 USD vẫn cho qua 4 request (tổng 0,000328 USD, vượt ~64%) rồi mới trả 429 `budget_exceeded`, do chi phí được cập nhật trễ và 2 worker kiểm tra song song → ngân sách thật cần đặt thấp hơn trần chịu được, cảnh báo sớm ở 80%
- [ ] Gọi Claude thật qua `/v1/messages`, gồm streaming và tool use
- [ ] Overhead độ trễ của proxy + plugin so với NFR-1
- [ ] Khôi phục PII khi streaming `/v1/messages`
- [x] Chạy nhiều worker với kho ánh xạ dùng chung (tuần 3 — 2 worker, kho Redis mã hoá AES-GCM, 20/20 request khôi phục đúng)

## Điều kiện xem lại

- Một bản nâng cấp LiteLLM làm vỡ thứ tự hook mà không có cách khắc phục trong 1 tuần.
- Yêu cầu guardrail cần can thiệp vào chỗ LiteLLM không có hook.
- Overhead không đạt NFR-1 sau tinh chỉnh.
