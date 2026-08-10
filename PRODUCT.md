# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- CS lead đọc dashboard hằng tuần để nắm KPI, phát hiện vấn đề và copy báo cáo.
- PO dùng xu hướng và segment để chọn Product Code hoặc Category cần ưu tiên
  cải thiện skill.
- Dev và CS agent dùng chẩn đoán chuyển CS, danh sách ticket có hơn 3 lượt xử lý
  và Ticket Explorer để điều tra ticket.

## Product Purpose

Biến dữ liệu Langfuse đã được phân loại thành một báo cáo vận hành CS gần thời
gian thực, giúp người đọc trả lời nhanh ba câu hỏi: AI xử lý được bao nhiêu,
điều gì đang hỏng, và số liệu có đáng tin hay không.

Source of truth về metric, schema, privacy và hành vi là
[`docs/SPEC-v2.md`](docs/SPEC-v2.md).

## Positioning

Đây là sổ điều hành tuần có thể truy ngược từ KPI tới tín hiệu chẩn đoán và
ticket đã được lọc riêng tư; observation overlap không được gọi là nguyên nhân
đã chứng minh. Đây không phải dashboard trình diễn hay hệ thống tạo nhận định
bằng LLM.

## Operating Context

- Được đọc theo nhịp hằng tuần, với dữ liệu near-live và TTL 5 phút.
- Bảng Báo cáo tuần, Copy TSV và CSV UTF-8 là deliverable quan trọng nhất.
- Service production phải nằm sau authenticated reverse proxy, VPN hoặc SSO.

## Capabilities and Constraints

- Giữ nguyên `GET /api/dashboard`, `GET /api/tickets` và `POST /api/refresh`.
- Giữ hai cohort `T2–T6` và `T2–CN`; `T2–T6` đứng bên trái và là mặc định khi
  mở dashboard. Giữ cross-filter và column visibility hiện có.
- Không bổ sung survey, data source, metric, LLM narrative, route hoặc auth mới,
  **ngoài ngoại lệ Freshdesk CSAT và outcome-reconciliation đã duyệt ngày
  2026-08-01 dưới đây**. Ngoại lệ này không được dùng để mở rộng sang metric
  hoặc nguồn thứ ba.
- Ticket ID là định danh điều tra được phép và luôn có trong bảng/CSV Ticket
  Explorer. Ô Ticket cung cấp hai điều hướng do người dùng chủ động bấm:
  Freshdesk ticket và Langfuse Tracing đã lọc theo Session ID tương ứng.
- Các link chỉ là UI affordance. CSV chỉ chứa Ticket ID thô; API, snapshot,
  local storage và CSV không thêm URL, icon hoặc accessible destination label.
- PII, raw trace, prompt/response và ID nội bộ Langfuse vẫn bị cấm. Ngoại lệ
  duy nhất là project routing ID cố định, không phải secret, được phép tồn tại
  trong frontend bundle và đúng href Langfuse đã duyệt; ngoại lệ này không cho
  phép thêm `traceId`, `observationId` hoặc giá trị Session ID khác. Filter
  `sessionId` của Tracing dùng chính Ticket ID đã được phép theo mapping sản
  phẩm hiện tại.
- Runtime có bốn trạng thái: loading, ready, refreshing và stale_error.

### Freshdesk CSAT và privacy deviation — PO duyệt 2026-08-01

PO đã trả lời bằng văn bản **“Đã ký”** cho việc hiển thị nội dung phản hồi
survey sau redaction, với đúng sáu điều kiện bắt buộc dưới đây. Đây là ngoại lệ
hẹp cho private field `comment_redacted` của CSAT; browser gọi dữ liệu đã duyệt
là **“nội dung phản hồi”**, không suy nó là lựa chọn có sẵn hay văn bản tự do.
Ngoại lệ không cho phép đưa nội dung hội thoại Freshdesk, phản hồi gốc, tên
agent hoặc identifier mới lên browser.

