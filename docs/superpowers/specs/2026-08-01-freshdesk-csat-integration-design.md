# CSAT từ Freshdesk — nguồn dữ liệu thứ hai

**Ngày:** 2026-08-01 · **Sửa theo dữ liệu live:** 2026-08-03
**Trạng thái:** Đã implement đến dashboard v12. PO đã ký privacy deviation và chốt dashboard
**chỉ lấy survey được Freshdesk gắn cho CS-agent “Admin CS ZaloPay”**, không
hiển thị CSAT của human CS. Giai đoạn 0 đã quét toàn bộ population, resolver đã
khớp đúng một agent active và config riêng tư đã được ghi mà không lộ ID ra
output. Runtime backfill 13 tuần là gate bắt buộc trước nghiệm thu dữ liệu
live. **Gate này đã hoàn tất ngày 2026-08-02:** cache mode `0600` có đủ 13
tuần, 2.907 response được kiểm tra và 824 response gắn đúng bot được publish;
ba token quan sát được vẫn chỉ là `-103`, `100`, `103`. Giai đoạn 4 đã hoàn tất
gate identity ngày 2026-08-03: private artifact mode `0600` có 55 candidate,
được materialize bảo thủ thành 45 human agent và 10 account bị loại; config
được bind bằng source hash. Tên/ID không đi vào output, snapshot hay tài liệu.
**Người viết spec:** Claude · **Người implement:** Codex (GPT 5.6)
**Phạm vi:** Backend + CLI mới + payload mới + frontend. **Có bump `_STORAGE_VERSION`.**

### Revision 2026-08-02 — binding

1. Xoá thiết kế so sánh CSAT AI với human. Dashboard chỉ có một cohort:
   response có `satisfaction_ratings.agent_id` bằng đúng bot ID đã duyệt.
2. `agent_id = null` **không phải human** và không được suy ra từ conversation để
   đưa vào CSAT. Mọi response null/agent khác bị loại khỏi metric chính.
3. Response identity dùng hash của `satisfaction_ratings[].id` đã quan sát ổn
   định; natural key chứa `agent_id` bị huỷ vì 1.577 response thiếu field này.
4. API rating chỉ trả mã số, không trả nhãn lựa chọn. Lưu `rating_raw` + bucket;
   exact text tiếng Việt là copy UI, không giả là `rating_label_raw` từ API.
5. Conversation chỉ phục vụ đối chiếu outcome ở Giai đoạn 4. Dòng survey
   feedback (`source = 6`) không phải agent reply và bắt buộc bị loại.
6. Chỉ thị PO ngày 2026-08-02: *"trên dashboard tôi chỉ cần survey của khách
   hàng ở những response là của cs-agent \"Admin CS ZaloPay\" chứ không cần của
   human CS"*. Đây là acceptance của cohort theo exact display name; code vẫn
   phải fail closed nếu tên resolve 0 hoặc nhiều hơn 1 ID.
7. Privacy deviation comment đã ký ngày 2026-08-01 vẫn còn hiệu lực, nhưng chỉ
   áp cho comment thuộc chính response bot đã include; không mở đường cho
   comment của human/other/null-agent response.
8. Chỉ thị PO ngày 2026-08-03: không render khối đối chiếu outcome Freshdesk
   hoặc các dòng coverage/phương pháp trên dashboard. Cache và payload v12 vẫn
   giữ để tương thích/forensic; số AI First Langfuse vẫn không đổi.

### Revision 2026-08-03 — v11/v12 binding

1. Cache CSAT schema 2 vẫn lưu mọi response bot được duyệt. Dashboard v11 đổi
   grain hiển thị: `response_count` là mọi response, `ticket_count` là Ticket ID
   khác nhau; ba mức hài lòng và breakdown lấy response mới nhất của mỗi ticket
   theo `(responded_at, response_key)`.
2. Breakdown `by_outcome`, `by_dimension.skill` và
   `by_dimension.issue_category` nối latest-ticket CSAT với đúng dimension
   Langfuse hiện có. Đây là quan sát, không phải quan hệ nhân quả và không sửa
   metric Langfuse.
3. `feedback_entries` chứa mọi response có `comment_redacted != null`, nhưng
   browser gọi là **“nội dung phản hồi”** vì API chỉ chứng minh một field
   `feedback`, không chứng minh option hay free text. UI giữ 10 item/trang.
4. Bảng breakdown không còn click row để lọc. Bộ lọc rõ ràng nằm trong panel
   “Hiện nội dung phản hồi”, đổi theo Kết quả xử lý/Skill/Category và có lựa
   chọn `Tất cả` để xóa đồng thời filter phản hồi và Ticket Explorer.
5. Dashboard v12 thêm `outcome_reconciliation` riêng. Chỉ public outgoing reply
   sau bot từ approved human agent ID mới là `true`; requester/user không bao
   giờ được tính dù trùng tên, source 6 bị loại và unknown author giữ `null`.
6. Conversation body không được đọc/serialize. Cache chỉ giữ
   `human_replied_after_ai: boolean|null`; payload chỉ có aggregate theo tuần.

---

## 1. Vì sao spec này tồn tại

Dashboard hiện chỉ biết **AI có trả lời không** và **khách có mở lại ticket không**. Nó không biết **khách có hài lòng không**. Reopen là proxy tồi cho hài lòng: khách bực nhưng bỏ cuộc thì không reopen, khách hài lòng vẫn có thể hỏi tiếp việc khác.

Freshdesk có sẵn survey CSAT. PO đã dò read-only trên tenant thật và xác nhận lấy được.

