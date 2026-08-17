# Đánh giá dashboard theo góc nhìn stakeholder — 2026-08-18

**Người đánh giá:** Claude, đóng vai C-level / Head of CS / CS staff khi dùng dashboard
**Đối tượng đánh giá:** `langfuse-weekly-cs-report` — bản SPA hiện hành trong `frontend/`, chạy local `--local --port 8765`, snapshot thật `generated_at=2026-08-12T05:41:13Z`
**Không đánh giá:** `static/legacy/index.html` (rollback, đã có bug log riêng trong `CLAUDE.md`, không lặp lại ở đây)
**Trạng thái tài liệu tại thời điểm đánh giá:** `DESIGN.md` tự nhận là "production candidate", **chưa official** — chưa có UXD/Brand Owner/Design System Owner ký duyệt. Đây là bản đánh giá độc lập đầu tiên từ bên ngoài mà project này nhận được (không có report review nào trước đó trong `docs/superpowers/reports/`, chỉ có 3 báo cáo tự chấm của người viết code).

---

## 0-bis. Đính chính sau vòng verify code (2026-08-18, cùng ngày)

Bản đầu của report này viết từ quan sát UI + tài liệu. Sau khi đọc thẳng source, ba chỗ cần đính chính — giữ nguyên bản gốc bên dưới để đối chiếu, nhưng **các mục dưới đây thắng khi mâu thuẫn**:

| Chỗ sai | Thực tế đọc từ source |
|---|---|
| "Transstatus chưa được đầu tư tầng dịch nghĩa" | **Sai.** Tầng dịch nghĩa **đã có**: `config/taxonomy.v2.json` → `tpe.mappings` có 28 mapping / 12 mã / **19 status enum** (`SUCCESSFUL`, `FAILED_NFC`, `FAILED_KYC`, `FAILED_OTP`, `SECURITY_BLOCK`, `RISK_BLOCK`, `POLICY_BLOCK`...), được `categories.py` load + validate chặt. Vấn đề thật: nó **bị ngắt giữa đường** — `categories.py:425` luôn set `tpe_status_canonical=None`, và `dashboard_schema.py:1250` chỉ emit `transstatus/step_result/count` nên status không bao giờ tới browser. `taxonomy.tpe.unmapped_policy = "passthrough"` là cơ chế làm mã thô rò ra UI. |
| "19 mã số trong dropdown" | **Sai đếm.** 20 mã (19 mã âm + mã `1`). |
| Item #2 "cần xây tín hiệu độ tin cậy" | **Đã có sẵn.** `frontend/src/lib/data-quality-score.ts` có `calculateDataQualityScore` (trọng số governed 40/20/20/10/10 trên `coverage.issue_category`/`tpe`/`skill` + `gate_status` + freshness), **đã có test** (`frontend/test/data-quality-score.test.ts`), và **đang được gọi** tại `AppShell.tsx:127` — nhưng chỉ `ageMs` được dùng, còn `score`/`tone` tính xong bị vứt. Đây là di chứng khi xoá mục Chất lượng dữ liệu ở commit `3619c42`. |

Bổ sung số liệu mới, đo trên snapshot thật tuần 10/08:

- Mapping phủ **10/20** mã đang chạy prod. Mã `-217` trong ví dụ headline nằm đúng nhóm **không** được phủ.
- Resolve theo cặp `(transstatus, step_result)`: **71,9%** tín hiệu (23/32) ra được status; **28,1%** (9/32) không resolve được.
- Resolution là **deterministic**: không mã nào vừa có mapping `steps: []` vừa có mapping step-specific, và không cặp `(code, step)` nào cho hai status khác nhau.
- Tín hiệu lớn nhất resolve ra `SUCCESSFUL` (19/32) — giao dịch **thành công** nhưng ticket vẫn chuyển CS. Đây là insight nghiệp vụ thật, không phải nhiễu.

Contrast ở §3.4 đã tính lại bằng công thức WCAG, **đúng như đã ghi**: muted `#9fadbf`/`#0d1117` = 8,29:1; brand-ink tối `#6685df` = 5,39:1; `#0033c9` gốc = 2,09:1.

### Đính chính đợt 2 — sau khi đọc từng control một

| Chỗ sai | Thực tế |
|---|---|
| §2.3 + §3.3.3 + item #5: "33+ trường form không có nhãn, screen reader nghe toàn *checkbox* vô danh" | **Over-claim, phải hạ cấp.** Đếm lại trên source (không tính bundle build): `frontend/src` có **23** control, trong đó **12** thiếu `id`/`name`/`aria-label` — nhưng **cả 12 đều được bọc trong `<label>`**, nên đã có accessible name qua implicit label association. Screen reader đọc đúng. Vấn đề thật chỉ còn: thiếu `id` (ảnh hưởng `htmlFor`, độ ổn định `getByLabel` trong Playwright, autofill) và **thiếu nhất quán** — riêng `TicketExplorer.tsx` có 11/15 control đã đặt `id` (`cohortWeekInput`, `tpeCodeInput`...) còn 4 cái cùng hình dạng JSX thì không. Mức độ: **Nhẹ**, không phải Trung bình/Nghiêm trọng. |
| Item #6: "chưa có cảnh báo mẫu nhỏ" | **Đã có một phần.** `CsatBreakdownTable.tsx:20` có `PERCENTAGE_SAMPLE_MINIMUM = 20` + badge "Mẫu nhỏ" (`:173-178`) + đã tụt về hiển thị count khi dưới ngưỡng (`:57-61`). Thiếu ở `TransferDiagnostics.tsx` và bảng segment trong `BelowFold.tsx`. Ngưỡng sẵn có là **20**, không phải 10 như tôi đề xuất — nên tái dùng hằng số này thay vì tạo ngưỡng thứ hai. |
| Item #9: "đổi `--critical` có rủi ro lan rộng" | **Gần như không rủi ro.** `--critical` (token viền) có **0 consumer sống** — chỉ dùng trong class chết `.criticalAction` (`below-fold.module.css:29-30`, không nơi nào tham chiếu). `--critical-text` có đúng **2 consumer sống**: giá trị KPI tone critical (`dashboard.module.css:615-617`) và badge/cột "Rất tệ" của CSAT (`satisfaction-badge.module.css:26-28`). |
| Item #8: "có lời gọi `eval()` bị CSP chặn" | **Chưa xác nhận được nguồn.** Grep bundle build: `eval(` = 0, `new Function` = 0. Vi phạm CSP Chrome báo là thật (`index-BzicdxLb.js:8` cột 78772) nhưng không khớp literal nào — có thể là indirect eval trong dependency hoặc dựng chuỗi lúc runtime. Hạ từ "code chết" xuống **cần điều tra**, chưa kết luận. |

