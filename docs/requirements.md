# Yêu cầu — Bến AI Platform

| | |
|---|---|
| Phiên bản | 0.1 — 14/09/2026 |
| Trạng thái | Bản đầu, chờ review |
| Quan hệ với PROJECT.md | File này là **nguồn sự thật** cho FR, NFR, phạm vi. PROJECT.md là tổng quan và thiết kế chi tiết; khi hai file lệch nhau, sửa PROJECT.md theo file này. |

## 1. Bối cảnh & mục tiêu

**ShopViet** (giả định) — thương mại điện tử, ~500 nhân sự, 6 team muốn dùng LLM. Hiện trạng "shadow AI": mỗi team tự giữ key nhà cung cấp, không đo được chi phí, dữ liệu khách hàng bị gửi thẳng ra ngoài, không đo được chất lượng, agent có quyền quá rộng.

| Mục tiêu kinh doanh | Chỉ số | Mục tiêu |
|---|---|---|
| Kiểm soát chi phí AI | Chi phí token so với baseline "mỗi team tự gọi model vừa" | Giảm ≥ 30% mà điểm eval giảm < 3 điểm |
| Bảo vệ dữ liệu | PII thô tới provider cloud; dữ liệu ≥ Confidential tới cloud | 0 / 0 |
| Tăng tốc team sản phẩm | Thời gian từ tạo tenant đến gọi API thành công | < 3 phút |
| Chứng minh được với kiểm toán | Request có trace + provenance; yêu cầu xoá có báo cáo bằng chứng | 100% |

## 2. Các bên liên quan

| Vai trò | Quan tâm chính | Tương tác |
|---|---|---|
| Platform Admin | Vận hành ổn định, chi phí toàn công ty, model catalog | Portal, Grafana |
| Tenant Admin | Key, ngân sách, tài liệu, prompt của team mình | Portal |
| Developer | Tích hợp nhanh bằng SDK có sẵn | API |
| Người duyệt | Duyệt hành động rủi ro của agent | Portal |
| Security / Compliance | Audit, sự cố guardrail | Portal, audit log |
| Data Owner / Data Steward | Nhãn phân loại, chất lượng nguồn | Portal, OpenMetadata |
| DPO | Use case có dữ liệu cá nhân, yêu cầu của chủ thể dữ liệu | Portal |
| End user | Nhận câu trả lời đúng, nhanh | App của tenant (không thấy Bến) |

## 3. Phạm vi

