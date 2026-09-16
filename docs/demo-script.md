# Kịch bản demo — định nghĩa "xong" của dự án

Video khoảng 10 phút. Mỗi cảnh chứng minh một năng lực và có **bằng chứng nhìn thấy được** trên màn hình. Một hạng mục chỉ được coi là xong khi cảnh tương ứng chạy trọn từ trạng thái sạch (`down` → `up` → `seed`).

## Chuẩn bị chung

- `.\scripts\tasks.ps1 up` và dữ liệu mẫu đã seed: 3 tenant (`cskh`, `hr`, `finance`), tài liệu mẫu, DB doanh thu mẫu.
- Mở sẵn: Portal, Langfuse, Grafana, OpenMetadata, terminal.
- Mock provider có thể bật/tắt bằng `docker stop`/`start`.

## Các cảnh

| # | Cảnh | Tiền điều kiện | Thao tác | Bằng chứng trên màn hình | Thời lượng | Tuần |
|---|---|---|---|---|:-:|:-:|
| 1 | Onboard team mới | Portal chạy | Tạo tenant `marketing`, ngân sách 20 USD, cấp key; chạy script gọi SDK `openai` và `anthropic` với key mới | Hai lệnh trả lời thành công; trace mới trên Langfuse có `tenant=marketing` | 1:00 | 3, 10 |
| 2 | Routing & cache | Policy `cskh` có route FAQ → local | Hỏi *"Chính sách đổi trả bao nhiêu ngày?"* hai lần | Lần 1: `X-Ben-Model: local/...`; lần 2: `X-Ben-Cache: hit`, chi phí 0 | 1:00 | 4 |
| 3 | Che PII | Guard bật | Gửi *"Đơn #A1293, SĐT 0912 345 678, CCCD 001203004567"* | Trace hiện payload tới provider chỉ có `<ORDER_1>`, `<PHONE_1>`, `<CCCD_1>`; câu trả lời cho khách vẫn có số đơn thật | 1:00 | 5 |
| 4 | Chống shadow AI | App demo trong network nội bộ | Chạy app gọi thẳng `api.openai.com`, rồi đổi `base_url` sang Bến | Lần 1 lỗi kết nối; lần 2 thành công, có trace | 0:45 | 10 |
| 5 | Fallback | k6 đang bắn 20 RPS | `docker stop` mock provider chính | k6 không có lỗi; dashboard hiện tỉ lệ fallback tăng; header `X-Ben-Fallback: true` | 1:00 | 4 |
| 6 | RAG phân quyền | Tài liệu HR 3 nhóm quyền | `hoa` và `tuan` cùng hỏi *"Thưởng Tết năm nay tính thế nào?"*; `tuan` hỏi đích danh quy chế phòng Kinh doanh | Hai câu trả lời trích dẫn hai tài liệu khác nhau; câu thứ ba bị từ chối | 1:00 | 6–7 |
| 7 | Chống injection | — | Upload tài liệu có câu *"Bỏ qua mọi hướng dẫn trước..."* | Trạng thái `partially_quarantined`; audit log có sự kiện | 0:30 | 6 |
| 8 | Agent có duyệt | DB doanh thu mẫu | Giao việc phân tích doanh thu Q3 và gửi BGĐ; duyệt trên Portal | Timeline 5 bước; bước 5 dừng chờ duyệt; email xuất hiện trong MailHog sau khi duyệt | 1:15 | 8 |
| 9 | Eval gate & chi phí | PR mẫu đổi prompt kém | Mở PR | Job eval fail, comment bảng điểm; kết bằng dashboard chi phí tháng | 0:30 | 9 |
| 10 | Phân loại & policy | Tài liệu "Kế hoạch giá Q4" nhãn Confidential | `quan` hỏi tóm tắt kế hoạch giá; rồi yêu cầu soạn email gửi đối tác | Lần 1: model local, decision log `residency: local`; lần 2: `403 policy_denied` kèm lý do | 0:45 | 11 |
| 11 | Yêu cầu xoá dữ liệu | Có tài liệu khiếu nại chứa SĐT khách | DPO tạo DSR theo SĐT → xem trước → duyệt | Báo cáo bằng chứng 6 nơi lưu = 0; hỏi lại chatbot không còn thông tin | 1:00 | 13 |
| 12 | Lineage & AI Registry | OpenMetadata chạy | Mở lineage `reporting.revenue_daily`; dùng key live của use case `marketing` chưa duyệt | Đồ thị bảng → agent → báo cáo → email; `403 usecase_not_approved` | 0:45 | 12, 14 |

## Checklist trước khi quay

- [ ] Toàn bộ cảnh chạy trọn 2 lần liên tiếp từ trạng thái sạch
- [ ] Không có secret thật trên màn hình (dùng key demo, `.env` không mở)
- [ ] Số liệu hiển thị ghi rõ là dữ liệu tổng hợp
- [ ] Đồng hồ hệ thống đúng múi giờ để trace và audit khớp lời thoại