Hai orphan khác phát hiện thêm, đều đã có test và **không được render ở đâu**: `selectWeakestCoverage()` (`selectors.ts:218-238`) và `formatDataAge()` (`data-quality-score.ts:66-82`). Cùng với `score`/`tone` bị vứt ở `AppShell.tsx:127`, đây là vật liệu sẵn có cho item #2 và #10 — không cần xây mới.

Kế hoạch triển khai: `docs/superpowers/plans/2026-08-18-dashboard-critique-remediation.md`.

---

## 0. Tóm tắt điều hành

Nền tảng kỹ thuật của dashboard này **tốt hơn đáng kể** so với ấn tượng ban đầu — deterministic, PII-safe, có gate P0, có changelog spec rõ ràng, màu sắc đã được tính contrast tử tế. Nhưng có **một lỗi xuyên suốt đủ nghiêm trọng để phủ bóng lên toàn bộ uy tín dữ liệu**: câu insight tự sinh và cột "Transstatus" đang phơi bày mã lỗi nội bộ thẳng ra màn hình đọc của C-level/Head of CS mà không dịch nghĩa — xem mục 4.1.1. Ngoài ra, gate chất lượng dữ liệu P0 mà chính dashboard này định nghĩa đang **fail** ngay trên snapshot mới nhất hiện có, và điều đó không hề được nói ra ở bất kỳ đâu trên UI.

**5 vấn đề nghiêm trọng nhất** (chi tiết ở mục 4):
1. Câu insight tự sinh lộ mã nội bộ ("Transstatus -217 / Step result -5025") — người đọc không phải dev không thể hiểu, kể cả tới đọc "Cách đọc" cũng chỉ được giải thích bằng một câu chung chung.
2. Gate P0 (coverage Category ≥90%, TPE ≥85%) đang **fail** trên snapshot mới nhất (85,6% và 78,3%) — dashboard tự thấy mình "chưa đạt chuẩn go-live" nhưng không hiển thị điều này ở bất kỳ đâu cho người xem.
3. `DESIGN.md` mô tả một mục "Chất lượng dữ liệu" đã bị xoá khỏi code từ 13/8 — tài liệu không được cập nhật theo, nên câu hỏi thứ 3 trong "3 câu hỏi 10 giây" (dữ liệu này tin được không?) hiện không có nơi trả lời tập trung.
4. Mục CSAT có section riêng trong DOM (`id="csat"`) nhưng **không có trong thanh nav** — người dùng cuộn qua sẽ không biết mục này tồn tại trừ khi vô tình lướt qua.
5. 33+ trường form (checkbox bộ lọc, ô tìm ticket, textarea) không có `id`/`name`/`aria-label` — người dùng screen reader nghe toàn "checkbox" vô danh khi duyệt bộ lọc.

**3 điểm mạnh đáng giữ** (đừng "sửa" nhầm khi đang sửa lỗi trên):
1. Bảng màu contrast được tính tay lại và xác nhận đúng: `muted` text đạt ~8,2:1 trên nền tối; brand-ink tối `#6685df` (đổi từ `#0033c9` gốc) đạt ~5,4:1, so với ước tính ~2:1 nếu giữ xanh gốc — sửa đúng vấn đề thật, không phải làm màu cho đẹp.
2. Toàn bộ lý luận business (chuyển CS, reopen, 4-outcome) là deterministic, không LLM đoán số — đúng như PRODUCT.md cam kết, không có chỗ nào "bịa" khi thiếu dữ liệu (fail closed).
3. "Lý do chuyển CS" đã map được ~99,3% ticket sang nhãn người đọc được (chỉ 1/135 = 0,7% "chưa xác định") — tốt hơn hẳn dashboard CS staff tự làm (100% "chưa xác định được từ trace" ở field tương đương).

---

## 1. Phạm vi và phương pháp đánh giá

Vì tính minh bạch — để các phát hiện dưới đây kiểm chứng lại được:

- **Link deploy** (`https://cxekc399fvuv41q5mxzj25ck.ai.zalopay.xyz/#weekly`) trả về `401 Unauthorized` thật từ server (không phải lỗi trình duyệt) — đây là `DASHBOARD_AUTH_MODE=basic` ở tầng platform (Zalopay Agent Base/Traefik) đúng như README của chính project mô tả cho môi trường PaaS demo. Tôi **không** cố lấy hay nhập credential để vượt qua — dùng đúng cách: tôi chạy `.venv/bin/weekly-cs-dashboard --local --port 8765` (server đã có sẵn, đang chạy healthy) và test trên bản build SPA thật tại `http://127.0.0.1:8765/#weekly`. Toàn bộ phát hiện UI/UX dưới đây đến từ **code production thật**, không phải giả lập.
- Dữ liệu trong snapshot đang xem là **snapshot thật gần nhất** (`generated_at=2026-08-12`), không phải fake/demo — nhưng bị "cũ" vì sandbox môi trường tôi đang chạy không có route mạng ra `langfuse.zalopay.vn` (`last_error_code=langfuse_unavailable`). Cơ chế last-good snapshot hoạt động đúng như thiết kế; tôi không quy lỗi "dữ liệu cũ" này cho sản phẩm.
- Đo bằng `evaluate_script` (kích thước phần tử, contrast tính tay theo công thức WCAG, sticky offset, tràn ngang) — không phán đoán từ ảnh chụp, đúng yêu cầu kiểm chứng UI của workspace.
- Test ở desktop `1440×900` và mobile `390×844×3, mobile, touch` (đúng thiết bị chuẩn workspace yêu cầu).
- File HTML "Báo cáo hiệu quả CS Agent" mà CS staff gửi kèm là **export "Save Page As"** — CSS/font/ảnh không được lưu lại (font serif mặc định, ảnh vỡ, nút không style). Tôi **không** dùng file đó để đánh giá trực quan — chỉ trích xuất `innerText` để hiểu nội dung/thông tin họ chọn hiển thị, việc này không bị ảnh hưởng bởi CSS mất.
- Đọc toàn bộ `PRODUCT.md`, `DESIGN.md`, `AGENTS.md`, `CLAUDE.md` (cả root workspace và project), `docs/SPEC-v2.md` phần liên quan, brand guideline PDF gốc tại `../docs/zalopay-guideline/`, và 3 report tự chấm đã có trong `docs/superpowers/reports/` — để không lặp lại việc "phát hiện" những gì chính team đã biết và ghi lại rồi.

---

## 2. Đánh giá theo góc nhìn stakeholder

### 2.1 Góc nhìn C-level

Câu hỏi của persona này khi mở dashboard: *"AI có đang work không, xu hướng ra sao, tôi tin số này tới đâu, và tôi có cần lo gì không?"* — đúng 3 câu hỏi 10 giây mà chính `SPEC-v2.md §5.2` đặt ra làm mục tiêu thiết kế.

- **Trả lời được câu 1-2 (AI hiệu quả tới đâu, xu hướng)** khá tốt: hero "T2–T6 · tuần 10/08–14/08 · 511 ticket" + 2 câu insight đầu ("AI First tăng 5,2 điểm so với trung bình cùng kỳ 4 tuần trước", "Reopen sau AI First giảm 2,4 điểm...") viết đúng văn phong điều hành — số + so sánh kỳ trước + không cần đọc bảng. Đây là điểm mạnh, giữ nguyên.
- **Câu 3 (tin được không) đang thất bại theo hai cách khác nhau**:
  - Về mặt **hiển thị**: không có nơi nào một C-level lướt 10 giây thấy được "gate dữ liệu đang fail". Badge "Dữ liệu cũ" chỉ nói dữ liệu *cũ*, không nói *coverage có đủ tin không*. `DESIGN.md` từng có mục "⑤ Chất lượng dữ liệu" trả lời đúng câu này nhưng đã bị xoá khỏi code ngày 13/8 (commit `3619c42`) mà tài liệu chưa cập nhật theo — nghĩa là câu hỏi thứ 3 trong chính spec của dashboard hiện **không có nơi trả lời tập trung** nữa.
  - Về mặt **số liệu thật**: gate P0 tự định nghĩa của dashboard (`coverage_issue_category ≥ 0.90`, `coverage_tpe ≥ 0.85`) đang đo được **0,856 và 0,783** trên chính snapshot mới nhất đang hiển thị — cả hai đều fail. Báo cáo nội bộ `2026-07-31-backend-production-readiness-report.md` đã ghi nhận `go_live=BLOCKED` vì đúng lý do này từ 31/7; tới snapshot 12/8 (gần 2 tuần sau) vẫn chưa qua ngưỡng. Một C-level nhìn con số "78,5% AI First" trên UI sẽ không biết rằng có tới ~21,7% ticket thiếu field TPE để phân loại đáng tin — con số đẹp đang được trình bày tách rời khỏi cảnh báo "nhưng nền tảng phân loại nó chưa đủ vững."
- **Rủi ro uy tín cụ thể**: nếu một C-level chụp màn hình phần "Tín hiệu chuyển CS nổi bật" để đưa vào slide/báo cáo (hành vi rất tự nhiên với một dashboard có nút "Copy TSV"/"Tải CSV" mời gọi trích xuất), câu "Transstatus -217 / Step result -5025" sẽ đi thẳng vào slide đó. Không ai ở tầng quản lý biết `-217` nghĩa là gì — kể cả hỏi lại CS agent team cũng phải tra code. Đây là kiểu lỗi âm thầm phá uy tín: không sập, không sai, chỉ **vô nghĩa mà trông như số liệu quan trọng**.
- **Governance đáng lo hơn cả UI**: theo đúng định nghĩa "official" trong `PRODUCT.md` Principle 5 (bằng chứng + ký duyệt bên ngoài, không tự phong), bản đang chạy **chưa official** — UXD/Brand Owner/Design System Owner chưa duyệt. Nhưng nó đã có sẵn một URL trông như "deployment" (`ai.zalopay.xyz`, có Basic Auth ở edge) và đang được đưa cho tôi đánh giá như bản thật. Nếu C-level xem bản này và đối xử với nó như bản chính thức, trong khi chính đội ngũ tạo ra nó biết rõ 8 deviation còn treo (kể cả "chưa có CS user nào test task thật") — đó là một khoảng cách kỳ vọng cần được nói rõ ràng, minh bạch trước khi share rộng hơn, không phải lỗi kỹ thuật để "fix".

### 2.2 Góc nhìn Head of CS

