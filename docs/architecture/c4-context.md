# C4 cấp 1 — System Context

Bến AI Platform nhìn từ ngoài vào: ai dùng, hệ thống nào nó phụ thuộc.

```mermaid
flowchart TB
    enduser["👤 Nhân viên / Khách hàng"]
    dev["👤 Developer các team"]
    admin["👤 Platform Admin / Tenant Admin"]
    approver["👤 Người duyệt"]
    gov["👤 DPO / Data Owner / Security"]

    apps["Ứng dụng của các team<br/>[Hệ thống bên ngoài]<br/>Chatbot CSKH, Trợ lý HR, Agent Finance"]

    ben["BẾN AI PLATFORM<br/>[Hệ thống đang thiết kế]<br/>Gateway, RAG, Agent, Governance"]

    anthropic["Anthropic API<br/>[Bên ngoài]"]
    openai["OpenAI API<br/>[Bên ngoài]"]
    idp["Identity Provider<br/>[Nội bộ — Keycloak]"]
    mail["Mail server<br/>[Nội bộ]"]
    findb["DB báo cáo tài chính<br/>[Nội bộ]"]

    enduser -->|"dùng"| apps
    dev -->|"xây"| apps
    apps -->|"HTTPS, API key bk_live_*"| ben
    admin -->|"Portal"| ben
    approver -->|"Duyệt hành động"| ben
    gov -->|"Phân loại, DSR, AI Registry"| ben
    ben -->|"HTTPS, key tổ chức<br/>chỉ dữ liệu ≤ Internal, PII đã che"| anthropic
    ben -->|"HTTPS, key tổ chức"| openai
    ben -->|"OIDC"| idp
    ben -->|"SMTP, chỉ khi đã duyệt"| mail
    ben -->|"SQL read-only"| findb
```

## Danh mục phần tử

| Phần tử | Loại | Trách nhiệm | Quan hệ với Bến |
|---|---|---|---|
| Nhân viên / Khách hàng | Người | Dùng app của tenant | Không trực tiếp; `user_ref` đi qua app |
| Developer | Người | Tích hợp app với Bến | API key, SDK OpenAI/Anthropic |
| Platform Admin / Tenant Admin | Người | Vận hành nền tảng / tenant | Portal |
| Người duyệt | Người | Duyệt tool `write`/`external` | Portal |
| DPO / Data Owner / Security | Người | Governance, audit | Portal, OpenMetadata |
| Ứng dụng của các team | Hệ thống ngoài | Nghiệp vụ của từng team | Client duy nhất của data plane |
| Anthropic API, OpenAI API | Hệ thống ngoài | Suy luận model | Chỉ gateway gọi; chịu ràng buộc residency và PII |
| Identity Provider | Hệ thống nội bộ | Đăng nhập, nhóm phòng ban | Nguồn nhóm cho ACL và RBAC |
| Mail server | Hệ thống nội bộ | Gửi email | Chỉ qua tool `send_email` sau khi duyệt |
| DB báo cáo tài chính | Hệ thống nội bộ | Dữ liệu doanh thu | Chỉ qua tool `sql_query`, user read-only |

## Ranh giới tin cậy

| Ranh giới | Bên trong | Bên ngoài | Kiểm soát chính |
|---|---|---|---|
| B1 — Internet ↔ doanh nghiệp | Mọi thứ trừ provider | Anthropic, OpenAI | Chỉ gateway có egress; PII đã che; residency |
| B2 — App tenant ↔ Bến | Bến | App tenant | API key theo tenant, quota, không tin header tự khai |
| B3 — Người dùng Portal ↔ Bến | Bến | Trình duyệt | OIDC, RBAC theo role Keycloak |
| B4 — Bến ↔ hệ thống nội bộ | Bến | Mail, DB tài chính | Tool đã duyệt, quyền tối thiểu, người duyệt |

Chi tiết mối đe doạ theo ranh giới: [threat-model.md](../threat-model.md).