Đồng thời có nghi vấn về độ chính xác của Langfuse: *"có những ticket để 'AI xử lý trọn' nhưng đọc ticket trong freshdesk thấy sau đó có CS human trả lời"*. Nếu đúng, chỉ số AI First đang bị thổi lên.

---

## 2. ⚠️ Spec này đảo ngược một quyết định user-mandated

`2026-07-31-langfuse-only-p0-data-integrity-design.md` — **Status: User-mandated** — ghi rõ:

> - The reporting package does not require or read `FRESHDESK_API_KEY`.
> - The Freshdesk dimension client/store module is removed from the executable...
> - Freshdesk ticket links may remain as operator navigation. **They are not a report data source and do not perform server-side Freshdesk reads.**

Spec đó ra ngày 2026-07-31, tức **một ngày trước** spec này.

**Cách hoà giải — tách hai mối quan tâm, không xoá quyết định cũ:**

| Thứ | Nguồn | Spec này đụng không |
|---|---|---|
| Gate P0 data integrity (`verify-dimensions --require-p0`) | **Chỉ Langfuse** | ❌ Không đụng. Vĩnh viễn. |
| 4 outcome, AI First, reopen, TPE, segment | **Chỉ Langfuse** | ❌ Không đổi cách tính |
| CSAT (mới) | Freshdesk | ✅ Đường đọc mới |
| Chỉ số lệch outcome (mới) | Freshdesk | ✅ **Chỉ báo cáo**, không sửa số Langfuse |

Điều bị gỡ ngày 31/07 là **overlay TPE applicability dùng cho gate P0** — mục đích khác hẳn. Tinh thần "gate toàn vẹn dữ liệu chỉ dựa vào một nguồn" được giữ nguyên tuyệt đối.

**Amendment 2026-08-01 đã được ghi** trong spec langfuse-only và boundary tương
ứng đã được ghi vào `PRODUCT.md`. Codex chỉ xác minh hai tài liệu này còn đúng;
không thêm amendment trùng lặp trong batch đầu tiên.

**Cảnh báo sequencing:** theo `CLAUDE.md`, gate P0 hiện **FAIL** (`coverage_issue_category=0.847 < 0.90`, `coverage_tpe=0.792 < 0.85`, `go_live=BLOCKED`). Thêm nguồn dữ liệu thứ hai khi cổng toàn vẹn còn đỏ là chồng rủi ro. PO nên cân nhắc sửa P0 trước — nhưng đây là quyết định của PO, spec chỉ nêu.

---

## 3. Sự thật đã đo về API

| Endpoint | Kết quả thật |
|---|---|
| `GET /api/v2/tickets/{id}/satisfaction_ratings` | ✅ Chạy |
| Bulk theo survey | ❌ `404` |
| Legacy toàn bộ ratings | ❌ `403` |
| `GET /api/v2/surveys` | ❌ `403` với credential hiện tại |
| `GET /api/v2/agents` | ❌ `403` với credential hiện tại |
| `GET /api/v2/ticket_fields` | ✅ Có `default_agent.choices`; resolve đúng một “Admin CS ZaloPay” |

⇒ **Mỗi ticket một request.** Đây là ràng buộc quyết định toàn bộ kiến trúc.

> **CHỐT 2026-08-01 — PO xác nhận KHÔNG mở được quyền bulk.**
> Đây là ràng buộc vĩnh viễn, không phải trở ngại tạm thời. Mọi thiết kế phải
> giả định fetch từng ticket. **Codex không được** viết code chờ endpoint bulk,
> để cờ bật/tắt cho bulk, hay ghi TODO xin quyền. Fetch tăng dần ở Giai đoạn 1
> là đường duy nhất, và nó là thứ giữ chi phí ở mức chấp nhận được
> (~935 request mỗi lần chạy thay vì 6.663).

Đã quét đủ **6.798 ticket / 13 tuần**, thấy **2.898 response**. Trường đã quan
sát: `id`, `ratings.default_question`, `feedback`, `ticket_id`, `survey_id`,
`agent_id`, `created_at`, `updated_at`.

- `satisfaction_ratings[].id` có mặt và không collision trong population này.
- `agent_id` thiếu ở **1.577 response**; vì vậy không được làm thành phần bắt
  buộc của response identity.
- Chỉ quan sát một `survey_id` (`43000076179`) và ba mã:
  `-103` = 506, `100` = 1.761, `103` = 631.
- API không trả nhãn lựa chọn (`rating_label_raw = null` ở toàn bộ scan).

Mapping chuẩn cho survey đã quan sát:

| `rating_raw` | Bucket | Copy UI dự kiến |
|---:|---|---|
| `-103` | `negative` | `Rất tệ` — PO đối chiếu và chốt theo UI Freshdesk |
| `100` | `neutral` | `Bình thường` — PO đối chiếu và chốt theo UI Freshdesk |
| `103` | `positive` | `Rất hài lòng` — PO đối chiếu và chốt theo UI Freshdesk |

Ba nhãn trên là copy UI đã được PO chốt. API chỉ trả token số; không được ghi
hoặc ngụ ý rằng API trả ba chuỗi tiếng Việt này. Trong population 13 tuần đã
quét, cả 2.898 response và riêng 818 response của bot đã duyệt đều chỉ có đúng
ba token trên; đây là kết luận về tập đã quan sát, không phải cam kết vĩnh viễn
của Freshdesk.

Claim cũ “tenant có 3 survey, cả thang 2 và 5 mức” **không được credential hiện
tại chứng minh** và không còn là input thiết kế. Config chỉ khai báo survey/mã
đã quan sát; survey ID hoặc mã mới phải fail closed rồi chạy discovery lại.