Câu hỏi của persona này: *"Tuần này CS của tôi bận cỡ nào, ticket nào đang có vấn đề thật, khách có đang khó chịu không, và tôi cần can thiệp ở đâu?"*

- **Điểm mạnh rõ**: bảng "Lý do chuyển CS" map được 8 loại lý do có tên người đọc được ("Skill đề xuất chuyển CS", "Khách tiếp tục hỏi sau 3 phản hồi AI", "Phát hiện nội dung có dấu hiệu can thiệp hệ thống"...) và mỗi ticket trong Explorer có cột "Lý do chuyển CS" + link "Vì sao?" dẫn tới `TraceExplainer` giải thích từng ticket. Đây là tính năng CS-agent team **không có** trong bản CS staff tự làm (bản đó 100% ghi "Chưa xác định được từ trace"). Nếu Head of CS cần biết "sao tuần này chuyển CS tăng", họ có đường đi thật để trả lời, không chỉ nhìn con số tổng.
- **Nhưng cùng lúc, "Transstatus"/"Step result" — đúng thứ Head of CS cần khi muốn biết "ticket đang stuck ở khâu kỹ thuật nào của giao dịch" — lại là dimension duy nhất KHÔNG được dịch.** Trong khi "Lý do chuyển CS" (do input/output guardrail quyết định) được đầu tư dịch nghĩa kỹ, cặp (Transstatus, Step result) đến từ `tool:get_transaction_processing_engine_data` — vốn nói về *engine thanh toán*, thứ Head of CS rất cần hiểu khi ticket IBFT chiếm 59,5% tổng ticket tuần này — lại bị bỏ ngỏ. Bộ lọc "Transstatus" trong Ticket Explorer liệt kê thẳng `1, -217, -244, -268, -332, -333, -344, -348, -357, -365, -367, -369, -370, -374, -375, -380, -383, -6038, -63, -993` — 19 mã số, không nhãn, không mô tả. Head of CS muốn lọc "ticket bị lỗi timeout ở bước xác thực ngân hàng" sẽ phải đoán con số nào tương ứng, hoặc bỏ qua bộ lọc này hoàn toàn.
- **CSAT — không kiểm chứng trực tiếp được ở tuần đang xem** (tuần 10/08–14/08 chưa có dữ liệu CSAT Freshdesk: "Chưa có dữ liệu CSAT Freshdesk cho tuần này."). Theo changelog trong `CLAUDE.md` (mục v13-v16), Ticket Explorer có cột "Mức độ hài lòng" và "nội dung phản hồi 10 item/trang" — nghĩa là khả năng đọc verbatim CSAT theo từng ticket **có tồn tại**, chỉ là gộp vào Ticket Explorer thay vì có feed riêng như bản CS staff tự làm. Tôi không có tuần nào có dữ liệu CSAT thật để xác nhận trải nghiệm đọc verbatim này có tốt bằng bản kia hay không — khuyến nghị Head of CS tự kiểm tra ở một tuần có dữ liệu CSAT trước khi kết luận, tôi không khẳng định đây là gap.
- **">3 lượt xử lý chưa chuyển CS"** — đúng loại tín hiệu cảnh báo sớm Head of CS cần ("ticket đang vật lộn nhưng chưa ai biết") — hiện = 0 trong tuần đang xem, tốt, nhưng cách trình bày (chỉ 1 con số, không link trực tiếp xuống danh sách 10 ticket cụ thể ở mục dưới) buộc phải cuộn xuống tận "Ticket có hơn 3 lượt xử lý" để thấy danh sách — nên có anchor link ngay tại KPI card.

### 2.3 Góc nhìn CS staff (người dùng hàng ngày)

Câu hỏi của persona này: *"Tôi cần tra 1 ticket cụ thể, hoặc lọc nhanh nhóm ticket đang có vấn đề, và tôi có thể đang làm việc này trên điện thoại giữa ca."*

- **Ticket Explorer đủ mạnh về filter** (14 chiều lọc: tuần, category, app, product code, skill, intent, transstatus, >3 lượt xử lý, đã chuyển CS, lý do chuyển CS, bắt đầu cuối tuần...) — nhưng **mạnh tới mức áp đảo**: 33 trường input/select/checkbox không có `id`/`name`/`aria-label` (xem 4.3), tức là nếu CS staff dùng screen reader hoặc trợ năng bàn phím, họ nghe toàn "checkbox, chưa chọn" không tên khi duyệt qua bộ lọc Category (30+ giá trị) hay App (100+ giá trị).
- **Trên mobile — nơi CS staff nhiều khả năng tra cứu nhanh giữa ca — có 3 vấn đề cụ thể đo được, không phải cảm tính**:
  1. Header sticky chiếm **276px trên tổng 844px chiều cao** màn hình (32,7%) — gần 1/3 màn hình bị chiếm bởi logo + toggle + badge trước khi thấy được số nào.
  2. Thanh tab điều hướng (6 tab) rộng 786px nhét vào khung 390px — phải vuốt ngang mới thấy hết "So sánh segment", "Chẩn đoán", "Ticket Explorer". (Điểm cộng: có mask gradient mờ dần ở mép phải làm dấu hiệu còn nội dung — không phải dead-end vô hình, ghi nhận đây là làm đúng.)
  3. Trên desktop, 178/318 phần tử tương tác (56%) nhỏ hơn ngưỡng chạm tối thiểu 44px — checkbox 18×18px, link "Vì sao?"/mã ticket cao 24px. Số đo lại trên mobile chỉ còn 29/318 (9%) nhỏ — tốt hơn nhiều, nhưng **các phần tử cụ thể tôi nghi ngờ nhất (checkbox chọn cột, link ticket trong Explorer) là loại CS staff sẽ chạm nhiều nhất khi lọc trên điện thoại** — khuyến nghị đo lại riêng phần Ticket Explorer ở mobile, không chỉ tin vào tổng số 9%.
