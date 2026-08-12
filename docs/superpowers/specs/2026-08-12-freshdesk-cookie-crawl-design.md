# Chuyển crawl Freshdesk từ REST API sang cookie (UI API)

- Ngày: 2026-08-12
- Trạng thái: **thiết kế, chưa implement**
- Phạm vi: `fetch-csat`, `fetch-freshdesk-entry-coverage`, `reconcile-freshdesk-outcomes`, cộng một đường nhập cookie trên dashboard
- Thay thế: phần *transport* của `2026-08-01-freshdesk-csat-integration-design.md` và `2026-08-04-freshdesk-cs-agent-entry-coverage.md`. **Không** đổi định nghĩa metric, bucket CSAT, phân loại entry coverage, hay privacy contract của hai spec đó.

## 1. Vấn đề

Cả ba job đều gọi Freshdesk REST API v2 bằng API key:

| Job | Endpoint | Số request |
|---|---|---|
| `fetch-csat` | `/api/v2/tickets/{id}/satisfaction_ratings` + `/api/v2/tickets/{id}/conversations` | 1–2 request **mỗi ticket** |
| `fetch-freshdesk-entry-coverage` | `/api/v2/tickets?updated_since=…&per_page=50` | 1 request mỗi 50 ticket |
| `reconcile-freshdesk-outcomes` | `/api/v2/tickets/{id}/conversations` | 1 request mỗi ticket |

Population hiện tại ~8.900 ticket. `fetch-csat` một mình đã là ~9k–18k request trên quota tài khoản dùng chung, và quota Freshdesk là **rolling window cấp account** — nên job này làm CS và các tool khác trong công ty bị 429 theo.

Bằng chứng đo được trong quá trình vận hành: `fetch-csat` phải chạy `--max-workers 1 --max-duration 1500` và vẫn không xong trong một lượt, phải resume nhiều vòng qua checkpoint. Phần lớn thời gian là ngồi chờ `Retry-After` (xem `_MAX_RETRIES = 11`, `_MAX_RETRY_AFTER_SECONDS = 300` trong `freshdesk_csat.py`).

## 2. Hướng giải quyết

Dùng **Freshdesk UI API nội bộ** (`/api/_/…`, auth bằng session cookie của trình duyệt) thay cho REST API. Đây là đúng đường mà `cs-ticket-crawler` đã dùng và chạy ổn định.

Lợi thế đo được từ `cs-ticket-crawler/crawler/ui_api.py`:

- Không tiêu quota REST API của account → hết ảnh hưởng người khác.
- List `per_page=100` thay vì `50`.
- Lọc thẳng theo `created_at` bằng `query_hash[…]` → không phải phân trang sâu theo `updated_since`.
- `include=requester,stats,company,survey` — **có thể** lấy survey ngay trong list response.

Điểm cuối cùng là đòn bẩy lớn nhất và cũng là ẩn số lớn nhất — xem §3.

### 2.1 Quyết định đã chốt (PO, 2026-08-12)

| Quyết định | Chọn |
|---|---|
| Quyền nhập cookie qua UI | Ai vào được dashboard đều nhập được (chỉ chặn CSRF bằng action header) |
| REST API | Giữ code, mặc định tắt, chỉ chạy khi gõ tay `--auth rest`. **Không** tự động fallback |
| Phạm vi | Cả 3 job, làm theo phase |

Ghi nhận rủi ro của quyết định 1 (PO đã biết và chấp nhận): dashboard hiện đứng sau HTTP Basic Auth ở tầng Traefik và link đã được chia cho PO team khác, nên bất kỳ ai có link + basic auth đều ghi được credential Freshdesk vào server. Nếu sau này muốn siết, thêm `FRESHDESK_COOKIE_ADMIN_TOKEN` là thay đổi cục bộ trong §6.3, không phá kiến trúc.