Một ticket **có thể có nhiều response** ⇒ grain là **một dòng cho mỗi response**, không phải mỗi ticket.

---

## Giai đoạn 0 — DÒ DANH TÍNH AGENT (cổng chặn)

**Không viết một dòng code tính CSAT nào trước khi qua bước này.**

PO chỉ yêu cầu survey của CS-agent “Admin CS ZaloPay”. Không biết chắc ID của
account này thì human response có thể lẫn vào số AI — sai yên lặng.

**Bước 0A — probe contract trước, chưa viết CLI production:**

1. Trên một mẫu nhỏ ticket đã biết, probe read-only ba surface:
   `GET /api/v2/tickets/{id}`, cùng endpoint với `include=stats` nếu tenant hỗ
   trợ, và `GET /api/v2/tickets/{id}/conversations`.
2. Ghi **chỉ schema đã redact** vào báo cáo discovery: tên field, type,
   nullability và quan hệ ID; không ghi body, comment, email, tên khách hay raw
   response. Tạo mock fixture tổng hợp từ schema đó, không copy payload thật.
3. Chứng minh field nào đại diện cho **agent được gán**, field nào đại diện cho
   **agent thực sự gửi từng response**. `GET /tickets/{id}` hiện **không được giả
   định** là trả danh sách agent đã trả lời.
4. Kết quả: `satisfaction_ratings[*].agent_id` là responder attribution của
   rating theo Freshdesk, không phải danh sách tác giả từng reply. `null` là
   chưa có attribution; **không có nghĩa human**.
5. Kết quả identity: dùng `satisfaction_ratings[].id`. Cache lưu `response_key`
   là SHA-256 canonical của source ID; không lưu raw source ID hoặc `agent_id`.
   Natural key `(ticket_id, survey_id, agent_id, created_at)` bị cấm vì
   `agent_id` null ở 1.577 response.

**Bước 0B — chỉ sau 0A mới viết CLI read-only
`weekly-cs-report discover-agents --weeks 13`:**

1. Gọi `GET /api/v2/ticket_fields` đúng một lần và chỉ đọc
   `default_agent.choices`. Không đọc conversation để suy attribution CSAT;
   nguồn duy nhất để include một response vẫn là
   `satisfaction_ratings[].agent_id`.
2. Candidate hiện được resolve từ `GET /api/v2/ticket_fields` →
   `default_agent.choices`: đúng một tên exact “Admin CS ZaloPay”. Artifact riêng
   tư là `artifacts/freshdesk_discovery/agent_identity_candidate.json`, mode
   `0600`. CLI phải chứng minh match active là duy nhất; 0 hoặc >1 match thì
   fail closed.
3. Chạy lượt đếm toàn bộ response theo ba nhóm: `known_bot`, `other_agent`,
   `null`. Output chỉ aggregate; không log/persist agent ID theo từng response.
4. Chỉ thị PO 2026-08-02 duyệt exact display-name cohort. Sau khi bước 2 và 3
   đạt, CLI chép ID đã resolve vào config bằng atomic write mode `0600`; không
   in ID ra stdout/stderr/chat.
5. Nếu sau này có thêm tên bot khác, response của ID đó tiếp tục bị loại cho tới
   khi discovery + PO approval cập nhật config.

Kết quả chốt vào `config/freshdesk_agents.v1.json`:

```json
{
  "schema_version": 1,
  "approved_by": "PO",
  "approved_at": "YYYY-MM-DD",
  "bot_agent_ids": [12345678],
  "survey_scales": {
    "43000076179": {"positive": [103], "neutral": [100], "negative": [-103]}
  },
  "notes": "Chi tinh response gan truc tiep cho Admin CS ZaloPay; ID/survey moi phai discovery va duyet lai"
}
```

`survey_scales` trên là mapping explicit của đúng các token đã quan sát trong
tenant. Không có `rating_label_raw` từ API. Exact copy tiếng Việt được kiểm
riêng trên UI và không tham gia phép tính. Không gọi mapping là label do API
trả về; survey/token mới luôn cần discovery lại.

**Hai mức fail-closed, không được nhập nhằng:**

- Thiếu/sai config, identity resolve không duy nhất, hoặc gặp
  `survey_id`/rating token chưa map ⇒ **không publish cache mới**, giữ nguyên
  last-good cache và trả lỗi sanitized.
- Response có `agent_id` khác bot ID hoặc null ⇒ chỉ response đó không vào CSAT;
  job vẫn hoàn tất, tăng đúng aggregate loại trừ và giữ các response bot hợp lệ.

**Tên agent không bao giờ vào payload.** File config chứa `agent_id` số; tên hiển thị chỉ để PO đọc lúc duyệt, không serialize ra browser.

Artifact discovery có agent ID/tên nên là dữ liệu vận hành riêng tư: ghi dưới
`artifacts/` đã gitignore, thư mục `0700`, file `0600`, không log raw response.
Nếu API shape thực tế khác các giả định trên, cập nhật spec/fixture và xin PO
duyệt trước Batch 1; không tự map field gần giống.

---

## Giai đoạn 1 — Job rời + cache

**Quyết định đã chốt:** dashboard **không gọi Freshdesk** lúc người dùng mở trang. Một CLI riêng fetch trước, ghi cache, dashboard đọc cache.

Lý do: 6.663 ticket × 1 request. Refresh Langfuse hiện 92 giây; nhét Freshdesk vào luồng đó thành hàng chục phút, và một lần Freshdesk chậm là hỏng cả dashboard đang chạy tốt.

