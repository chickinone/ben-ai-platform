# ADR-003: pgvector làm vector store

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-09-14
- **Liên quan:** FR-R1 → FR-R4, NFR-2, NFR-8, NFR-11, ADR-004

## Bối cảnh

RAG cần lưu khoảng 1 triệu chunk (NFR-11), tìm kiếm lai vector + từ khoá, và **lọc quyền trong truy vấn** theo `tenant_id` và nhóm người dùng (NFR-8). Chunk, metadata tài liệu, nhãn phân loại và quyền phải nhất quán với nhau: xoá hoặc đổi quyền tài liệu phải có hiệu lực ngay, không có cửa sổ mà index vector còn dữ liệu cũ.

## Tiêu chí đánh giá

1. Lọc quyền chính xác, không rò rỉ (quan trọng nhất).
2. Nhất quán giữa metadata và vector khi cập nhật/xoá.
3. Độ trễ p95 < 400 ms ở 1 triệu chunk (NFR-2).
4. Số hệ thống phải vận hành trên laptop.
5. Hỗ trợ tìm kiếm từ khoá cho hybrid search.

## Các phương án

### Phương án 1 — pgvector trong PostgreSQL sẵn có
- Ưu: một hệ thống; vector, metadata, ACL trong cùng transaction; Row Level Security làm lớp phòng thủ thứ hai; `tsvector` cho nhánh từ khoá; backup một nơi.
- Nhược: kết hợp lọc chặt + HNSW có thể giảm recall hoặc phải quét nhiều hơn; hiệu năng ở quy mô hàng chục triệu vector kém hơn hệ chuyên dụng.

### Phương án 2 — Qdrant
- Ưu: chuyên cho vector, lọc payload tốt, hiệu năng cao ở quy mô lớn.
- Nhược: thêm một hệ thống có trạng thái; ACL phải đồng bộ từ Postgres sang → cửa sổ không nhất quán khi đổi quyền/xoá; không có RLS; nhánh từ khoá cần giải pháp riêng hoặc sparse vector.

### Phương án 3 — OpenSearch
- Ưu: tìm kiếm từ khoá mạnh + k-NN trong một hệ.
- Nhược: nặng nhất cho laptop (JVM); cùng vấn đề đồng bộ ACL; vận hành phức tạp.

## Quyết định

Chọn **pgvector** (image `pgvector/pgvector:pg16`).

- Bảng `chunks` giữ `embedding vector(1024)`, `tsv tsvector` sinh tự động, `tenant_id`, `acl_groups`, `quarantined`.
- Index: HNSW (`vector_cosine_ops`) cho vector; GIN cho `tsv` và `acl_groups`; B-tree cho `tenant_id`.
- Điều kiện quyền nằm trong mệnh đề `WHERE` của **cả hai** nhánh tìm kiếm; RLS theo `app.tenant_id` bật trên `documents` và `chunks`.

## Hệ quả

- (+) Không có cửa sổ rò rỉ khi đổi quyền: đổi `acl_groups` và truy vấn cùng một database.
- (+) Bớt một hệ thống; migration schema một nơi (Alembic).
- (−) Cần theo dõi recall khi lọc chặt (người dùng ít quyền, lọc loại bỏ phần lớn ứng viên HNSW) → đo recall@6 riêng cho nhóm ít quyền trong eval tuần 7; nếu thấp, tăng `hnsw.ef_search` hoặc dùng iterative index scan của pgvector.
- (−) Nhánh từ khoá dùng cấu hình `simple` (không có từ điển tiếng Việt) → kiểm tra chất lượng ở tuần 7.
- Kiểm chứng: NFR-2 bằng dữ liệu tổng hợp 1 triệu chunk ở tuần 15.

## Điều kiện xem lại

- Trên ~10 triệu chunk, hoặc NFR-2 không đạt sau tinh chỉnh.
- Recall@6 của nhóm ít quyền thấp hơn nhóm nhiều quyền quá 10 điểm.
