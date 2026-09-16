# Thang phân loại dữ liệu — bản nháp

| | |
|---|---|
| Phiên bản | 0.1 nháp — 14/09/2026 (tuần 1) |
| Chốt | Tuần 11, cùng `config/classification-scheme.yaml` |
| Thiết kế đầy đủ | [PROJECT.md §27](../PROJECT.md#27-phân-loại-dữ-liệu) |

## Mức mật

| Mức | Định nghĩa | Ví dụ ShopViet | Gửi model cloud | Model local |
|---|---|---|:-:|:-:|
| Public | Được phép công bố ra ngoài | FAQ, chính sách đổi trả công khai | ✅ | ✅ |
| Internal | Chỉ nhân viên; lộ ra gây thiệt hại nhỏ | Quy chế chung, quy trình | ✅ nếu hợp đồng provider cam kết không huấn luyện | ✅ |
| Confidential | Chỉ nhóm được phép; lộ ra gây thiệt hại đáng kể | Kế hoạch giá, doanh thu chi tiết, quy chế thưởng theo phòng | ❌ | ✅ |
| Restricted | Lộ ra gây thiệt hại nghiêm trọng; dữ liệu cá nhân nhạy cảm dạng thô | Lương từng người, CCCD, số tài khoản | ❌ | ❌ ở dạng thô |

## Thẻ dữ liệu cá nhân

| Thẻ | Ý nghĩa |
|---|---|
| `pii:none` | Không có dữ liệu cá nhân |
| `pii:basic` | Họ tên, SĐT, email, địa chỉ, mã đơn gắn với người |
| `pii:sensitive` | Dữ liệu cá nhân nhạy cảm — danh mục lấy theo văn bản pháp luật hiện hành |

## Quy tắc cốt lõi

1. Nhãn cao nhất trong context quyết định model và hành động được phép.
2. Hệ thống chỉ được **đề xuất nâng** nhãn, không bao giờ tự hạ.
3. Chưa xác nhận → dùng nhãn cao hơn giữa đề xuất và lựa chọn của owner.
4. Hạ nhãn: Confidential cần Data Owner; Restricted cần Data Owner + DPO; luôn có lý do và audit.

## Việc cần làm trước khi chốt (tuần 11)

- [ ] Đối chiếu danh mục dữ liệu cá nhân nhạy cảm với văn bản pháp luật hiện hành
- [ ] Rà soát tài liệu mẫu của 3 tenant, gán nhãn thử, ghi các trường hợp khó phân loại
- [ ] Quyết định có ánh xạ sang cách phân loại của Luật Dữ liệu hay không
- [ ] Viết `config/classification-scheme.yaml` và test cho rule đề xuất nhãn
