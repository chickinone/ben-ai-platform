# ADR-004: Cách ly tenant bằng schema chung + `tenant_id` + Row Level Security

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-09-14
- **Liên quan:** NFR-8, NFR-11, ADR-003

## Bối cảnh

Bến phục vụ nhiều tenant (mục tiêu 50) trên cùng hạ tầng. Dữ liệu của tenant — key, policy, usage, tài liệu, chunk, lượt chạy agent — không được lẫn sang tenant khác. Một số tenant (ví dụ `hr`) nhạy cảm hơn hẳn các tenant còn lại.

## Tiêu chí đánh giá

1. Khả năng rò rỉ dữ liệu giữa tenant do lỗi lập trình.
2. Chi phí vận hành khi số tenant tăng (migration, backup, kết nối).
3. Truy vấn tổng hợp toàn nền tảng (chi phí toàn công ty).
4. Khả năng nâng mức cách ly cho tenant nhạy cảm.

## Các phương án

### Phương án 1 — Chung schema, cột `tenant_id`
- Ưu: đơn giản nhất; một migration; truy vấn tổng hợp dễ.
- Nhược: quên một điều kiện `tenant_id` là rò rỉ.

### Phương án 2 — Mỗi tenant một schema Postgres
- Ưu: cách ly tốt hơn; xoá tenant bằng một lệnh.
- Nhược: migration nhân theo số tenant; truy vấn tổng hợp phải `UNION` qua schema; connection pool phức tạp.

### Phương án 3 — Mỗi tenant một database
- Ưu: cách ly mạnh nhất; backup/khôi phục độc lập.
- Nhược: chi phí vận hành cao nhất; không hợp 50 tenant trên laptop.

### Phương án 4 — Chung schema + `tenant_id` + Row Level Security, cho phép tách DB theo ngoại lệ
- Ưu: giữ sự đơn giản của phương án 1, thêm lớp phòng thủ ở tầng database; tenant đặc biệt vẫn tách được.
- Nhược: phải quản lý biến phiên `app.tenant_id` đúng cách; RLS không áp dụng cho owner của bảng nên role ứng dụng phải tách khỏi role owner.

## Quyết định

Chọn **phương án 4**.

- Mọi bảng thuộc tenant có `tenant_id uuid NOT NULL`.
- Role **`ben`** (owner, chạy migration) tách khỏi role **`ben_app`** (ứng dụng dùng). RLS chỉ có tác dụng với `ben_app`.
- Bảng chứa nội dung (`documents`, `chunks`) bật RLS với policy `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`. Chưa đặt tenant → không thấy dòng nào (mặc định từ chối).
- Ứng dụng đặt tenant bằng `SET LOCAL app.tenant_id = ...` trong từng transaction, lấy từ API key đã xác thực — không bao giờ từ header do client gửi.
- Tenant có yêu cầu đặc biệt có thể tách DB riêng; quyết định ghi trong policy tenant (mở rộng).
- `ben_app` bị thu hồi `UPDATE`, `DELETE`, `TRUNCATE` trên `audit_logs`.

## Hệ quả

- (+) Lỗi quên điều kiện `tenant_id` ở tầng ứng dụng không làm rò rỉ nội dung tài liệu (RLS chặn).
- (+) Một migration, truy vấn tổng hợp chi phí chạy bằng role báo cáo riêng.
- (−) Các thao tác quản trị xuyên tenant (control plane, job governance) cần role riêng có `BYPASSRLS` hoặc đặt tenant tường minh → thiết kế ở tuần 10–13.
- (−) Dùng connection pool phải bảo đảm `SET LOCAL` (không phải `SET`) để biến không rò sang request khác.
- Kiểm chứng: test tích hợp — role `ben_app` với tenant A không đọc được chunk tenant B; test audit log bất biến (đã có từ tuần 2).

## Điều kiện xem lại

- Có yêu cầu pháp lý/khách hàng buộc cách ly vật lý.
- Số tenant > 500 hoặc một tenant chiếm > 50% dữ liệu.