**1.0. Credential và import boundary:**

- Dùng đúng hai biến `FRESHDESK_BASE_URL` và `FRESHDESK_API_KEY`, chỉ đọc khi
  dispatch vào `discover-agents` hoặc `fetch-csat`. Không nhận secret qua argv.
- `FRESHDESK_BASE_URL` phải đúng origin đã duyệt
  `https://vngzalopay.freshdesk.com`, không port/path/query/userinfo; mọi request
  resolve dưới origin đó, không follow redirect sang origin khác. Origin HTTPS
  khác cũng phải fail closed trước khi gắn Basic Auth.
- Client CSAT nằm trong module riêng và không được import từ `web.py`,
  `dashboard_cache.py`, report pipeline hay `verify-dimensions`. Serving,
  dry-run và report Langfuse phải khởi động/chạy khi hai biến này vắng.
- Không log header Authorization, URL có credential, raw response hay exception
  body. Error public chỉ nêu loại lỗi/status đã sanitize.
- Sửa `test_reporting_package_has_no_retired_freshdesk_backfill_surface`: tiếp
  tục cấm toàn bộ Freshdesk backfill/applicability cũ, nhưng thay cấm chuỗi
  credential toàn package bằng allowlist import/caller cụ thể cho hai CLI CSAT.
  Test phải chứng minh serving/report/P0 không đọc credential.

**1.1. CLI mới:** `weekly-cs-report fetch-csat --weeks 13 [--since-week YYYY-MM-DD]`

**1.2. Chiến lược tăng dần — điểm mấu chốt về chi phí:**

| Loại tuần | Hành vi |
|---|---|
| Tuần đã đóng, đã fetch | **Bỏ qua hoàn toàn.** Survey không đổi ngược quá khứ |
| Tuần đang chạy | Fetch lại toàn bộ ticket của tuần đó; không hard-code số lượng |
| Tuần đóng chưa fetch | Fetch một lần rồi đóng băng |

Lần chạy đầu backfill 13 tuần; từ lần sau chỉ fetch population tuần đang chạy
và tuần đóng còn trong late-response window. Số request lấy từ dữ liệu hiện
tại, không dùng mốc 935 làm hằng số.

**Ngoại lệ:** khách có thể trả lời survey muộn. Cho phép fetch lại tuần đã đóng trong **14 ngày** kể từ ngày kết thúc tuần, sau đó mới đóng băng.

**1.3. Rate limit — tái dùng pattern đã có.**

`mcp/freshdesk-ticket/src/freshdesk_mcp/client.py` đã xử lý sẵn: Basic auth (dòng 68, 82), `429` + `Retry-After` với retry (dòng 112-125, 217-236), phân trang (dòng 138), fallback ticket archived (dòng 155-162).

**Chép pattern, không import** — đó là repo riêng, package này không được phụ thuộc vào nó.

Bắt buộc:
- Tôn trọng `Retry-After`, không tự đặt sleep cố định
- Giới hạn đồng thời cấu hình được, **mặc định 2**
- Checkpoint sau mỗi tuần: đứt giữa chừng thì chạy lại không mất phần đã xong
- Chạy quá `--max-duration` (mặc định 30 phút) thì **dừng sạch**, ghi tiến độ

**1.4. Cache trên đĩa** — `runtime/csat_cache.json`, mode `600`, gitignore.

`web._validated_runtime_directory()` hiện chỉ cho
`dashboard_snapshot.json` và temp snapshot. Batch 1 phải mở allowlist **đúng một
tên** `csat_cache.json`, vẫn yêu cầu regular file, owner hiện tại và mode
`0600`; mọi tên/dir/symlink khác tiếp tục fail closed. Thêm test startup với
cache hợp lệ và test từ chối symlink/permissive/unknown file. Nếu thiếu cache,
dashboard vẫn chạy Langfuse-only; không tạo cache rỗng trong serving process.

```json
{
  "schema_version": 1,
  "fetched_weeks": {"2026-07-20": "2026-07-28T03:00:00Z"},
  "fetch_stats": {
    "all_response_count": 84,
    "included_bot_response_count": 31,
    "excluded_other_agent_response_count": 8,
    "excluded_null_agent_response_count": 45
  },
  "responses": [
    {
      "response_key": "sha256:3f4c...",
      "ticket_id": "1234567",
      "survey_id": 43000076179,
      "responded_at": "2026-07-21T04:15:00Z",
      "rating_raw": 103,
      "satisfaction_bucket": "positive",
      "comment_present": true
    }
  ]
}
```

- `response_key` là hash của source `satisfaction_ratings[].id`; source ID gốc
  không vào cache.
- `responses` **chỉ chứa** row có `agent_id == bot_agent_ids[approved]`.
- Response agent khác/null chỉ tăng `fetch_stats`, không có row cache và không
  bao giờ vào payload/browser.
- `rating_raw` giữ nguyên mã API. Không có field `rating_label_raw` vì API tenant
  không trả nhãn.
- `satisfaction_bucket` ∈ `{positive, neutral, negative}` — quy về theo `survey_id`, cho phép so giữa các thang khác nhau
- Không có `answered_by_bot`: mọi row trong `responses` đã là bot-attributed theo
  contract. Field boolean hằng `true` chỉ tạo cảm giác có kiểm soát mà không thêm
  thông tin.
- Batch 1–4 **không lưu bất kỳ comment text nào**, kể cả bản redact; chỉ có
  `comment_present`. Giai đoạn 3/Batch 5 mới được thêm `comment_redacted` sau
  khi toàn bộ privacy gate chạy.