1. Redact hai lớp ngay lúc fetch: mẫu PII trước, họ tên Việt Nam sau.
2. Nội dung gốc chỉ tồn tại trong bộ nhớ và không bao giờ chạm đĩa, cache,
   snapshot, log hay payload.
3. UI mặc định chỉ hiện số nội dung phản hồi; người dùng phải chủ động mở mới thấy bản
   đã redact.
4. Mỗi nội dung đã redact bị cắt tối đa 200 ký tự.
5. Trước khi vào cache/payload, chạy privacy validator; còn khớp mẫu cấm thì
   thay toàn bộ bằng `[đã ẩn]`, không cố sửa từng phần.
6. Test bắt buộc bao phủ số điện thoại cách quãng, email, URL, chuỗi số dài,
   ID giao dịch và họ tên; kiểm cả cache, API, DOM, export/clipboard và log.

Freshdesk chỉ cung cấp CSAT và chỉ số đối chiếu outcome. Gate P0, AI First,
reopen, bốn outcome, TPE và segment vẫn chỉ tính từ Langfuse. Dashboard serving
không gọi Freshdesk theo request; một CLI riêng ghi cache riêng tư. Mọi số từ
Freshdesk phải ghi nguồn và thời điểm cập nhật trên màn hình. Freshdesk không
được âm thầm sửa hay thay thế số Langfuse.

CSAT chỉ gồm survey được Freshdesk gắn trực tiếp cho **Admin CS ZaloPay** — tài
khoản AI CS Agent đã duyệt; survey gắn cho human CS không nằm trong metric.
Dashboard v11 dùng grain ticket: `response_count` đếm mọi response bot được
duyệt trong cohort, `ticket_count` đếm Ticket ID khác nhau, còn ba mức hài lòng
và breakdown theo outcome/Skill/Category lấy đúng response mới nhất của mỗi
ticket theo `(responded_at, response_key)`. `responded_at` không đổi tuần cohort
của ticket. Các breakdown là phép nối quan sát giữa Freshdesk và dimension
Langfuse, không chứng minh dimension gây ra mức hài lòng.
Người đọc có thể chọn tuần hoặc `Tất cả tuần` ngay trong mục CSAT. Lựa chọn này
dùng chung scope với các phần phân tích và Ticket Explorer để vừa dễ tìm, vừa
không tạo hai con số mang cùng nhãn tuần nhưng khác mẫu số.

Dashboard v12 thêm đối chiếu độc lập cho ticket Langfuse ghi `AI xử lý trọn`:
chỉ public outgoing reply sau bot từ một agent ID trong private roster đã được
PO duyệt mới được tính là CS người trả lời sau. Requester/user không bao giờ
được tính dù tên trùng human CS; author chưa xác định giữ `null`. Job chỉ đọc
metadata hội thoại trong bộ nhớ và cache/payload chỉ giữ trạng thái dẫn xuất,
không giữ tên/ID agent, message ID, timestamp cấp message hay conversation text.
Mẫu số đối chiếu chỉ gồm ticket `AI xử lý trọn` có Ticket ID Freshdesk hợp lệ mà
job được phép fetch; nó không sửa hoặc thay thế tổng outcome Langfuse.

Dashboard v13 thêm thời gian mở ticket vào Ticket Explorer. Giá trị lấy từ
turn đầu tiên trong Langfuse, hiển thị theo giờ Việt Nam và sort được trên toàn
bộ tập kết quả. Filter tuần vẫn là control thời gian chính; không có filter
ngày giờ thứ hai chồng nghĩa.

Dashboard v14 thêm bảng **Lý do chuyển CS**. Mỗi ticket đã chuyển CS chỉ thuộc
một row, lấy từ blocked guardrail event trên đúng trace chuyển CS đầu tiên;
trace ID chỉ dùng trong bộ nhớ và không đi vào snapshot hoặc browser. Bảng đặt
wording dễ đọc trước, đồng thời giữ nguyên `rule`, observation source, stage và
skill đã qua validation để Dev đối chiếu. Hai đường `cs_escalation` từ
`skill_guardrail_checked · stage=output` và `output_guardrail` được giữ riêng.
Nếu trace chuyển CS đầu tiên không có event hợp lệ, ticket vào
`Chưa xác định được từ trace`; không suy lý do từ TPE hay trace khác.