Lý do **không** tự động fallback REST: cookie hết hạn lúc 3 giờ sáng mà job âm thầm rơi về REST thì tái hiện đúng sự cố rate-limit đang muốn bỏ, lại còn khó phát hiện hơn. Fail closed, báo lên UI — cùng triết lý với `llm_client.py` (thiếu config thì raise, không đoán số).

## 3. Discovery spike — PHẢI làm trước, chặn thiết kế phía sau

Không đọc được từ source code; phải probe thật bằng một cookie hợp lệ trên máy local.

Logic CSAT hiện tại (`collect_ticket_ratings`, `_bot_response` trong `freshdesk_csat.py`) cần **đúng 7 field mỗi rating**:

```
id, ticket_id, survey_id, created_at, agent_id, ratings.default_question, feedback
```

Cần trả lời:

**S1.** `GET /api/_/tickets?include=…,survey&query_hash[…]` trả về gì trong field survey của từng ticket? Có đủ 7 field trên không?

**S2.** `GET /api/_/tickets/{id}?include=requester,stats,company,survey,ticket_form` trả về gì trong `survey`? Có `agent_id` không?

**S3.** Có endpoint UI API riêng cho satisfaction rating không? Thử `/api/_/tickets/{id}/surveys`, `/api/_/tickets/{id}/survey_results`, `/api/_/surveys/…`. Mở DevTools trên trang ticket Freshdesk, xem tab Network lúc phần CSAT render — đó là câu trả lời chắc chắn nhất.

**S4.** `GET /api/_/tickets/{id}/conversations` trả về field nào? `reconcile-freshdesk-outcomes` và nhánh null-agent của CSAT cần: `id`, `user_id`, `incoming`, `private`, `source`, `created_at`, `category`, và `body`/`body_text` (để dò marker `autorep`). Tên field UI API có thể khác REST.

**S5.** Ở nhịp thật (vài nghìn request), UI API có 429 không? README của `cs-ticket-crawler` viết "không rate-limit", nhưng chính `get_with_retry()` của nó vẫn xử lý 429 — nên coi đây là **chưa xác minh ở volume của mình**, giữ nguyên đường retry.

### 3.1 Hai nhánh thiết kế phụ thuộc kết quả

- **Nhánh A — survey nằm trong list response (S1 = có đủ):** `fetch-csat` đổi từ "N request mỗi ticket" sang "1 request mỗi 100 ticket". ~8.900 ticket còn ~89 request. Backfill xong trong vài phút thay vì vài giờ. Đây là kết quả mong muốn.
- **Nhánh B — phải gọi từng ticket (S1 = thiếu field):** vẫn N request nhưng không tiêu quota REST và không phải chờ `Retry-After`. Vẫn thắng lớn về thời gian, nhưng backfill vẫn tính bằng chục phút. Checkpoint/resume giữ nguyên vai trò.

Implement §4 theo cách để **cả hai nhánh dùng chung** interface phía trên; chỉ khác implementation bên trong client.

Deliverable của spike: một file ghi lại response shape thật (đã bỏ PII) để làm cơ sở viết mapper — đặt ở `docs/superpowers/specs/2026-08-12-freshdesk-ui-api-probe.md`. **Không** commit cookie hay dữ liệu ticket thật.

## 4. Kiến trúc client

Giữ nguyên mọi dataclass đang có (`CSATResponse`, `ConversationMetadata`, `FreshdeskTicketMetadata`, `CSATCache`) — đây là ranh giới ổn định, và giữ nó nghĩa là toàn bộ tầng tính toán, cache, projection, UI phía sau **không phải sửa gì**.

Thêm một client thứ hai cùng bề mặt method:

```
freshdesk_csat.py
  FreshdeskClient          # REST v2, giữ nguyên, không sửa logic
  FreshdeskUIClient        # MỚI — UI API, cookie auth
```

Bề mặt chung (đã tồn tại trên `FreshdeskClient`, `FreshdeskUIClient` phải khớp):