---

## Giai đoạn 2 — Chỉ số CSAT lên dashboard

**2.1. Payload hiện hành v11** — thêm vào mỗi view:

```json
"csat": {
  "source": "freshdesk",
  "fetched_at": "2026-07-28T03:00:00Z",
  "by_week": {
    "2026-07-20": {
      "response_count": 31,
      "ticket_count": 29,
      "positive": 23,
      "neutral": 4,
      "negative": 2,
      "by_outcome": {},
      "by_dimension": {"skill": [], "issue_category": []},
      "feedback_entries": []
    }
  }
}
```

`csat` là key bắt buộc trong mỗi view sau storage migration, giá trị là object
trên hoặc `null`. Cache vắng/không đọc được ⇒ `null` và dashboard Langfuse vẫn
hoạt động; cache stale vẫn giữ object cùng `fetched_at` để UI cảnh báo. Batch
payload phải khóa exact-key Python, Zod `.strict()`, parity fixture, old-version
rejection và missing-cache behavior trong cùng commit với version bump.

**2.2. Quy tắc metric — chống đúng những cách sai thường gặp:**

1. **Không trả lời survey ≠ Bình thường.** Chỉ tính ticket có response thật.
   Mẫu số phần trăm là `ticket_count`, mỗi Ticket ID một latest response; không
   phải tổng ticket và không phải `response_count`.
2. **Không tính response rate trên tổng ticket.** Chưa có denominator Freshdesk
   đã chứng minh cho “ticket được Admin CS ZaloPay trả lời”, nên không bịa tỷ lệ
   response bằng tổng ticket hoặc AI First Langfuse.
3. Luôn hiện `ticket_count`; chỉ hiện `response_count` làm thông tin hỗ trợ khi
   hai số khác nhau.
4. **Ngưỡng tối thiểu**: total dùng `ticket_count < 20`; mỗi grouping row dùng
   `row.ticket_count < 20`. Dưới ngưỡng chỉ hiện số đếm thô, không hiện phần trăm.
5. Không có metric/hàng human CS trong payload hoặc UI.

**2.3. Hiển thị** — mục mới sau "So sánh theo thuộc tính ticket":

```
Khách hài lòng tới đâu

Admin CS ZaloPay     31 phản hồi · 74% hài lòng · 13% không hài lòng

Chỉ survey của Admin CS ZaloPay · Freshdesk cập nhật 03:00 28/07 · Các phần khác: Langfuse.
```

Dòng nguồn gọn phía trên **bắt buộc**: đây là số duy nhất trên trang không đến
từ Langfuse. Nếu cache cũ, nối `· Chưa cập nhật hôm nay.` vào cùng đoạn thay vì
tạo thêm một dòng. Không dán nhãn là lặp lại đúng lỗi lệch scope của vòng 1.

`fetched_at` không thuộc ngày hiện tại theo Asia/Ho_Chi_Minh ⇒ cảnh báo dữ liệu
Freshdesk chưa được cập nhật hôm nay, không ẩn số và không giả timestamp mới.

---

## Giai đoạn 3 — ⚠️ Comment khách (DEVIATION cần duyệt riêng)

> **PO ĐÃ DUYỆT 2026-08-01** — trả lời nguyên văn: *"Đã ký"*, cho câu hỏi
> có sẵn nội dung rủi ro (redact tiếng Việt không đạt 100%, mỗi lần lọt là sự
> cố dữ liệu thật trên trang nhiều người xem).
> Giai đoạn 3 được phép thực hiện. **Sáu điều kiện bên dưới là bắt buộc, không
> phải khuyến nghị** — chúng chính là thứ được duyệt kèm. Bỏ bất kỳ điều kiện
> nào thì chữ ký không còn hiệu lực.
> Việc còn lại của PO: chép nguyên đoạn này vào mục privacy contract của
> `PRODUCT.md` để chữ ký nằm cùng chỗ với ranh giới PII, không nằm rải trong
> lịch sử chat.

**Phần này phá ranh giới PII hiện hành. Tách riêng để gỡ được mà không đụng CSAT.**

`CLAUDE.md` "Ranh giới PII trên browser" ghi: được phép **Ticket ID**; **không được** tên/email, **nội dung hội thoại**, raw payload.

Comment survey là **văn bản khách tự viết** — cùng loại với nội dung hội thoại. PO chọn hiện bản đã redact.

**Vì sao rủi ro thật, không phải lo xa:** redact tiếng Việt không đạt 100%. Tên người Việt không bắt buộc viết hoa; số tài khoản viết cách quãng; số điện thoại viết bằng chữ (*"không tám tám..."*); địa chỉ lẫn trong câu kể. Regex bắt được phần lớn, không bắt được tất cả. Mỗi lần lọt là sự cố dữ liệu thật, trên trang nhiều người xem.

**Điều kiện bắt buộc nếu làm:**

1. **PO duyệt bằng văn bản** — ghi vào `PRODUCT.md` mục privacy contract, nêu rõ đây là deviation có chủ ý và ai chịu trách nhiệm
2. **Redact hai lớp, cả hai chạy lúc fetch, không chạy lúc render**:
   - Lớp 1 — mẫu: số điện thoại (mọi định dạng, kể cả cách quãng), email, URL, số ≥ 6 chữ số, ID giao dịch
   - Lớp 2 — họ tên: tái dùng `_VIETNAMESE_FAMILY_NAMES` + `_VIETNAMESE_NAME_MIDDLES` đã có trong `dashboard_schema.py:47-50`