- **"Vì sao?" là điểm cộng thật sự đáng khen** cho persona này: mỗi dòng ticket có link giải thích riêng — đúng thứ một CS staff cần khi khách hỏi lại "tại sao ticket của tôi bị chuyển" mà không phải hỏi ngược lại team Dev.

---

## 3. Chi tiết theo khía cạnh (bằng chứng kỹ thuật)

### 3.1 Dữ liệu & độ tin cậy

**3.1.1 — [Nghiêm trọng] Câu insight tự sinh và bộ lọc "Transstatus" phơi bày mã nội bộ chưa dịch nghĩa**

Nguyên văn lấy trực tiếp từ DOM (`http://127.0.0.1:8765/#weekly`, tuần 10/08–14/08):

> "Tín hiệu chuyển CS nổi bật: Transstatus 1 / Step result 1 14,1%, Transstatus -244 4,4%, Transstatus -217 / Step result -5025 1,5% — tính trên 135 ticket đã chuyển CS."

Câu này nằm ngay sau hai câu insight viết rất tốt ("AI First tăng 5,2 điểm...", "Reopen sau AI First giảm 2,4 điểm...") — độ tương phản giữa câu 1-2 (đọc được ngay) và câu 3 (mã nội bộ trần trụi) rất rõ khi đọc liền mạch trên trang thật.

Tôi đã kiểm tra cả 3 nơi dimension này xuất hiện — cả 3 đều bỏ ngỏ như nhau, không phải lỗi đánh máy một chỗ:
1. Câu insight tự sinh (trên).
2. Dropdown filter "Transstatus" trong Ticket Explorer: liệt kê thẳng `1, -217, -244, -268, -332, -333, -344, -348, -357, -365, -367, -369, -370, -374, -375, -380, -383, -6038, -63, -993, Không xác định` — 19 mã, không nhãn.
3. Panel "Cách đọc" (`#howToReadPanel`, chính là nơi dashboard tự nhận trách nhiệm giải thích cách đọc số) — toàn văn liên quan: *"Transstatus và Step result là trạng thái xử lý giao dịch."* — đúng một câu, không giải thích `-217` khác `-244` ở đâu, không nói dấu âm nghĩa là gì.

`CLAUDE.md` xác nhận rõ nguồn: TPE (Transstatus, Step result) tới từ `tool:get_transaction_processing_engine_data`, tách biệt hoàn toàn khỏi tầng "Lý do chuyển CS" (vốn được map kỹ qua `taxonomy.v2.json`). Vấn đề không phải là dữ liệu sai — mà là dimension này chưa được đầu tư một tầng dịch nghĩa giống hệt "Lý do chuyển CS" đã có, trong khi nó xuất hiện công khai ở 3 nơi cho người đọc không phải dev.

*Đề xuất:* map `(transstatus, step_result)` sang nhãn người đọc được (ít nhất nhóm theo "thành công/timeout/lỗi xác thực/lỗi ngân hàng đối tác"...) trước khi cho vào câu insight tự sinh; nếu chưa map được, ẩn cặp giá trị này khỏi câu insight tự động và khỏi dropdown filter cho tới khi có nhãn — đừng để "chưa dịch được" trở thành "hiển thị số thô".

**3.1.2 — [Nghiêm trọng] Gate P0 đang fail trên snapshot mới nhất, không hiển thị ở UI**

Từ `GET /api/dashboard` (snapshot thật `generated_at=2026-08-12T05:41:13Z`):

```
coverage.issue_category = 0.8558780679143786   (ngưỡng P0: ≥ 0.90)
coverage.tpe            = 0.7825843326235571   (ngưỡng P0: ≥ 0.85)
```

Áp đúng công thức P0 mà `CLAUDE.md` định nghĩa (`coverage_issue_category`, `coverage_tpe`, ngưỡng 0,90/0,85), cả hai đều **fail** — nhất quán với báo cáo nội bộ `2026-07-31-backend-production-readiness-report.md` (`p0_data=FAIL`, `go_live=BLOCKED`) gần 2 tuần trước. Lưu ý: số `coverage` trong payload API là số **theo từng dimension của dashboard**, khác với số P0 gate chính thức mà CLI `verify-dimensions` tính riêng trên toàn bộ raw ticket — bản thân spec 01/8 của project đã cảnh báo không được gộp hai số này làm một; tôi trích số dashboard-facing ở đây vì đó là số duy nhất người dùng UI thực sự nhìn thấy được.

*Đề xuất:* không cần hiển thị số P0 kỹ thuật cho end-user, nhưng cần một tín hiệu tổng hợp ("độ tin cậy phân loại tuần này: thấp/trung bình/cao") ở cấp dashboard — đây chính là việc mục "Chất lượng dữ liệu" (đã bị xoá, xem 3.2.2) từng làm.

**3.1.3 — [Trung bình] Coverage trung bình có thể che khuất biến động thật giữa các tuần**

`CLAUDE.md` tự ghi nhận ví dụ thật: `skill` coverage dao động 0,3%→83% qua 5 tuần trong khi headline "coverage skill 50,2%" là trung bình che mất biến động đó. Tôi không kiểm tra lại số này (đã có sẵn trong tài liệu chính chủ), nhưng nó xác nhận một rủi ro chung: **bất kỳ con số coverage nào hiển thị dạng trung bình một tuần cần ghi rõ đây là snapshot một tuần, không phải xu hướng ổn định** — nên kiểm tra xem KPI card hiện tại có vô tình gây hiểu lầm "coverage ổn định ở mức X%" không.

### 3.2 Thông tin & kiến trúc thông tin (IA)

**3.2.1 — Không có router thật — toàn bộ là một trang cuộn liên tục**