Dashboard v15 thêm cùng enum **Lý do chuyển CS** vào Ticket Explorer và CSV,
không thêm rule/source/stage/skill cấp ticket. Bảng lý do tổng hợp sort được ở
cả sáu cột. Rule `max_replies_exceeded` hiển thị là
`Khách tiếp tục hỏi sau 3 phản hồi AI`: guardrail chạy ở input sau khi lịch sử
đã có 3 message assistant. Chỉ số `>3 lượt xử lý` là `turn_count > 3` trên số
trace của ticket; đây là hai định nghĩa độc lập.

Dashboard v18 thêm **Độ phủ xử lý từ Freshdesk**. Freshdesk là tập ticket gốc
theo tuần; mỗi ticket được đối chiếu với Ticket ID Langfuse và public agent
reply trong conversation. `Không thấy lần gọi CS-agent` chỉ có nghĩa là không
thấy Ticket ID Langfuse tương ứng và không thấy public reply của bot đã được
duyệt trên Freshdesk; đây không phải bằng chứng chắc chắn rằng trigger thất
bại. Trạng thái này luôn tách khỏi `Đã gọi nhưng không có phản hồi/chuyển CS`
(`invoked_no_result`), là ticket đã có trong Langfuse nhưng không có AI First
và không có chuyển CS.

Đối chiếu dùng contract Freshdesk: chỉ conversation `category=3`,
`private=false`, `incoming=false` mới là public agent reply; category 1 là
user, 2 là private note, 5 là system/automation và 7 là survey. Bot và human
được nhận diện bằng roster agent ID đã được PO duyệt, không bằng display name.
Conversation chỉ được đọc trong job ngoài serving process; browser/cache chỉ
giữ Ticket ID, thời gian mở, tuần, enum trạng thái và cờ human reply. Ticket
Freshdesk không có dữ liệu Langfuse không được thêm vào Ticket Explorer vì
không có outcome/segment để lọc; chúng có drill-down riêng, phân trang 10
ticket và link Freshdesk để điều tra. Inventory dùng `per_page=50` cố định và
checkpoint riêng theo trang; đối chiếu ticket cũng checkpoint theo tiến độ. Chỉ
tính ticket Freshdesk từ tuần bắt đầu `06/07/2026`; dữ liệu trước mốc này không
được đưa vào aggregate.

Refresh Langfuse có enrichment `partial` không được publish hoặc serve. Hệ
thống giữ snapshot hoàn chỉnh gần nhất; nếu chưa có snapshot hoàn chỉnh thì
dashboard ở trạng thái chưa sẵn sàng. Vì vậy `Chưa xác định được từ trace`
chỉ xuất hiện khi trace đã được đọc đầy đủ và thực sự không xác định được,
không phải do một lane enrichment bị lỗi hoặc timeout.

### Source-faithful TPE diagnostics

- `Step result` chỉ đến từ observation có tên chính xác
  `tool:get_transaction_processing_engine_data`, field
  `output.result.stepresult`, và luôn đi cùng `output.result.transstatus` của
  chính result đó.
- Không tách `meta["Step result"]`, không map sang `Case`, canonical status
  hoặc diễn giải ý nghĩa mã. Token thiếu hiển thị `Không có Step result`.
- Phân phối dùng grain `(transstatus, step_result)`. Bảng có đúng bốn cột:
  `Transstatus`, `Step result`, `Ticket`, `Tỷ trọng`.
- Không có cảnh báo “mã TPE chưa có trong taxonomy”. Dashboard nói thẳng số
  ticket chuyển CS thiếu Step result và mẫu số tương ứng.