3. **Comment gốc không bao giờ chạm đĩa.** Redact trong bộ nhớ, chỉ ghi bản đã redact — cùng nguyên tắc "raw trace không serialize" đang áp cho Langfuse
4. **Mặc định ẩn trên UI.** Hiện `12 phản hồi có kèm comment`, bấm mới mở
5. **Cắt 200 ký tự** — comment dài là chỗ PII hay nấp
6. **Chạy qua bộ kiểm PII hiện có** trước khi vào payload; dính mẫu nào ⇒ thay bằng `[đã ẩn]`, không cố sửa

**Nếu PO không duyệt được bằng văn bản:** bỏ Giai đoạn 3, giữ `comment_present` dạng đếm. Giai đoạn 1–2 chạy độc lập, không phụ thuộc.

**Shape private cache đã duyệt:** cache schema `1 → 2` thêm dưới
mỗi response đúng một field `comment_redacted: string | null`. Đồng thời bump
dashboard storage version; browser v11 trở đi (hiện tại v13) chiếu thành:

```json
"feedback_entries": [
  {
    "ticket_id": "1234567",
    "responded_at": "2026-07-21T04:15:00Z",
    "satisfaction_bucket": "positive",
    "outcome": "ai_end_to_end",
    "skill": "interbank-fund-transfer",
    "issue_category": "Chuyển tiền",
    "text": "Cảm ơn, xử lý nhanh",
    "response_number": 1,
    "response_total": 1,
    "is_latest_for_ticket": true
  }
]
```

Không có `answered_by` vì mọi nội dung trong section này đã thuộc response bot
được duyệt. Nội dung phản hồi không được đưa vào Copy TSV, CSV, clipboard, log
hoặc accessible name khi disclosure còn đóng.

**Revision 2026-08-02:** dashboard storage bump `9 → 10` trong cùng batch thêm
`comments[].responded_at` (shape lịch sử, được v11 thay bằng
`feedback_entries`). UI nội dung phản hồi mặc định sort mới nhất, cho phép sort
mới/cũ, lọc theo tuần và theo ba mức hài lòng; mỗi Ticket ID mở đúng Freshdesk
ticket. Bộ redact phải có regression test giữ nguyên cụm nghiệp vụ `xử lý`
(`xử lý lâu`, `xử lý không tốt`, `CS xử lý nhanh`), `lý do` và `hồ sơ` thay vì
hiểu nhầm từ nghiệp vụ là họ người. URL cấm gồm URL có protocol, domain trần
ASCII/Unicode, IPv4 và IPv6 kèm path/query; cùng một matcher phải chạy khi
redact trước khi ghi cache và khi validate trước payload. Dòng tuần hiện tại
trong bảng báo cáo vẫn được highlight kể cả khi cohort T2–T6 đã `complete` vào
cuối tuần. Probe discovery xử lý theo batch nhỏ và checkpoint sau từng batch để
giới hạn thời gian không làm lặp lại cả tuần.

**Revision 2026-08-02 — phân trang nội dung phản hồi:** không render toàn bộ nội dung của
scope cùng lúc. Filter tuần/mức hài lòng và sort thời gian chạy trên toàn bộ
tập kết quả trước, sau đó UI chỉ render **10 item/trang**. Đổi bất kỳ
filter/sort nào phải về trang 1. Từ 11 item trở lên, desktop có Trang
trước/sau và cửa sổ số trang tối đa 7 vị trí; mobile dùng `Trang x / y` cùng
Trang trước/sau. Không dùng infinite scroll. Từ 10 item trở xuống không
hiện phân trang. Dòng trạng thái phải nói rõ khoảng đang xem, ví dụ
`Hiển thị 11–20 / 117 nội dung phản hồi`, và được thông báo bằng `aria-live` mà không
cướp focus khỏi nút phân trang.

API cần text để render nhưng chỉ nhận bản đã qua đủ sáu gate; comment gốc không
có field tương ứng trong bất kỳ schema nào.

---

## Giai đoạn 4 — Đối chiếu outcome (đã implement v12)

**Gate hoàn tất 2026-08-03:** discovery từ đúng
`ticket_fields.default_agent.choices` đã loại bot ID được duyệt và ghi 55
candidate vào `artifacts/freshdesk_discovery/human_agent_candidates.v1.json`
(gitignored, mode `0600`). Materializer bảo thủ đã gán 45 candidate là `human`
và 10 là `exclude`, đặt `approved_by=PO`, `approved_at=2026-08-03`, bind config
bằng source hash và giữ toàn bộ tên/ID ngoài chat, commit, payload và log.

Trả lời: *"Langfuse ghi 'AI xử lý trọn' nhưng thực tế có CS người trả lời sau"* xảy ra bao nhiêu.

Phase này không phải CSAT human và không ảnh hưởng cohort survey bot-only.
Không gọi mọi `user_id != bot_id` là human: chỉ ID trong allowlist đã bind mới
được tính; automation, requester và account bị loại không thể trở thành human
qua display name.

**4.1. Lằn ranh cứng — đọc được, xuất thì không.**

PO cho phép đọc conversation. Contract live cho thấy không cần body: chỉ đọc
metadata `user_id`, `incoming`, `private`, `source`, `created_at`. Cho phép với
ràng buộc **không thương lượng**:

| Được | Không được |
|---|---|
| Gọi `GET /api/v2/tickets/{id}/conversations` trong CLI | Đọc/ghi `body`, `body_text`, attachment hoặc quoted text |
| Giữ metadata trong bộ nhớ, tính ra kết luận | Đưa metadata cấp message vào payload |
| Xuất boolean `human_replied_after_ai` | Xuất tên agent, trích đoạn, dấu thời gian cấp tin nhắn |

Đây **cùng invariant** đang áp cho Langfuse: *"Raw trace/observation không bao giờ serialize ra đĩa"*. Mở rộng sang Freshdesk, không nới ra.

**4.2. Cách nhẹ đã đo và không đủ.** Mẫu 50 ticket cho thấy
`GET /tickets/{id}?include=stats` có `stats.agent_responded_at` nhưng không có
danh sách tác giả/chuỗi reply. Dùng endpoint conversations, nhưng tuyệt đối
không truy cập body.

Một agent reply hợp lệ phải đồng thời:

1. `incoming == false`;
2. `private != true`;
3. `source != 6` — Freshdesk định nghĩa `6` là survey feedback của khách, không
   phải agent reply;
4. `user_id` nằm trong `human_agent_ids` của identity config được duyệt riêng
   cho reconciliation; chỉ "khác bot ID" là chưa đủ.

Không resolve được author ⇒ kết quả ticket là `null`, không phải `false`.

**4.3. Cache + payload contract:**

Khi gate author-resolution đã đạt, Batch 6 đọc cache/storage version hiện tại
rồi bump đúng một lần và lưu trên mỗi ticket thuộc population đối chiếu đúng
một derived field `human_replied_after_ai: boolean | null`. Không lưu
conversation text, message ID, agent ID/tên hay timestamp cấp message. `null`
nghĩa là chưa kiểm/không đủ bằng chứng, không được tính như `false`.

Trong dashboard snapshot, thêm `outcome_reconciliation` **làm sibling của
`csat` trong mỗi view**, không top-level và không lồng dưới từng ticket:

```json
"outcome_reconciliation": {
  "source": "freshdesk",
  "fetched_at": "2026-08-03T03:00:00Z",
  "by_week": {
    "2026-07-20": {
      "langfuse_ai_end_to_end": 727,
      "checked_ticket_count": 680,
      "human_replied_after_ai": 43,
      "unresolved_ticket_count": 12,
      "mismatch_rate": 0.06323529411764706
    }
  }
}
```

Field là object trên hoặc `null`; cache vắng/chưa đối chiếu ⇒ `null`. `by_week`
dùng cùng cohort definition với view chứa nó. Batch 6 đọc storage version hiện
tại rồi bump thêm một lần; cập nhật exact-key Python, Zod `.strict()`, fixture
parity, old-version rejection và missing-cache behavior trong cùng commit.

**4.4. Không sửa số Langfuse và không render summary đối chiếu.** Mọi báo cáo
đã gửi đi đều tính theo Langfuse. Đổi công thức làm số lịch sử mất khả năng so
sánh. Kết quả đối chiếu chỉ giữ trong cache/payload tương thích và không xuất
hiện thành khối nội dung trên dashboard; sửa công thức là quyết định riêng,
spec riêng.

**4.5. Nếu mismatch > 10%** — dừng, báo PO. Lệch mức đó nghĩa là định nghĩa outcome sai, không phải chỉnh sửa nhỏ.

---

## Thứ tự batch

| # | Nội dung | Chặn bởi | Test RED đầu tiên |
|---|---|---|---|
| **0** | Probe API shape/response identity; exact-name resolver qua `ticket_fields`; attribution scan toàn bộ; atomic config | — | `test_discover_agents_requires_exactly_one_active_name_match`; contract đo collision bằng 0 |
| **1** | Client Freshdesk + credential isolation + rate limit + cache + runtime allowlist | Batch 0 | `test_csat_fetch_honours_retry_after` |
| **2** | Fetch tăng dần + đóng băng tuần + bot-only attribution | Batch 1 | `test_fetch_includes_only_approved_bot_agent_id`; `test_closed_week_is_not_refetched_after_fourteen_days` |
| **3** | Payload CSAT nullable + bump version + exact Python/Zod parity | Batch 2 | `test_csat_payload_never_contains_agent_id` **và** `test_csat_schema_is_strict_and_versioned` |
| **4** | Mục CSAT trên frontend | Batch 3 | `test_csat_hides_percentage_below_twenty_responses` |
| **5** | Comment redact + cache schema 2 + bump storage version lần hai | Batch 4 + privacy contract trong `PRODUCT.md` | `test_redaction_strips_spaced_phone_numbers` |
| **6 (phase riêng)** | **Đã implement v12:** đối chiếu outcome + cache metadata-only | discovery + PO duyệt `human_agent_ids`; **không phụ thuộc Batch 5** | `test_reconciliation_never_serializes_conversation_text` **và** `test_reconciliation_rejects_unapproved_non_bot_authors` |

**Batch 0 là cổng chặn.** Không có `config/freshdesk_agents.v1.json` đã duyệt thì batch 1 không bắt đầu.

**Batch 3 bắt buộc:** đọc `_STORAGE_VERSION` hiện tại rồi bump đúng một lần,
cập nhật exact-key Python và Zod **cùng commit**; test snapshot version cũ bị từ
chối và cache vắng tạo `csat: null`.

**Batch 5 bắt buộc bump lần hai** vì persisted/browser shape có thêm comments.
Không khai báo optional field từ Batch 3 rồi âm thầm bắt đầu populate ở Batch 5;
version phải phản ánh đúng thời điểm dữ liệu nhạy cảm xuất hiện.