```python
get_satisfaction_ratings(ticket_id) -> tuple[object, ...]
get_conversation_metadata(ticket_id, *, should_stop=None) -> tuple[ConversationMetadata, ...]
list_ticket_metadata(*, updated_since, ..., on_page=None, should_stop=None) -> tuple[FreshdeskTicketMetadata, ...]
```

Nguyên tắc:

1. **Normalize ngay tại biên client.** `FreshdeskUIClient.get_satisfaction_ratings()` trả về đúng shape mà `_bot_response()` đang kỳ vọng (7 field ở §3). Mọi khác biệt tên field UI-vs-REST chết trong client, không rò ra ngoài. `collect_ticket_ratings()`, `_survey_follows_bot_response()`, `_bot_response()` **không được sửa**.
2. **Nếu nhánh A khả thi**, thêm một method mới `list_ratings_by_week(week_ticket_ids)` cho đường batch, và `fetch_csat_population()` ưu tiên method này khi client có nó (`getattr(client, "list_ratings_by_week", None)` — cùng pattern đang dùng cho `get_conversation_metadata` ở dòng ~415). Không có thì rơi về vòng lặp per-ticket hiện tại.
3. **Giữ nguyên giới hạn an toàn của `_get_json`:** `_MAX_RESPONSE_BYTES`, chặn redirect, error message đã sanitize, `should_stop` deadline. Port hết sang client mới; đừng viết lại bằng `requests` trần như crawler.
4. **Cookie sai/hết hạn (401/403) raise `FreshdeskCookieExpired`** — subclass mới của `FreshdeskCSATError`. **Không** `sys.exit()` như `cs-ticket-crawler` làm; đây là service, phải trả lỗi có cấu trúc để CLI và web cùng xử lý.
5. Giữ `time.sleep(0.1)` giữa các page như crawler — lịch sự với UI API, và là van an toàn nếu S5 hoá ra có throttle.

### 4.1 Chọn client

```python
def _freshdesk_client(auth: str):   # auth: "cookie" | "rest"
```

- `--auth cookie` (mặc định): đọc cookie theo §5. Không có cookie → raise `FreshdeskCookieMissing`, exit khác 0, **không** rơi về REST.
- `--auth rest`: đường cũ, giữ để chạy tay khi cần.

Cả ba subcommand nhận `--auth`, mặc định `cookie`.

## 5. Lưu cookie

Cookie là session token của một tài khoản CS thật — đối xử như credential.

| | |
|---|---|
| Vị trí | `/app/runtime/freshdesk_cookie` (local: `runtime/freshdesk_cookie`) |
| Mode | `0600`, thư mục `0700` |
| Ghi | atomic — dùng lại `_atomic_private_json()` đã có trong `freshdesk_csat.py` |
| Nguồn phụ | env `FRESHDESK_COOKIE` (bootstrap lần đầu). **File thắng env** nếu cả hai có |
| Không bao giờ | in ra log, đưa vào payload API, commit, để trên argv |

`runtime/` đã có persistent storage trên Agent Base (tạo 2026-08-12) nên cookie sống qua redeploy. Trước ngày đó thì thiết kế này bất khả thi — đó là lý do làm được bây giờ.

Metadata đi kèm, lưu riêng ở `runtime/freshdesk_cookie_state.json` (không nhạy cảm, đọc được từ web layer):

```json
{
  "schema_version": 1,
  "updated_at": "2026-08-12T10:00:00Z",
  "last_verified_at": "2026-08-12T10:00:00Z",
  "last_failure_at": null,
  "state": "ok"
}
```

`state` ∈ `ok` | `expired` | `missing`. Timestamp là ISO-8601 UTC hậu tố `Z`, khớp `_format_utc()` đang dùng.

Job cập nhật file này: verify thành công → `ok` + `last_verified_at`; gặp 401/403 → `expired` + `last_failure_at`. **Không** ghi cookie vào file state.

## 6. UX cookie hết hạn

Nguyên tắc: người xem dashboard đông hơn người sửa được cookie. Đừng chặn màn hình của tất cả vì một section hỏng.