`frontend/src/main.tsx` chỉ mount một `DashboardScreen`; không có react-router, không có route config. Thanh nav ("Báo cáo tuần", "Độ phủ Freshdesk", "Xu hướng", "So sánh segment", "Chẩn đoán", "Ticket Explorer") toàn bộ là **anchor link vào cùng một trang dài**, không phải tab thật chuyển nội dung. Đây là lựa chọn thiết kế hợp lý cho "sổ điều hành tuần" (đọc tuần tự từ trên xuống) — không phải bug — nhưng có nghĩa là với C-level chỉ muốn xem đúng 1 mục, họ vẫn phải tải toàn bộ trang (bảng segment 25 dòng, Ticket Explorer với hàng trăm option filter) dù chỉ cần đọc phần đầu.

**3.2.2 — [Nghiêm trọng] Tài liệu thiết kế mô tả một mục đã không còn tồn tại trong code**

`DESIGN.md` (cập nhật lần cuối ghi "2026-08-04") liệt kê "⑤ Chất lượng dữ liệu" là một mục hiển thị thật trong "Surface composition". Nhưng: không có file `DataQualitySection.tsx` nào trong `frontend/src/components/` hiện tại (chỉ còn dấu vết `frontend/coverage/components/DataQualitySection.tsx.html` — artifact test-coverage cũ chứng minh nó từng tồn tại); `AppShell.tsx` không có entry nav nào cho mục này; `BelowFold.tsx` không render nó (dù comment trong chính file này ở dòng 746-749 vẫn ghi là đang xử lý "data-quality disclosure"). Commit `3619c42` ("...finish data-quality section removal...") xác nhận đây là một quyết định sản phẩm có chủ đích, không phải lỗi — nhưng `DESIGN.md` chưa được cập nhật theo, nên tài liệu hiện mô tả sai những gì đang chạy thật.

