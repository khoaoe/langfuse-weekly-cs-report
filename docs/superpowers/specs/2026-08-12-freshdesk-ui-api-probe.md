# Phase 0 probe kết quả — Freshdesk UI API shape

- Ngày: 2026-08-12
- Cookie test: session hợp lệ của account CS thật, lấy thủ công qua DevTools, chạy trên máy local, không commit.
- Đối chứng: ticket `7005238` — đã có rating thật trong `checkpoint.json` do REST API fetch trước đó (chạy trên container qua Coolify exec), dùng để so hai transport trên **cùng một ticket**.

## Kết quả

### S1/S2 — survey field trong list/detail response
`GET /api/_/tickets?include=survey` và `GET /api/_/tickets/{id}?include=survey` — field `survey` rỗng/null trên mọi ticket đã thử (30 ticket gần nhất + 1 ticket detail). **Không dùng được** để lấy CSAT qua list.

### S3 — endpoint riêng cho rating: **CÓ, và trùng khớp hoàn toàn REST**

`GET /api/_/tickets/{id}/satisfaction_ratings` tồn tại (khác với `/surveys`, `/survey_results` — cả hai 404).

Test trên ticket `7005238` (đã biết có rating qua REST):

```
status: 200
top-level keys: agent_id, created_at, feedback, group_id, id, ratings, survey_id, ticket_id, updated_at, user_id
ratings sub-keys: default_question, question_43000076415, question_43000076416, question_43000076417
```

Cả 7 field mà `_bot_response()` (`freshdesk_csat.py`) cần đều có, **đúng tên, đúng kiểu**:

| Field | REST kỳ vọng | UI API thực tế |
|---|---|---|
| `id` | int | int |
| `ticket_id` | int | int |
| `survey_id` | int | int |
| `created_at` | str (ISO) | str |
| `agent_id` | int hoặc null | null (khớp — null-agent branch) |
| `ratings.default_question` | int | int |
| `feedback` | str hoặc null | str |

**Kết luận: không cần mapper.** `FreshdeskUIClient.get_satisfaction_ratings()` chỉ đổi path (`/api/v2/` → `/api/_/`) và auth (Basic Auth API key → header `Cookie`), parse y hệt REST client hiện tại.

### S4 — conversations shape: **trùng khớp hoàn toàn REST**

`GET /api/_/tickets/{id}/conversations` — test trên ticket `7083448`:

```
top-level keys (đầy đủ): attachments, auto_response, automation_channel_type, automation_id,
automation_type_id, bcc_emails, body, body_text, category, cc_emails, cloud_files, created_at,
deleted, delivery_details, email_failure_count, from_email, has_quoted_text, id, incoming,
last_edited_at, last_edited_user_id, outgoing_failures, private, source, structured_body,
support_email, thread_id, thread_message_id, threading_type, ticket_id, to_emails, updated_at,
user_id
```

6 field `ConversationMetadata` cần đều có, đúng tên: `id`, `user_id`, `incoming`, `private`, `source`, `created_at`, `category`, cộng `body`/`body_text` cho marker `autorep`.

**Kết luận: không cần mapper cho conversations.**

### List endpoint cho entry-coverage
`GET /api/_/tickets` với `query_hash[…]` lọc `created_at`, trả `id` + `created_at` ở top level (xác nhận trong response S1) — đủ cho `FreshdeskTicketMetadata`. `per_page=100` (REST hiện dùng 50). Filter theo `created_at` trực tiếp — không cần `updated_since` + phân trang sâu như REST.

### S5 — rate limit ở volume thật
**Chưa xác minh** — chỉ chạy ~140 request trong spike này (30 + 100 scan + vài request lẻ), không có 429 nào. Không đủ để kết luận cho volume ~9.000 ticket. Giữ nguyên đường retry `get_with_retry`-style theo spec §4 điểm 3, không bỏ vì spike sạch.

## Quyết định cho §4 kiến trúc (cập nhật so với spec gốc)

Spec gốc dự tính 2 nhánh (A: batch qua list, B: per-ticket) và đặt nặng vào "normalize tại biên client". Kết quả thực tế đơn giản hơn cả hai:

- **Không có nhánh A theo nghĩa batch** — vẫn per-ticket, giống REST hiện tại.
- **Nhưng không cần mapper/normalize** — response UI API là superset gần như y hệt REST, cùng tên field. `FreshdeskUIClient` chỉ đổi transport (path prefix + auth header), giữ nguyên toàn bộ logic parse của `collect_ticket_ratings()`, `_bot_response()`, `get_conversation_metadata()`.
- Lợi ích chính không phải giảm số request, mà là **bỏ hẳn quota REST dùng chung** và **bỏ thời gian chờ `Retry-After`** — đúng vấn đề gốc (§1 spec chính).
- `list_ticket_metadata()` cho entry-coverage đổi từ `updated_since` phân trang sâu sang `query_hash` lọc `created_at`, `per_page=100` — đơn giản hơn REST, không cần sliding-window phức tạp như `cs-ticket-crawler` vì mỗi lần entry-coverage chỉ quét một cửa sổ ngày giới hạn (không lùi hàng năm).

Implementation đi thẳng theo hướng: `FreshdeskUIClient` là bản sao gần như 1:1 của `FreshdeskClient` (`freshdesk_csat.py`), khác đúng 3 chỗ: base URL path prefix, cách auth (`Cookie` header thay `httpx.BasicAuth`), và xử lý 401/403 raise `FreshdeskCookieExpired` thay vì lỗi HTTP chung.