### 6.1 Không dùng modal tự bật

Modal chặn toàn dashboard lúc load là sai: phần lớn người mở dashboard là PO/CS đang muốn xem số, không phải người đi lấy cookie. Thay bằng ba tầng theo mức độ liên quan:

**Tầng 1 — trong section CSAT (nơi hậu quả xảy ra).** Chỗ hiện đang render `Chưa có dữ liệu CSAT từ Freshdesk.` đổi thành copy theo state:

| State | Copy |
|---|---|
| `missing` | `Chưa kết nối Freshdesk. Cần cookie để lấy dữ liệu CSAT.` + nút `Kết nối Freshdesk` |
| `expired` | `Cookie Freshdesk đã hết hạn — CSAT dừng ở <ngày cập nhật cuối>.` + nút `Cập nhật cookie` |
| `ok` nhưng thiếu tuần | giữ copy hiện tại |

**Tầng 2 — chip trong header.** Chỉ hiện khi `expired`/`missing`, đặt cạnh `runtimeChip` đang có. Nội dung ngắn: `Freshdesk: cần cookie`. Bấm vào → cuộn tới section CSAT và mở dialog. Người đang đọc section khác vẫn thấy, mà không bị chặn.

**Tầng 3 — dialog, chỉ mở khi người dùng chủ động bấm.**

### 6.2 Dialog nhập cookie

Yêu cầu cụ thể:

- `<dialog>` thật (native), focus trap, `Esc` đóng, trả focus về nút đã mở — cùng pattern `helpPanel` trong `AppShell.tsx` đang làm.
- Hướng dẫn 3 bước đánh số, ngắn, kèm link mở thẳng `https://vngzalopay.freshdesk.com`:
  1. Mở Freshdesk và đăng nhập
  2. DevTools (`F12`) → tab Network → bấm một ticket bất kỳ → chọn request bất kỳ → copy toàn bộ giá trị header `Cookie`
  3. Dán vào ô dưới
- Ô nhập là `<textarea>` chứ không phải `<input>` — cookie dài vài trăm ký tự, người dùng cần thấy cái mình dán. Đặt `autocomplete="off"`, `spellcheck="false"`, `rows={4}`.
- Validate client-side trước khi gửi (chỉ để bắt lỗi dán nhầm, không phải bảo mật): không rỗng, có ký tự `=`, độ dài trong khoảng hợp lý.
- Nút submit có 3 trạng thái rõ: `Kiểm tra và lưu` → `Đang kiểm tra…` (disabled) → kết quả.
- **Server verify trước khi lưu.** Không bao giờ persist cookie chưa xác minh — cookie sai mà lưu vào thì job đêm chết âm thầm.
- Kết quả hiện ngay trong dialog:
  - Thành công: `Cookie hợp lệ, đã lưu. Dữ liệu sẽ cập nhật trong lượt chạy kế tiếp.` → tự đóng sau ~1,5s, đồng thời bắn message vào `#liveStatus` (`role="status"`) cho screen reader.
  - Thất bại: `Cookie không hợp lệ hoặc đã hết hạn. Lấy lại cookie mới rồi thử lại.` Giữ nguyên nội dung đã nhập để người dùng sửa, không xoá trắng.
- Sau khi đóng, ô nhập bị clear khỏi state React. Không log, không đẩy vào analytics, không đưa vào URL.

### 6.3 API

```
GET  /api/freshdesk-cookie        -> { state, updated_at, last_verified_at }
POST /api/freshdesk-cookie        body: { cookie: string }
```

