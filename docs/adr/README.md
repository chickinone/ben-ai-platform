# Architecture Decision Records

Mỗi quyết định kiến trúc quan trọng là một file ngắn theo [template.md](template.md). ADR không bị sửa nội dung sau khi chấp nhận — muốn đổi quyết định thì viết ADR mới với trạng thái "Thay thế ADR-xxx".

| ADR | Tiêu đề | Trạng thái | Ngày |
|---|---|---|---|
| [001](001-build-vs-buy-gateway.md) | Tự xây lõi gateway thay vì dùng LiteLLM / Kong AI Gateway | Bị thay thế bởi ADR-017 | 2026-09-14 |
| [002](002-api-format.md) | API thống nhất kiểu OpenAI kèm passthrough API gốc từng provider | Đã chấp nhận, sửa đổi bởi ADR-017 | 2026-09-14 |
| [003](003-vector-store.md) | pgvector làm vector store | Đã chấp nhận | 2026-09-14 |
| [004](004-tenant-isolation.md) | Cách ly tenant bằng schema chung + `tenant_id` + Row Level Security | Đã chấp nhận | 2026-09-14 |
| [005](005-metering-queue.md) | Redis Streams cho metering, không dùng Kafka | Đã chấp nhận | 2026-09-14 |
| 006 | Guardrail lỗi: chặn hay cho qua | Dự kiến (tuần 5) | |
| 007 | Semantic cache | Dự kiến (tuần 4) | |
| 008 | Agent đồng bộ hay bất đồng bộ | Dự kiến (tuần 8) | |
| 009 | Tích hợp tool bằng MCP | Dự kiến (tuần 8) | |
| 010 | Phương pháp chấm eval | Dự kiến (tuần 9) | |
| 011 | Mô hình triển khai | Dự kiến (tuần 15) | |
| 012 | Ba lớp chống shadow AI | Dự kiến (tuần 10) | |
| 013 | OPA làm điểm quyết định policy | Dự kiến (tuần 11) | |
| 014 | Nhãn cao nhất quyết định định tuyến model | Dự kiến (tuần 11) | |
| 015 | OpenMetadata và lineage hai tầng | Dự kiến (tuần 12) | |
| 016 | Subject index cho yêu cầu xoá | Dự kiến (tuần 13) | |
| [017](017-litellm-proxy-as-gateway-core.md) | Dùng LiteLLM Proxy làm lõi gateway, mở rộng bằng plugin ([thử nghiệm](../../spikes/litellm/README.md)) | Đã chấp nhận | 2026-09-15 |
