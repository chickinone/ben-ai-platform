# ADR-001: Tự xây lõi gateway thay vì dùng LiteLLM / Kong AI Gateway

- **Trạng thái:** Bị thay thế bởi [ADR-017](017-litellm-proxy-as-gateway-core.md) (2026-09-15) — thử nghiệm cho thấy lý do chính của ADR này chưa đứng vững
- **Ngày:** 2026-09-14
- **Liên quan:** FR-G1 → FR-G9, FR-D2, NFR-1, NFR-7

## Bối cảnh

Bến cần một gateway đứng giữa app của các team và nhà cung cấp model. Gateway phải làm được những việc mà nhiều sản phẩm có sẵn đã hỗ trợ một phần (xác thực, rate limit, routing, fallback, tính chi phí), cộng với những việc đặc thù:

- Che PII tiếng Việt **có đảo ngược** trước khi gửi ra ngoài và khôi phục ở đầu ra.
- Gắn quyết định governance (OPA) và nhãn phân loại của context vào việc chọn model.
- Tính chi phí đúng theo cách tính riêng của từng provider, gồm token cache.
- Phát provenance event cho từng câu trả lời.
- Thứ tự các bước phải kiểm soát chặt (ví dụ: che PII **trước** cache; quyết định policy **trước** router).

Đây là dự án portfolio: năng lực thiết kế và hiện thực phần lõi này là thứ cần chứng minh.

## Tiêu chí đánh giá

1. Kiểm soát được thứ tự và nội dung chuỗi xử lý (guardrail, governance, metering).
2. Hỗ trợ passthrough API gốc từng provider mà không làm mất tính năng (ADR-002).
3. Overhead thấp (NFR-1).
4. Công sức hiện thực và vận hành trong 16 tuần.
5. Giá trị trình bày năng lực.

## Các phương án

### Phương án 1 — LiteLLM Proxy
- Ưu: có sẵn nhiều provider, virtual key, budget, fallback, logging callback; cộng đồng lớn.
- Nhược: guardrail và governance phải cắm qua cơ chế plugin/callback của sản phẩm, khó bảo đảm thứ tự bước và hành vi khi lỗi; thêm một codebase lớn phải hiểu và theo phiên bản; phần "tự làm" còn lại là phần dễ nhất.

### Phương án 2 — Kong AI Gateway (hoặc API gateway thương mại có plugin AI)
- Ưu: API gateway trưởng thành, plugin rate limit, auth; mô hình vận hành quen thuộc với doanh nghiệp.
- Nhược: PII tiếng Việt, OPA theo nhãn context, metering theo provider phải viết plugin riêng (Lua hoặc ngôn ngữ plugin của sản phẩm); một số tính năng AI nằm ở bản trả phí; nặng cho môi trường laptop.

### Phương án 3 — Tự xây lõi mỏng bằng FastAPI, dùng SDK chính thức của provider
- Ưu: kiểm soát hoàn toàn chuỗi middleware; dễ test từng bước; cùng ngôn ngữ với RAG, agent, governance; thể hiện năng lực.
- Nhược: phải tự viết rate limit, circuit breaker, streaming, retry; rủi ro lỗi ở những phần đã được sản phẩm khác giải quyết; phải tự theo thay đổi API provider.

## Quyết định

Chọn **phương án 3**: tự xây lõi gateway mỏng bằng FastAPI.

- Dùng SDK chính thức `anthropic`, `openai` cho endpoint thống nhất; `httpx` cho passthrough.
- Tham khảo thiết kế của LiteLLM (định dạng model, cách tính chi phí, xử lý stream) thay vì phát minh lại.
- Giữ gateway **mỏng**: chỉ các bước ở PROJECT.md §7.2; không đưa logic nghiệp vụ RAG/agent vào gateway.

## Hệ quả

- (+) Toàn quyền quyết định thứ tự guardrail → cache → governance → router → metering, và hành vi khi từng bước lỗi.
- (+) Mỗi bước là một middleware có unit test riêng; dễ đo overhead từng bước bằng span.
- (−) Tốn thêm khoảng 2 tuần so với cấu hình sản phẩm có sẵn (tuần 3–4).
- (−) Phải tự theo dõi thay đổi API của provider → contract test bằng SDK thật chạy trong CI.
- Tài liệu phải ghi rõ: **ở doanh nghiệp thật**, với đội nhỏ và yêu cầu guardrail đơn giản, dùng sản phẩm có sẵn thường hợp lý hơn; quyết định này phục vụ yêu cầu guardrail/governance đặc thù và mục tiêu portfolio.

## Điều kiện xem lại

- Công sức duy trì adapter provider vượt 20% thời gian mỗi tuần.
- Yêu cầu hỗ trợ trên 5 provider.
- Overhead gateway không đạt NFR-1 sau tối ưu ở tuần 15.