- `GET` **không bao giờ** trả cookie hoặc bất kỳ phần nào của nó — chỉ state + timestamp.
- `POST` bắt buộc có action header giống `/api/refresh` (`_REFRESH_ACTION_HEADER` pattern, xem `web.py:266`) để chặn CSRF. Thiếu header → `403 {"code": "cookie_action_required"}`.
- `POST` giới hạn body ≤ 8 KB; quá → `413`.
- Luồng xử lý `POST`: verify live bằng **một** request UI API rẻ nhất (`GET /api/_/tickets?only=count` với cửa sổ 1 ngày) → 200 thì ghi file `0600` + state `ok` rồi trả `202`; 401/403 thì **không ghi gì** và trả `400 {"code": "cookie_invalid"}`.
- Response của `POST` không echo lại cookie.
- Rate limit đơn giản: tối đa 5 lần POST / phút / process, tránh biến endpoint này thành công cụ dò cookie.

Ràng buộc kiến trúc phải giữ: hiện tại **serving process không gọi Freshdesk** (ghi trong `CLAUDE.md`). Endpoint này phá lệ đó một chút — chấp nhận, nhưng giới hạn cứng: web layer chỉ được gọi **đúng một** request verify `only=count`, không fetch dữ liệu. Mọi việc lấy dữ liệu vẫn thuộc job CLI. Ghi rõ điều này vào `CLAUDE.md` khi implement.

### 6.4 Trigger fetch sau khi lưu

Sau `POST` thành công, đánh dấu để job chạy sớm. Đơn giản nhất và không cần thêm hạ tầng: ghi `runtime/freshdesk_cookie_state.json` với `state: "ok"`, rồi để cron 6 tiếng bắt. Nếu muốn phản hồi tức thì thì spawn job nền — **chỉ làm nếu đã giải quyết được chuyện single-worker và refresh lock đang là process-local**. Khuyến nghị: phase 1 để cron bắt, và dialog nói đúng sự thật là dữ liệu cập nhật ở lượt chạy kế tiếp.

## 7. Backfill rồi schedule

**Backfill** (làm một lần, sau khi 3 phase xong):

```bash
weekly-cs-report fetch-csat --weeks 20 --auth cookie
```

- Checkpoint hiện tại ở `/app/artifacts/freshdesk_csat/checkpoint.json` **dùng lại được nguyên vẹn** — nó lưu theo tuần và theo `response_key`, không dính transport. Backfill dở dang bằng REST (đang ở 382.944 byte) resume tiếp bằng cookie được, không phải chạy lại từ đầu.
- `--max-workers`: nhánh A không cần (list-based). Nhánh B đặt mặc định `5` như crawler, cho phép chỉnh.
- `--max-duration`: nâng mặc định lên, vì lý do tồn tại của mức 1500s là chờ `Retry-After` của REST. Đề xuất `3600`, khớp `timeout` của scheduled task.

**Schedule**: bật lại task `freshdesk-refresh` (uuid `k135w2gaocn1xy8m1pzzlabn`, hiện `enabled: false`, tắt ngày 2026-08-12 để dừng crawl REST), đổi command:

```
weekly-cs-report fetch-csat --auth cookie; weekly-cs-report fetch-freshdesk-entry-coverage --auth cookie; weekly-cs-report reconcile-freshdesk-outcomes --auth cookie
```

Giữ `;` chứ không `&&` — ba job độc lập, một job hỏng không được chặn hai job kia. Giữ cron `0 */6 * * *`. Lưu ý giới hạn 255 ký tự của cột `command` trong Coolify.

## 8. Phase

Mỗi phase phải xanh trước khi sang phase sau.

### Phase 0 — Discovery spike
- Trả lời S1–S5 (§3), viết `2026-08-12-freshdesk-ui-api-probe.md`.
- **Gate:** biết chắc đi nhánh A hay B.

### Phase 1 — `FreshdeskUIClient` + `fetch-csat`
- Thêm `FreshdeskUIClient`, `FreshdeskCookieMissing`, `FreshdeskCookieExpired`, đọc/ghi cookie theo §5.
- `--auth` cho `fetch-csat`.
- Test: unit test mapper UI→dataclass bằng fixture lấy từ Phase 0 (đã bỏ PII); test cookie thiếu → raise đúng loại; test 401 → `FreshdeskCookieExpired` + state file thành `expired`.
- **Gate:** `fetch-csat --auth cookie` chạy được ≥ 1 tuần trên local, số CSAT khớp với dữ liệu REST đã có trong cache cũ. Đây là kiểm chứng quan trọng nhất — hai transport phải ra cùng số.