Xem bảng MVP / Mở rộng / Ngoài phạm vi ở [PROJECT.md §5.4](PROJECT.md#54-phạm-vi). Nguyên tắc khoá phạm vi: không làm hạng mục "Mở rộng" cho đến khi [kịch bản demo](demo-script.md) chạy trọn.

## 4. Yêu cầu chức năng

Ưu tiên: **M** = MVP bắt buộc · **E** = mở rộng. Cột "Demo" trỏ tới cảnh trong [demo-script.md](demo-script.md).

### 4.1 Gateway

| ID | Yêu cầu | Ưu tiên | Tiêu chí chấp nhận | Tuần | Demo |
|---|---|:-:|---|:-:|:-:|
| FR-G1 | API thống nhất tương thích OpenAI Chat Completions, `model: "auto"`, streaming SSE | M | SDK `openai` chính thức gọi được chỉ bằng đổi `base_url` + key; stream trả từng chunk, kết thúc bằng `[DONE]` | 3 | 1, 2 |
| FR-G2 | Endpoint định dạng Anthropic Messages (`/v1/messages` hợp nhất qua LiteLLM — ADR-017) | M | SDK `anthropic` chính thức gọi được qua proxy chỉ đổi `base_url` + key; guardrail chạy cả hai chiều; passthrough `/anthropic` không mở cho tenant có dữ liệu cá nhân | 3–4 | 1 |
| FR-G3 | Endpoint embeddings | M | Trả vector đúng số chiều của model; tính usage | 3 | — |
| FR-G4 | Xác thực bằng API key theo tenant, có scope, hết hạn, thu hồi | M | Key sai/hết hạn/thu hồi → 401 `invalid_api_key` trong < 60 s kể từ khi thu hồi; DB chỉ lưu hash | 3 | 1 |
| FR-G5 | Hạn mức RPM, TPM, ngân sách tháng | M | Vượt RPM → 429 có `Retry-After`; 50 request song song không vượt quota quá 1 request; ngân sách 100% → hạ tier hoặc 429 theo policy | 4 | — |
| FR-G6 | Router theo policy, fallback, circuit breaker | M | Dừng provider chính giữa lúc tải → request thành công qua model dự phòng trong < 2 s; header `X-Ben-Fallback: true` | 4 | 5 |
| FR-G7 | Che PII tiếng Việt có đảo ngược; phát hiện prompt injection | M | Bộ test 500 mẫu: 0 SĐT/CCCD/STK thô trong payload gửi provider; báo cáo precision/recall theo loại | 5 | 3 |
| FR-G8 | Tính token và chi phí theo cách tính riêng từng provider (gồm token cache) | M | Tổng chi phí lệch < 1% so với usage provider báo trên cùng tập request | 4 | 9 |
| FR-G9 | Exact cache; semantic cache theo tenant | M / E | Hỏi lại cùng câu → `X-Ben-Cache: hit`, chi phí 0; không cache request có PII | 4 / E | 2 |

### 4.2 RAG

| ID | Yêu cầu | Ưu tiên | Tiêu chí chấp nhận | Tuần | Demo |
|---|---|:-:|---|:-:|:-:|
| FR-R1 | Upload PDF, DOCX, HTML, Markdown; gán nhóm quyền | M | 4 định dạng mẫu ingest thành công; nhóm quyền lưu xuống từng chunk | 6 | 6 |
| FR-R2 | Ingest bất đồng bộ, trạng thái, version, xoá hoàn toàn | M | Xoá tài liệu → không còn chunk và mục cache liên quan trong 24 h (test ngay lập tức trong CI) | 6 | — |
| FR-R3 | Hybrid search + rerank, lọc quyền trong truy vấn | M | Test tự động: người nhóm A không bao giờ nhận chunk nhóm B, kể cả khi hỏi đích danh tài liệu | 6–7 | 6 |
| FR-R4 | Trả lời có trích dẫn; từ chối khi thiếu căn cứ | M | recall@6 ≥ 0,85; trích dẫn đúng ≥ 0,95; từ chối đúng ≥ 0,90 trên golden set | 7 | 6 |

### 4.3 Agent

| ID | Yêu cầu | Ưu tiên | Tiêu chí chấp nhận | Tuần | Demo |
|---|---|:-:|---|:-:|:-:|
| FR-A1 | Định nghĩa agent bằng YAML | M | Agent `finance-analyst` chạy từ file YAML, không hard-code | 8 | 8 |
| FR-A2 | Tool qua MCP, có mức rủi ro | M | 4 tool mẫu; tool chưa được duyệt không xuất hiện với agent | 8 | 8 |
| FR-A3 | Chạy bất đồng bộ, lưu trạng thái, tiếp tục sau sự cố | M | Kill worker giữa lượt chạy → worker khác tiếp tục từ bước cuối, không lặp tool đã chạy | 8 | — |
| FR-A4 | Hàng chờ duyệt cho tool `write` / `external` | M | `send_email` luôn dừng ở `WAITING_APPROVAL`; từ chối kèm lý do → agent nhận lý do và lập kế hoạch lại | 8 | 8 |

### 4.4 Control plane & Observability

| ID | Yêu cầu | Ưu tiên | Tiêu chí chấp nhận | Tuần | Demo |
|---|---|:-:|---|:-:|:-:|
| FR-C1 | Portal quản lý tenant, key, ngân sách, policy, tài liệu, prompt, tool, duyệt, audit | M | Tạo tenant → gọi API thành công < 3 phút, không cần sửa file tay | 10 | 1 |
| FR-C2 | Trace mọi request; dashboard chi phí/độ trễ/lỗi; cảnh báo | M | 100% request có `trace_id` tìm được trên Langfuse; 4 cảnh báo ở PROJECT.md §10.3 bắn được khi giả lập | 9 | 2, 5 |
| FR-C3 | Prompt registry có version và nhãn | M | Chuyển nhãn `production` về version cũ → gateway dùng version cũ trong < 60 s | 9 | 9 |
| FR-C4 | Eval chạy trong CI, chặn PR dưới ngưỡng | M | PR đổi prompt kém → job eval fail, comment bảng điểm vào PR | 9 | 9 |
| FR-C5 | Chống shadow AI lớp mạng | M | Container app demo gọi thẳng `api.openai.com` thất bại; gọi qua gateway thành công | 10 | 4 |

### 4.5 Data & AI Governance

| ID | Yêu cầu | Ưu tiên | Tiêu chí chấp nhận | Tuần | Demo |
|---|---|:-:|---|:-:|:-:|
| FR-D1 | Nhãn phân loại cho tài liệu, chunk, cột, tool, use case; tự đề xuất nhãn | M | Tài liệu có từ khoá lương được đề xuất ≥ Confidential; không bao giờ tự hạ nhãn | 11 | 10 |
| FR-D2 | Quyết định policy (OPA) theo use case, mục đích, nhãn; ràng buộc router | M | Context Confidential → chỉ model local; mục đích bên ngoài + Confidential → 403 `policy_denied` có lý do | 11 | 10 |
| FR-D3 | Provenance mọi câu trả lời; lineage tổng hợp lên OpenMetadata | M | 100% trace RAG/agent có provenance; tài liệu trên OpenMetadata hiện use case đã dùng | 12 | 12 |
| FR-D4 | Yêu cầu của chủ thể dữ liệu: xoá, hạn chế xử lý, rút đồng ý | M | Sau xoá, tìm theo subject key ở 6 nơi lưu = 0; có báo cáo bằng chứng | 13 | 11 |
| FR-D5 | Thời hạn lưu trữ, legal hold | M | Job dọn xoá đúng bản ghi quá hạn; bản ghi trong legal hold không bị xoá | 13 | — |
| FR-D6 | Owner, hạn review, kiểm tra chất lượng nguồn | M / E | Tài liệu `EXPIRED` bị loại khỏi RAG của `cskh`; Soda check là mở rộng | 14 | — |
| FR-D7 | AI Registry: vòng đời, phân tầng rủi ro, chặn key live, xuất DPIA/ROPA | M | Key live của use case chưa `approved` → 403 `usecase_not_approved`; xuất DPIA Markdown | 14 | 12 |

## 5. Yêu cầu phi chức năng

Danh sách đầy đủ, mục tiêu và cách đo: [PROJECT.md §5.3](PROJECT.md#53-yêu-cầu-phi-chức-năng-nfr) (NFR-1 → NFR-19). Tóm tắt các nhóm:

| Nhóm | NFR | Đo ở tuần |
|---|---|:-:|
| Hiệu năng | NFR-1 overhead gateway p95 < 60 ms · NFR-2 retrieval p95 < 400 ms · NFR-3 TTFT p95 < 1,5 s | 15 |
| Thông lượng & sẵn sàng | NFR-4 100 RPS/pod · NFR-5 99,9% · NFR-6 fallback < 2 s | 15 |
| Bảo mật | NFR-7 0 PII thô · NFR-8 0 đọc ngoài quyền | 5–6, 15 |
| Chi phí | NFR-9 lệch < 1% · NFR-10 giảm ≥ 30% | 4, 15 |
| Quy mô & quan sát | NFR-11 50 tenant, 1 triệu chunk · NFR-12 100% có trace | 9, 15 |
| Tuân thủ & vận hành | NFR-13 audit bất biến · NFR-14 `up` < 5 phút | 2, 5 |
| Governance | NFR-15 → NFR-19 | 11–15 |

## 6. Ràng buộc

| # | Ràng buộc | Hệ quả thiết kế |
|---|---|---|
| C1 | Một người, 16 tuần | Khoá phạm vi; ưu tiên thành phần mã nguồn mở có sẵn cho những gì không phải trọng tâm |
| C2 | Chạy trên một laptop (16–32 GB RAM, có thể không có GPU) | Model local 3–7B; load test dùng mock provider; OpenMetadata và Langfuse chạy compose riêng |
| C3 | Chi phí gần 0 | Mặc định dùng Ollama; API cloud chỉ để chứng minh passthrough và benchmark có giới hạn ngân sách |
| C4 | Không có dữ liệu thật của doanh nghiệp | Dữ liệu tổng hợp, tài liệu mẫu tự soạn; ghi rõ trong mọi báo cáo số liệu |
| C5 | Tài liệu và giao diện bằng tiếng Việt | Chuẩn hoá Unicode NFC; embedding đa ngôn ngữ; PII recognizer riêng cho Việt Nam |

## 7. Giả định

- A1: Nhân viên đăng nhập qua một IdP chung (mô phỏng bằng Keycloak); nhóm phòng ban lấy từ IdP.
- A2: Hợp đồng với provider cloud có điều khoản không dùng dữ liệu API để huấn luyện (điều kiện để dữ liệu Internal được gửi cloud).
- A3: Ứng dụng của tenant tự xác minh danh tính end user; Bến nhận `user_ref` đã được app xác thực.
- A4: Tầng mạng doanh nghiệp cho phép chặn egress theo domain (mô phỏng bằng Docker network).

## 8. Câu hỏi mở

| # | Câu hỏi | Ảnh hưởng | Cần chốt trước |
|---|---|---|---|
| Q1 | Provider cloud thứ hai dùng OpenAI hay chỉ Anthropic + mock? | Phạm vi adapter, chi phí benchmark | Tuần 3 |
| Q2 | Model local nào đủ chất lượng tiếng Việt trên máy hiện có? | Router, eval, NFR-3 | Tuần 3 |
| Q3 | Portal dùng Next.js hay Streamlit để tiết kiệm thời gian? | Tuần 10 | Tuần 9 |
| Q4 | Hạn xử lý yêu cầu của chủ thể dữ liệu và thời hạn thông báo vi phạm lấy theo điều khoản nào? | `retention.yaml`, runbook | Tuần 13 |