*Đề xuất:* cập nhật `DESIGN.md` phần "Surface composition" để khớp code hiện tại, và quyết định rõ: câu hỏi "dữ liệu này tin được không" (10-second question #3 của chính SPEC-v2) hiện đang được trả lời bằng cách nào — bằng các badge/caption rải rác (freshness chip, "Chưa cập nhật hôm nay") có đủ hay cần khôi phục một điểm hội tụ?

**3.2.3 — [Trung bình] Mục CSAT tồn tại trong DOM nhưng không có trong thanh nav**

`CsatSection.tsx` render với `id="csat"`, nằm giữa "So sánh segment" và "Chẩn đoán" theo thứ tự DOM thật — nhưng mảng nav trong `AppShell.tsx` nhảy thẳng từ "So sánh segment" sang "Chẩn đoán", bỏ qua CSAT. Một người chỉ dùng thanh nav để định vị sẽ không biết mục CSAT tồn tại giữa hai mục đó, dù đây là tính năng đã qua nhiều vòng phát triển (v11→v18 theo changelog).

*Đề xuất:* thêm entry nav cho CSAT — việc này nhỏ, rẻ, và tính nhất quán (mọi mục lớn khác đều có nav entry) không nên có ngoại lệ không giải thích được.

**3.2.4 — [Nhẹ] Số phiên bản lệch giữa code và tài liệu**

`_STORAGE_VERSION` trong `dashboard_schema.py` hiện là `20`; mọi tài liệu (CLAUDE.md, DESIGN.md, changelog trong PRODUCT.md) đều dừng ở mô tả v18. Đúng loại lỗi mà `CLAUDE.md` mục "Kiểm chứng giả định trước khi thiết kế" tự cảnh báo ("đừng tin con số trong doc hay spec cũ") — bằng chứng cho thấy cảnh báo đó là cần thiết trên thực tế, không chỉ lý thuyết.

### 3.3 Bố cục & UI/UX

**3.3.1 — Sticky header/table đo được (evaluate_script, không suy đoán từ ảnh)**

| Viewport | Header sticky height | % chiều cao màn hình |
|---|---|---|
| Desktop 1440×900 | 176px | 19,6% |
| Mobile 390×844 | 276px | 32,7% |

Header không tràn nội dung (không phải bug), nhưng ở mobile chiếm gần 1/3 màn hình trước khi thấy dữ liệu — cho một "sổ điều hành" cần đọc nhanh, đây là chi phí thật cần cân nhắc rút gọn (ví dụ: thu badge "Freshdesk: cần cookie" vào một icon có tooltip thay vì pill full-width).

Sticky table header (nhóm cột + tên cột trong bảng tuần) xếp lớp đúng: group header `top:0px` cao 34px, header cột `top:34px` cao 45px — tổng khớp chính xác, không lặp lại lỗi cũ đã ghi trong `CLAUDE.md` (offset 134px sai vị trí ở bản legacy). **Đây là bug cũ đã được xác nhận sửa đúng ở bản SPA — ghi nhận, không cần sửa lại.**

**3.3.2 — [Trung bình] Tap target dưới ngưỡng 44px — chủ yếu ở desktop, cần đo lại có chủ đích ở mobile**

Desktop 1440×900: 318 phần tử tương tác, **178 (56%)** nhỏ hơn 44×44px — mẫu cụ thể: checkbox 18×18px (bộ chọn cột, bộ lọc), link mã ticket 61×24px, link "Vì sao?" 47×24px, icon mở trace 24×24px.
Mobile 390×844: cùng phép đo, chỉ còn **29/318 (9%)** nhỏ — cải thiện rõ, nhưng tôi không xác nhận được nguyên nhân chính xác (CSS responsive tăng kích thước thật, hay các phần tử đó đang cuộn ngang ra ngoài khung đo tại thời điểm chạy script). Khuyến nghị người trong team tự đo lại riêng khu vực Ticket Explorer ở mobile (nơi checkbox/link dày đặc nhất) trước khi kết luận mobile đã ổn.

**3.3.3 — [Trung bình] 33+ trường form không có `id`/`name`/`aria-label`**

Chrome DevTools chỉ tự động gộp mẫu và báo 4, nhưng truy vấn trực tiếp DOM (`input, select, textarea` không có `id` và không có `name`) ra: hầu hết checkbox bộ lọc Category/App, 1 input số (ô nhập mã ticket, `inputmode="numeric"`), 2 select (Kết quả, Mức độ hài lòng), 1 textarea (`rows="4"`, không rõ mục đích hiển thị). Không cái nào có `aria-label`. Đây là khoảng trống a11y thật — WCAG 4.1.2 (Name, Role, Value) — ảnh hưởng người dùng screen reader hoặc autofill trình duyệt.

**3.3.4 — [Nhẹ] CSP chặn một lời gọi `eval()` — có thể là code chết, đáng kiểm tra**

Console log: `Content Security Policy of your site blocks the use of 'eval' in JavaScript` tại `assets/index-BzicdxLb.js:8`. CSP của dashboard cấm `unsafe-eval` đúng như `CLAUDE.md` mô tả (đây là làm đúng, không phải lỗi CSP) — nhưng có nghĩa **một đoạn code trong bundle đang cố gọi `eval`/`new Function` và bị chặn âm thầm**, khả năng cao đến từ một dependency (chart lib?) chứ không phải code tự viết (dự án tự nhận không dùng `eval`). Nếu tính năng nào phụ thuộc đường code đó, nó đang fail im lặng. Đáng dò ngược xem source map trỏ về thư viện nào.

**3.3.5 — [Điểm cộng] Thanh nav cuộn ngang trên mobile có dấu hiệu còn nội dung**

`mask-image: linear-gradient(90deg, #000 0, #000 calc(100% - 28px), transparent 100%)` trên `<nav>` — mờ dần 28px cuối bên phải báo hiệu còn tab chưa thấy, thay vì cắt cụt đột ngột. Chi tiết nhỏ nhưng đúng thực hành tốt, giữ nguyên.

### 3.4 Brand guideline

Đối chiếu trực tiếp với `../docs/zalopay-guideline/zalopay-brand-guidelines.pdf` (bản 2024) và giá trị computed style thật lấy từ trang đang chạy:

| Hạng mục | Chuẩn brand | Thực tế đo được | Kết luận |
|---|---|---|---|
| Font | Aeonik Pro, mọi heading/body | `"Aeonik Pro", "Segoe UI", system-ui...` — self-hosted, WOFF2 | Đúng chuẩn |
| Màu chính | Blue `#0033C9`, Green `#00CF6A` | `--brand-blue`/`--brand-green` khớp chính xác | Đúng chuẩn |
| Case chữ | Sentence case, không hiệu ứng chữ (gradient/outline/shadow) | Xác nhận qua screenshot header — chữ phẳng, không hiệu ứng | Đúng chuẩn |
| Logo trên nền | Chỉ dùng full-color/nền trắng hoặc trắng/nền đen-hoặc-2-màu-brand | Header dark theme dùng logo trắng trên nền tối `#0d1117` | Đúng chuẩn (thuộc case được duyệt) |
| Z-mark cropping | Chỉ được cắt ở mép trái/phải, không được cắt trên/dưới | `DESIGN.md` tự khai cắt ở mép phải | Đúng chuẩn (theo tự khai, chưa tự kiểm tra lại bằng mắt) |
| Contrast brand-ink dark mode | — | `#0033c9` gốc ≈ 2:1 trên nền tối (tính tay, cùng bậc nghiêm trọng với con số 1,91:1 mà `DESIGN.md` tự đo) → đổi sang `#6685df` ≈ **5,4:1** (tính tay theo công thức WCAG) | Deviation **đã công bố** trong DESIGN.md, và tôi xác nhận độc lập là sửa đúng vấn đề thật |
| Màu `critical` | Zalopay guideline **không có màu đỏ** nào (chính hoặc phụ) | `--critical: #b42318` — đỏ, không có trong palette chính thức | **Deviation chưa công bố** — không nằm trong danh sách 8 deviation mà DESIGN.md tự thừa nhận |
| Trộn ngôn ngữ | SPEC-v2 §... cấm nhãn tiếng Anh lẫn trong câu tiếng Việt | "Skill đề xuất chuyển CS", "Category", "Intent", "TPE", "CSAT" dùng như danh từ riêng trong câu Việt | Judgment call — hợp lý nếu coi là thuật ngữ taxonomy cố định, nhưng nên có quyết định tường minh thay vì để trôi tự nhiên |

*Đề xuất ưu tiên brand:* (a) xử lý màu `critical` — hoặc tìm cách phối trong palette chính thức (v.d. dùng orange `#FF8A00` đậm hơn cho mức "critical", giữ đỏ cho trường hợp thật sự cần khác biệt tuyệt đối), hoặc bổ sung vào danh sách deviation đã công bố kèm lý do (an toàn/nhận diện > tuân thủ tuyệt đối — như chính Product Principle 4 của dự án đã cho phép). (b) Không có gì cấp bách khác về brand — phần này làm tốt hơn tôi kỳ vọng trước khi đo.

---

## 4. Đối chiếu với dashboard CS staff tự làm (vibe-coded)

File CS staff gửi là export "Save Page As" của route `#diagnostics`, CSS/ảnh không còn nên tôi chỉ so sánh được **nội dung/thông tin**, không so được thẩm mỹ. Đối chiếu từng ý tưởng nổi bật họ có, để tránh vừa liệt kê máy móc "học hết":

| Ý tưởng ở bản CS staff | Đã có ở bản chính thức? | Ghi chú |
|---|---|---|
| Toggle so sánh "cùng kỳ tới hôm nay" / "tuần đủ" | **Đã có, tương đương** | "Cùng kỳ đến T3" / "Tuần đủ" — cùng ý tưởng, đã implement |
| Câu tóm tắt bằng chữ dưới mỗi chart ("Tuần gần nhất có dữ liệu: ...") | **Đã có, tương đương** | Y hệt pattern, cùng vị trí |
| Ghi rõ nguồn + độ mới từng nhóm số liệu (CSAT: Freshdesk · cập nhật ...) | **Đã có, chi tiết hơn** | Bản chính thức có badge freshness riêng cho từng phần, không chỉ CSAT |
| "Lý do chuyển CS" | **Đã có, tốt hơn nhiều** | Bản CS staff: 100% "chưa xác định được từ trace". Bản chính thức: chỉ 0,7% chưa xác định, 8 nhãn người đọc được |
| Ticket-level explainability | **Chỉ có ở bản chính thức** | "Vì sao?" + `TraceExplainer` — bản CS staff không có gì tương đương |
| **Cảnh báo "Mẫu nhỏ" trên bảng thống kê có n thấp** | **Không có ở bản chính thức** | Bản CS staff gắn "Mẫu nhỏ" khi n=9, n=11. Bản chính thức có dòng n=1, n=2 trong "Lý do chuyển CS" hiển thị % sạch, không cảnh báo mẫu nhỏ |
| **Link "Số liệu này đáng tin tới đâu → Mở chi tiết" ngay cạnh từng con số** | **Không có ở bản chính thức** | Đây là affordance rõ ràng nhất đáng học — đúng tinh thần minh bạch mà chính dashboard chính thức đã làm rất tốt ở nơi khác (badge freshness, fail-closed labeling), chỉ là chưa có **per-metric**, chỉ có per-section |

**Kết luận phần này:** bản chính thức đã vượt bản CS staff tự làm ở gần như mọi khía cạnh thực chất (độ phủ nhãn, khả năng truy vết ticket, độ chi tiết nguồn dữ liệu). Thứ đáng mang qua chỉ có **hai** ý tưởng cụ thể, cả hai đều rẻ để làm và khớp hoàn toàn với triết lý sẵn có của dashboard chính thức (minh bạch, fail-closed, không bịa số):
1. Cảnh báo "mẫu nhỏ" (ví dụ n<10) trên mọi bảng tỷ lệ %, đặc biệt "Lý do chuyển CS" đang có dòng n=1/n=2 hiển thị % không kèm cảnh báo.
2. Một affordance "độ tin cậy" per-metric (không cần đúng bản UI đó, có thể là tooltip/icon (i) cạnh mỗi KPI card dẫn tới đúng con số coverage tương ứng) — đây chính là cách rẻ nhất để lấp khoảng trống đã nêu ở 3.2.2 mà không cần dựng lại nguyên một section "Chất lượng dữ liệu".

---

## 5. Danh sách ưu tiên sửa

| # | Vấn đề | Mức độ | Ước lượng công sức | Tham chiếu |
|---|---|---|---|---|
| 1 | Ẩn/dịch nghĩa cặp Transstatus+Step result khỏi câu insight tự sinh và filter dropdown cho tới khi có nhãn | Nghiêm trọng | Trung bình (cần mapping nghiệp vụ trước, code sau) | 3.1.1 |
| 2 | Thêm tín hiệu "độ tin cậy phân loại tuần này" tổng hợp, thay thế mục Chất lượng dữ liệu đã xoá | Nghiêm trọng | Nhỏ–Trung bình | 3.1.2, 3.2.2, 4 |
| 3 | Cập nhật `DESIGN.md` khớp code thật (bỏ mục đã xoá, cập nhật version, note deviation `--critical`) | Trung bình | Nhỏ (tài liệu) | 3.2.2, 3.2.4, 3.4 |
| 4 | Thêm nav entry cho CSAT | Nhẹ | Rất nhỏ | 3.2.3 |
| 5 | Gắn `id`/`name`/`aria-label` cho toàn bộ input/select/checkbox/textarea trong panel filter | Trung bình | Nhỏ–Trung bình (số lượng nhiều nhưng cơ học) | 3.3.3 |
| 6 | Thêm cảnh báo "mẫu nhỏ" (n<10) trên bảng % — ít nhất ở "Lý do chuyển CS" | Nhẹ–Trung bình | Nhỏ | 4 |
| 7 | Kiểm tra lại tap target thật trên mobile ở riêng khu vực Ticket Explorer | Nhẹ (việc kiểm tra) | Rất nhỏ | 3.3.2 |
| 8 | Dò nguồn gốc lời gọi `eval()` bị CSP chặn — xác nhận không có tính năng nào chết âm thầm | Nhẹ | Nhỏ (điều tra) | 3.3.4 |
| 9 | Quyết định tường minh cách xử lý `--critical` (đổi màu hoặc công bố deviation có lý do) | Nhẹ | Rất nhỏ | 3.4 |
| 10 | Cân nhắc affordance "độ tin cậy" per-metric (tooltip/icon cạnh KPI card) | Trung bình (giá trị cao, không khẩn) | Trung bình | 4 |

---

*Ghi chú cuối: mọi số đo trong báo cáo này lấy trực tiếp từ DOM/API thật của bản đang chạy tại thời điểm đánh giá (2026-08-18, snapshot dữ liệu 2026-08-12), có thể đổi khi refresh mới hoặc code mới. Contrast ratio ở mục 3.4 tính tay theo công thức WCAG 2.x (relative luminance), làm tròn — nên xác minh lại bằng công cụ đo màu chuyên dụng trước khi đưa vào tài liệu chính thức nếu cần độ chính xác cao hơn.*