**Batch 6 không nằm trên critical path CSAT bot-only.** Nó chỉ bắt đầu sau gate
author-resolution riêng và đọc version thực tế lúc đó; không được giả định mọi
non-bot ID là human và không được ép phụ thuộc comment Batch 5.

---

## Kiểm chứng

```bash
task_basetemp="$(mktemp -d)"; chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"

# Key cấm — phải là 0; chạy trên server do chính lượt kiểm chứng start
curl -s http://127.0.0.1:8765/api/dashboard | grep -cE 'UserID|TransID|traceId|sessionId|agent_id|agent_name|raw_comment|"feedback"|"body"|"body_text"|"attachments"|"quoted_text"'

# Cache không có agent_id hoặc field comment gốc. `comment_present` được phép;
# `comment_redacted` chỉ được phép từ Batch 5/cache schema 2.
grep -cE '"agent_id"|"agent_name"|"comment"[[:space:]]*:|"feedback"|"body"|"body_text"|"attachments"|"quoted_text"' runtime/csat_cache.json

stat -f "%Sp %N" runtime runtime/csat_cache.json   # drwx------ / -rw-------
```

**Kiểm bắt buộc trước khi giao:**
1. Ngắt mạng giữa lúc fetch ⇒ checkpoint còn nguyên, chạy lại tiếp được
2. Freshdesk trả `429` liên tục ⇒ CLI dừng sạch, cache cũ vẫn dùng được
3. Thiếu `config/freshdesk_agents.v1.json` ⇒ **từ chối chạy**, không mặc định
4. Ticket có 2 response ⇒ đếm 2 dòng, không đè lên nhau
5. Ba token đã quan sát `-103`, `100`, `103` map đúng theo config; survey ID
   hoặc token mới ⇒ không publish cache mới và giữ last-good
6. Comment chứa `"sdt cua e la 0 9 0 1 2 3 4 5 6 7"` ⇒ redact được (test này **phải** có)
7. Cache/API/DOM/export/clipboard/log không chứa comment gốc, agent ID/tên,
   email, URL, số dài, ID giao dịch hoặc họ tên từ bộ fixture đối kháng
8. `runtime/csat_cache.json` hợp lệ không làm dashboard fail startup; symlink,
   mode khác `0600`, directory hoặc tên lạ vẫn bị từ chối
9. Thiếu cả hai biến Freshdesk ⇒ dashboard, report Langfuse và
   `verify-dimensions` vẫn chạy; chỉ hai lệnh CSAT fail với lỗi sanitized
10. Exact schema parity: `csat` nằm trong từng view, cache vắng là `null`, cache
    quá 48h render stale, snapshot version cũ bị từ chối
11. Fetch lại cùng source response ID không tạo dòng mới; hai response cùng
    ticket vẫn tách được; source ID thiếu/trùng phải fail closed
12. `agent_id == approved_bot_id` ⇒ include; `agent_id` khác/null ⇒ loại và tăng
    đúng aggregate exclusion, không có row cache/browser
13. Conversation `source = 6` không bao giờ được tính là agent/human reply
14. Payload/DOM/export không có hàng, series hoặc metric CSAT human; comment nếu
    bật chỉ đến từ response bot đã include
15. Scope có 117 comment chỉ render 10 item trên mỗi trang; trang cuối có 7,
    filter/sort reset về trang 1, `aria-current` đánh dấu đúng trang, và viewport
    390 px không phát sinh overflow ngang

---

## Điều phải nói thẳng

1. **Spec này đảo một quyết định user-mandated của chính PO 1 ngày trước.** Cách hoà giải ở §2 giữ nguyên tinh thần cũ: gate P0 vẫn chỉ Langfuse. Nhưng phải sửa spec cũ tường minh, không lách.

2. **Gate P0 đang FAIL.** Category 84,7% < 90%, TPE 79,2% < 85%, `go_live=BLOCKED`. Thêm nguồn thứ hai khi cổng toàn vẹn còn đỏ là chồng rủi ro. Cân nhắc sửa P0 trước.

3. **Bulk endpoint bị chặn vĩnh viễn — PO đã chốt không mở được.** Fetch tăng dần ở Giai đoạn 1 không phải giải pháp tạm; nó là kiến trúc chính thức. Phần đắt nhất của spec này (checkpoint, đóng băng tuần, giới hạn đồng thời) tồn tại vì lý do đó và không được cắt bớt.

4. **Giai đoạn 3 đã được PO ký duyệt**, kèm rủi ro đã nêu rõ. Sáu điều kiện ở Giai đoạn 3 là nội dung được duyệt, không phải gợi ý. Codex bỏ bớt điều kiện nào thì phải dừng và hỏi — chữ ký không phủ bản rút gọn.

5. **Đọc hội thoại được, xuất hội thoại thì không.** Ranh giới ở §4.1 là điều kiện để Giai đoạn 4 tồn tại. Codex vi phạm dòng nào trong bảng đó thì phải dừng.

6. **CSAT bot-only không đại diện cho toàn bộ khách hoặc toàn bộ ticket.** Mẫu
   số dashboard chỉ là `ticket_count` có response gắn trực tiếp cho ID bot đã
   duyệt, mỗi ticket lấy response mới nhất. Không dựng response rate trên tổng
   ticket; dưới 20 ticket chỉ hiện số đếm thô, không hiện phần trăm.

7. **Batch 0 không được bỏ qua.** Resolve sai agent bot thì CSAT của bot và
   người khác lẫn nhau, số vẫn trông hợp lý, và không ai phát hiện được. Đây là
   loại sai tệ nhất: sai một cách yên lặng.