### Phase 2 — UI nhập cookie
- `GET`/`POST /api/freshdesk-cookie`, dialog, chip header, copy theo state.
- Test: unit test route (thiếu action header → 403; cookie sai → 400 và không ghi file; cookie đúng → 202 và file mode `0600`); test component dialog; kiểm `curl … | grep -c cookie` trên `/api/dashboard` và `/api/freshdesk-cookie` phải là 0.
- Kiểm chứng UI thật bằng Chrome DevTools MCP theo `CLAUDE.md` §Kiểm chứng UI — đo tap target ≥ 44px, focus trap, `Esc`, và mobile `390x844x3`.
- **Gate:** nhập cookie hết hạn ra đúng thông báo; nhập cookie thật thì state đổi sang `ok`.

### Phase 3 — hai job còn lại
- `--auth cookie` cho `fetch-freshdesk-entry-coverage` và `reconcile-freshdesk-outcomes`.
- Entry coverage: đổi từ `updated_since` phân trang sâu sang `query_hash` lọc `created_at` — đúng thứ job này thực sự cần (nó group theo `created_at`), và bỏ được cả cơ chế trượt trang.
- **Gate:** entry coverage chạy bằng cookie ra cùng tập ticket như REST trên một cửa sổ đối chứng.

### Phase 4 — Backfill + bật cron
- Backfill CSAT đủ 20 tuần, xác nhận `runtime/csat_cache.json` tồn tại và checkpoint bị xoá (đây là tín hiệu `complete=True` duy nhất đáng tin).
- Bật lại `freshdesk-refresh` với command mới.
- **Gate:** dashboard hiện đủ CSAT; theo dõi qua một chu kỳ cron.

## 9. Ràng buộc không được phá

- Không đổi `_STORAGE_VERSION`, schema cache, hay bất kỳ metric nào. Đây là thay transport, không thay ý nghĩa số.
- Ranh giới PII giữ nguyên: browser chỉ được thấy Ticket ID. UI API trả **nhiều** field hơn REST (`requester`, `company`, `stats`, body hội thoại) — mapper phải **projection ngay tại client**, không được để payload thô đi tiếp vào cache hay snapshot. Đây là rủi ro rò rỉ mới do chính spec này tạo ra; xử lý ở đúng một chỗ.
- Raw trace/observation vẫn không bao giờ serialize ra đĩa.
- Không thêm runtime dependency. `httpx` đã có, đủ dùng; **không** thêm `requests` chỉ vì crawler dùng nó.
- Cookie không xuất hiện trong log, error message, payload API, hay git.

## 10. Rủi ro

| Rủi ro | Xử lý |
|---|---|
| S1 = thiếu field → nhánh B, backfill vẫn lâu | Vẫn thắng lớn so với hiện tại (không còn chờ `Retry-After`); checkpoint gánh phần còn lại |
| Cookie hết hạn lúc không ai để ý | State surfacing §6 là biện pháp chính. Không tự gia hạn được — làm vậy phải headless login, tức là nhét mật khẩu tài khoản CS vào server. **Không làm.** |
| UI API là API nội bộ không cam kết → Freshdesk đổi shape là gãy | Mapper tập trung một chỗ; test có fixture; job fail closed và báo lên UI thay vì ghi số sai |
| POST cookie mở cho mọi người xem dashboard | PO đã chấp nhận (§2.1). Đường siết sau: thêm `FRESHDESK_COOKIE_ADMIN_TOKEN`, sửa cục bộ §6.3 |
| UI API cũng throttle ở volume lớn (S5 chưa xác minh) | Giữ nguyên `get_with_retry` + sleep 0.1s giữa page; đừng bỏ đường retry vì tin README của crawler |
