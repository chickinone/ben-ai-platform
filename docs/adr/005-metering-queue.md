# ADR-005: Redis Streams cho metering, không dùng Kafka

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-09-14
- **Liên quan:** FR-G8, NFR-1, NFR-9, NFR-11, FR-D3

## Bối cảnh

Mỗi request qua gateway sinh một usage event (token, chi phí, độ trễ, cache, fallback) và — từ tuần 12 — một provenance event. Ghi đồng bộ vào Postgres trên đường đi của request làm tăng độ trễ (NFR-1) và khiến Postgres chậm kéo theo gateway chậm. Cần một hàng đợi bền để gateway phát event bất đồng bộ và worker gom lô ghi xuống.

Quy mô mục tiêu: 10 triệu usage event/tháng (NFR-11) ≈ 4 event/giây trung bình, đỉnh vài trăm event/giây.

## Tiêu chí đánh giá

1. Không làm chậm request (phát event < 1 ms).
2. Không mất event khi worker khởi động lại.
3. Số hệ thống phải vận hành.
4. Khả năng phát lại (replay) khi sửa lỗi tính chi phí.

## Các phương án

### Phương án 1 — Ghi thẳng Postgres trong request
- Ưu: đơn giản nhất.
- Nhược: tăng độ trễ; Postgres chậm → gateway chậm; khó gom lô.

### Phương án 2 — Kafka
- Ưu: bền, replay dài hạn, chuẩn cho event streaming quy mô lớn.
- Nhược: thêm một cụm có trạng thái (broker + KRaft); nặng cho laptop; quá khả năng cần ở 10 triệu event/tháng. Dự án trước của tác giả đã chứng minh năng lực Kafka.

### Phương án 3 — Redis Streams
- Ưu: Redis đã có sẵn (quota, cache); consumer group có ack và danh sách pending → không mất event khi worker chết; `XADD` rất nhanh; đủ cho quy mô mục tiêu.
- Nhược: dữ liệu nằm trong RAM, retention ngắn; replay dài hạn hạn chế; bền phụ thuộc cấu hình AOF.

## Quyết định

Chọn **Redis Streams**.

- Stream `stream:usage` (và `stream:provenance` từ tuần 12); gateway `XADD` với `MAXLEN ~` giới hạn độ dài.
- Worker đọc bằng consumer group, ghi lô vào Postgres, `XACK` **sau** khi transaction commit; event pending quá hạn được worker khác nhận lại (`XAUTOCLAIM`).
- Ghi Postgres idempotent theo `trace_id` để nhận lại không tạo bản ghi trùng.
- Redis bật AOF (`--appendonly yes`) trong compose.
- Nguồn replay dài hạn là **bảng `usage_events` trong Postgres**, không phải stream.

## Hệ quả

- (+) Không thêm hệ thống; phát event gần như không tốn thời gian.
- (+) Worker chết không mất event nhờ pending list.
- (−) Redis đang cấu hình `maxmemory-policy noeviction` (Langfuse yêu cầu và cũng an toàn cho stream/quota) → cache của gateway phải có TTL và giới hạn kích thước riêng, không dựa vào eviction của Redis. Khi tách môi trường giống production, cân nhắc Redis riêng cho cache.
- (−) Redis mất dữ liệu trong khoảng giữa hai lần fsync AOF → chấp nhận sai số nhỏ, đối chiếu định kỳ với usage provider (NFR-9).
- (−) Khi Redis sập, gateway ghi đệm event ra file cục bộ rồi đẩy lại (PROJECT.md §17).
- Kiểm chứng: test kill worker giữa lô ở tuần 4; đo thời gian `XADD` trong span.

## Điều kiện xem lại

- Lưu lượng event bền vững > 5.000 event/giây.
- Có hệ thống khác cần tiêu thụ cùng luồng event (data platform, billing) → khi đó Kafka hoặc dịch vụ managed tương đương đáng giá.