- Bảng Lý do chuyển CS dùng partition v14: wording CS/PO đứng trước, còn giá trị
  rule và nguồn kỹ thuật đứng sau cho Dev; tổng số ticket luôn bằng mẫu số ticket
  chuyển CS.
- Bảng ticket có hơn 3 lượt xử lý chỉ hiện `Tổng`, `Đã chuyển CS`, `Chưa chuyển CS` và
  lối mở danh sách chưa chuyển. Không hiện số “rule fired” hay suy chênh lệch
  giữa hai telemetry thành nguyên nhân.
- Panel `escalation_guard_blocked` không hiển thị vì dễ bị đọc ngược nghĩa và
  không tạo hành động riêng; field vẫn được giữ trong projection tương thích.
- `outcome_reconciliation` vẫn được giữ trong cache/payload tương thích nhưng
  không render thành khối “Đối chiếu Freshdesk” trên dashboard; PO xác nhận các
  dòng coverage/phương pháp này không cần thiết ở màn hình chính.

## Implementation Policy

- Product contract không khóa frontend vào một framework, component library
  hoặc chart library vĩnh viễn.
- React/TypeScript/Vite, TanStack và Zod là lựa chọn implementation hiện tại
  được phản ánh trong `package.json`; thay đổi stack phải chứng minh giữ nguyên
  API, metric, privacy, rollback và các task chính của người dùng.
- Charting được chọn bằng bằng chứng: semantic output, keyboard/cross-filter,
  hiển thị đúng khoảng dữ liệu thiếu, CSP, maintainability và bundle budget.
  Implementation hiện tại dùng Visx modular bên trong semantic SVG; Visx hoặc
  native SVG đều không phải yêu cầu cố định và có thể thay khi kết quả đo của
  giải pháp khác tốt hơn.

## Brand Commitments

- Tên hiển thị luôn là `Zalopay`.
- Nguồn canonical của mọi logo, Z graphic, app icon và font Zalopay nằm tại
  `../docs/zalopay-guideline`.
- Project giữ một bản curated dưới
  `assets/brand/{logos,graphics,icons,fonts/source,fonts/web}` để build tự chứa;
  `assets/brand-provenance.json` pin nguồn, hash, derivation và quyền ship của
  từng file. Bản này chỉ được cập nhật từ nguồn canonical và phải qua kiểm tra
  provenance trước khi phát hành. File `.ai`, PDF và OTF source không được ship
  vào browser.
- Icon Langfuse phục vụ điều hướng là third-party asset, không phải Zalopay
  asset. Nó được exact-copy vào `assets/icons/`, có manifest provenance riêng
  và được bundle same-origin; không nhập vào `assets/brand-provenance.json`.
- Dùng logo chính thức, primary blue `#0033C9`, primary green `#00CF6A` và
  Aeonik Pro self-hosted.
- Chưa gọi bản build là official cho tới khi Design System/UXD phê duyệt.

## Evidence on Hand

- Brand guideline, vector logo và Aeonik Pro trong `../docs/zalopay-guideline`.
- Business/UI contract trong `docs/SPEC-v2.md`.
- Baseline UI và test evidence trong `docs/superpowers/reports/`.

## Product Principles

1. Báo cáo tuần trước, chẩn đoán sau.
2. Mỗi con số phải có phạm vi, so sánh, độ tươi và chú thích cần thiết.
3. Dữ liệu thiếu phải trông thiếu; không biến rỗng thành số 0.
4. Không hy sinh riêng tư hoặc sự thật để làm UI đẹp hơn.
5. “Official” là kết quả của bằng chứng và phê duyệt, không phải nhãn tự gắn.
6. **Đã chuyển CS** chỉ có nghĩa là phản hồi trong trace khớp chính xác một mẫu thông báo chuyển CS đã được duyệt; không xác nhận CS người đã phản hồi hoặc xử lý ticket.

## Accessibility & Inclusion

Frontend phải đạt WCAG 2.2 AA, dùng semantic HTML, hỗ trợ bàn phím, reflow,
reduced motion và không truyền thông tin chỉ bằng màu.
