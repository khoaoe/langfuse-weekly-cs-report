# CLAUDE.md — langfuse-weekly-cs-report

Dashboard hiệu quả CS-agent theo tuần, read-only trên Langfuse. Đọc `../CLAUDE.md` trước để lấy bối cảnh workspace và gateway.

**Đây là Git repo riêng, nhánh mặc định `main`.** Không commit `.env`, `runtime/`, `artifacts/`, cache hoặc credential. Không tuyên bố đã verify Docker — Docker không chạy được ở đây.

## Lệnh

```bash
# Runtime dependency sync when a local runtime needs to be prepared.
uv sync --locked --no-dev
.venv/bin/weekly-cs-dashboard --local --port 8765     # dashboard local, loopback only
.venv/bin/weekly-cs-report dry-run --weeks 12
.venv/bin/weekly-cs-report verify-dimensions --weeks 12
.venv/bin/weekly-cs-report verify-dimensions --weeks 12 --include-current-wtd --as-of 2026-07-31T10:00:00+07:00 --require-p0
.venv/bin/weekly-cs-report inspect-session SESSION_ID

# Deterministic full Python suite; do not add dev dependencies to .venv.
task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"

npm ci                                               # Node 24, npm 11
npm run test:unit
npm run typecheck
npm run build                                        # output: src/weekly_cs_report/static/spa/
npm run test:e2e
python scripts/verify_brand_assets.py --require-canonical   # cần sibling ../docs/zalopay-guideline
python scripts/generate_brand_fonts.py                      # OTF -> WOFF2, deterministic
python scripts/verify_wheel_assets.py                       # wheel có đủ asset lồng nhau
python scripts/e2e_server.py                                # FastAPI thật + snapshot tổng hợp, 127.0.0.1:18765
DASHBOARD_FRONTEND_MODE=legacy .venv/bin/weekly-cs-dashboard --local --port 8765   # rollback
```

`verify-dimensions` mặc định là diagnostic (exit `0`); với `--require-p0`, nó
in đúng một JSON aggregate đã privacy-validate rồi chỉ trả exit `0` khi cả hai
threshold P0 pass; mọi trường hợp khác trả exit `1`. Không đặt credential trên
argv.

Không suy luận trạng thái, phiên bản Python, hoặc việc có pytest của shared
`.venv` từ tài liệu này. Xác minh deterministic dùng isolated locked dev env;
Task 2 không sửa shared `.venv`.

## Nguồn sự thật

`docs/SPEC-v2.md` thắng `README.md` khi mâu thuẫn về metric. Riêng P0 data
integrity, `docs/superpowers/specs/2026-07-31-langfuse-only-p0-data-integrity-design.md`
khóa công thức gate, mẫu số và ngưỡng. Spec
`docs/superpowers/specs/2026-08-01-p0-applicable-coverage-diagnostic-design.md`
là authority mới nhất cho **diagnostic bổ sung**, nhưng không được thay đổi bất
kỳ legacy P0 field hay `p0_pass` nào. Hai spec cùng có hiệu lực ở hai phạm vi
này; mọi thiết kế Freshdesk/applicability cũ khác đều bị thay thế.
§5 của SPEC-v2 là đặc tả UI (§5.2 ba câu hỏi 10 giây, §5.3 palette + nguyên
tắc, §5.4 luật mã hoá thị giác).

`PRODUCT.md` khóa user, task, metric, API và privacy contract; `DESIGN.md` khóa brand token, layout, state và deviation.

Frontend production candidate theo `docs/superpowers/specs/2026-07-30-zalopay-production-frontend-design.md` và plan cùng ngày.

`assets/` là asset store của repo; build import từ đó, **không** import thẳng từ
`../docs/zalopay-guideline` (nguồn canonical để đối chiếu). `assets/brand-provenance.json`
pin hash Zalopay, `assets/third-party-provenance.json` pin asset không phải Zalopay
(icon Langfuse) — đừng gộp hai manifest. Mọi user-facing copy dùng literal `Zalopay`.

Spec bổ sung ở `docs/superpowers/specs/`:

| Spec | Nội dung |
|---|---|
| `2026-07-29-langfuse-weekly-cs-dashboard-design.md` | V1, khai báo điều kiện mở khoá V2 |
| `2026-07-29-live-on-open-dashboard-design.md` | Cache live-on-open, refresh nền |
| `2026-07-30-reopen-reason-labeling-design.md` | Lớp gán nhãn lý do reopen (V2). §10 có 14 bước, **3 điểm dừng người quyết** |
| `2026-07-30-dashboard-ui-uplift-design.md` | Nâng cấp UI. §9 có 9 tiêu chí sẵn sàng giao user |
| `2026-07-30-zalopay-production-frontend-design.md` | React/Vite production candidate, brand, accessibility và release gate |
| `2026-07-31-dashboard-usage-value-design.md` | Viết lại copy, so sánh cùng kỳ cho tuần đang chạy, timeline thay đổi skill. Part C chờ discovery Batch 3 |
| `2026-07-31-langfuse-only-p0-data-integrity-design.md` | Contract P0 active: chỉ Langfuse, raw all-ticket denominator, ngưỡng Category `0.90` và TPE `0.85`. **Sửa 2026-08-01**: thu hẹp phạm vi về gate P0 + metric lõi; CSAT Freshdesk là đường đọc riêng |
| `2026-08-01-p0-applicable-coverage-diagnostic-design.md` | **Đã implement + rerun live.** Gate metadata trong `tranxdetail` đạt 100%; số 95,7% là nguồn observation riêng, không được trộn vào gate. Category còn lỗi thật — 767 ticket vắng `entry_point` thiếu Category 100%, sửa ở `cs-agent-master`. Gate/ngưỡng giữ nguyên; `"null"` (574) tách khỏi vắng (767) |
| `2026-08-01-dashboard-clarity-round2-design.md` | **Đã implement.** Bỏ badge lệch scope và copy nội bộ, thống nhất định dạng số, trục chart tròn + tooltip, Explorer có filter tuần. Frontend thuần, **không bump version** |
| `2026-08-01-freshdesk-csat-integration-design.md` | **Luồng Freshdesk đã implement đến v12; dashboard hiện ở v21** (con số tại thời điểm viết dòng này là v18, đã bump tiếp qua v20 rồi v21 — xem `_STORAGE_VERSION` trong `dashboard_schema.py:33`). Survey vẫn chỉ gồm Admin CS ZaloPay; bulk không mở được nên dùng job rời + cache. v11 đếm latest response mỗi ticket cho summary, v16 thêm breakdown theo từng response bên cạnh breakdown ticket theo outcome/Skill/Category. Ticket Explorer có mức hài lòng và nội dung phản hồi 10 item/trang. Private roster 55 candidate đã duyệt ngày 2026-08-03 (45 human/10 exclude, không lộ identity); v12 đối chiếu `AI xử lý trọn` bằng metadata-only conversation, requester/unknown không bị suy là human. v13 thêm thời gian mở ticket; v14 thêm partition `Lý do chuyển CS` từ đúng trace chuyển đầu tiên, gồm cả `output_guardrail`; v15 đưa enum reason an toàn vào Ticket Explorer và thêm sort bảng tổng hợp. Không đưa ID nội bộ ra browser. CSAT cache/reconciliation không đổi version. Serving process không gọi Freshdesk **ngoại trừ đúng 1 exception** (2026-08-12): `POST /api/freshdesk-cookie` gọi `FreshdeskUIClient.verify()` — đúng 1 request UI API rẻ nhất để xác thực cookie trước khi lưu, không bao giờ fetch dữ liệu ticket. `web.py` bị cấm import mọi hàm fetch bulk (`FreshdeskClient`, `fetch_csat_population`, `list_ticket_metadata`, ...) và mọi REST credential — enforce bằng `tests/test_deployment_contract.py::test_reporting_package_keeps_freshdesk_credentials_inside_csat_cli_only` |
| `2026-08-04-freshdesk-cs-agent-entry-coverage.md` | **Đã implement (storage version tại thời điểm đó là v18; `_STORAGE_VERSION` hiện tại là 21).** Job Freshdesk inventory dùng `per_page=50` cố định, checkpoint theo trang và theo ticket để resume; chỉ đối chiếu từ 06/07/2026. `invoked_no_result` tách khỏi `not_observed_invoked`; category 3 + public outgoing là contract agent reply. Aggregate và drill-down Freshdesk tách khỏi Ticket Explorer, cache private và API phân trang 10 ticket |
| `2026-08-12-freshdesk-cookie-crawl-design.md` | **Đã implement Phase 1-3 (client + CLI).** Cả 3 job Freshdesk (`fetch-csat`, `fetch-freshdesk-entry-coverage`, `reconcile-freshdesk-outcomes`) nhận `--auth cookie\|rest`, mặc định `cookie`. `FreshdeskUIClient` (`freshdesk_csat.py`) gọi UI API nội bộ (`/api/_/...`, cookie header) thay REST — không tiêu quota REST dùng chung. `satisfaction_ratings`/`conversations` trả shape y hệt REST (xác nhận probe 2026-08-12), không cần mapper. `list_ticket_metadata` lọc theo `created_at` (UI API từ chối điều kiện `updated_at`, xác nhận 400 `invalid_value`) — tương đương REST cho mọi caller hiện tại vì `filtered_inventory` đã tự thu hẹp về `created_at >= start` ngay sau khi fetch. Cookie lưu `runtime/freshdesk_cookie` (mode 600) + `runtime/freshdesk_cookie_state.json`. Phase 2 (dialog nhập cookie trên UI) và Phase 4 (backfill + bật cron) chưa xong |

## Phân loại KHÔNG dùng LLM

99% dashboard là deterministic. Đừng đi tìm model ở đâu:

- **Chuyển CS** = so khớp đúng một câu semantic cố định trong `taxonomy.v2.json` (`transfer.semantic_text`)
- **Reopen** = số học trên timestamp, cửa sổ 168h
- **4 outcome** (`ai_end_to_end`, `ai_then_cs`, `direct_cs`, `unclassified`) = thứ tự turn + có/không câu transfer
- **Nhóm vấn đề / App / entry point** = map field `input.other_info.meta` theo `taxonomy.v2.json`
- **TPE dashboard** = cặp `(transstatus, step_result)` từ observation
  `tool:get_transaction_processing_engine_data`; không suy ra từ metadata

Chỗ **duy nhất** cần LLM: `content_labeler.py` (lý do reopen). Thiếu config thì `llm_client.py` raise `LLMConfigurationError`, pipeline chuyển `reopen_reason.status = "pending"` — fail closed, không giả số.

## Bẫy đã biết

- `categories._tpe_mapping()` là code chết mang lỗi tương thích v1/v2: nó đọc
  key v1 `mapping["step"]`, còn `taxonomy.v2.json` chỉ có `steps` (list) —
  gọi nó trên taxonomy v2 raise `KeyError: 'step'`. Chỉ tới được qua
  `classify_tpe()` bên trong `classify_transfer()`, và `classify_transfer()`
  không có caller production nào (chỉ `tests/test_categories.py` gọi trực
  tiếp). Test đó dùng fixture `taxonomy` trỏ `config/taxonomy.v1.json` nên
  không bao giờ chạm nhánh v2 và không bắt được lỗi. Resolver v2-safe thật sự
  đang dùng production là `resolve_tpe_status()` trong
  `src/weekly_cs_report/tpe_status.py`, đọc đúng key `steps`. Đừng sửa
  `_tpe_mapping()` tưởng là đang fix code đang chạy — nó không được gọi ở
  đâu cả; nếu dọn dẹp, xoá cùng `classify_transfer()`/`classify_tpe()` và test
  tương ứng, không chỉ đổi key.

## Ràng buộc kiến trúc

- **Raw trace/observation không bao giờ serialize ra đĩa.** Hệ quả: labeler phải chạy **trong cùng lượt pipeline** khi payload còn trong bộ nhớ; không chạy lại được từ artifact.
- `static/index.html` là legacy rollback; frontend mới nằm trong `frontend/` và Vite build vào `static/spa/`.
  `DASHBOARD_FRONTEND_MODE=spa|legacy` chọn bản nào được serve; mặc định `spa`, và `main()`
  **từ chối khởi động** nếu chọn `spa` mà chưa build.
- SPA dùng external hashed JS/CSS/font/logo cùng origin; CSP cấm `unsafe-inline`, `unsafe-eval`, CDN và external request.
- FastAPI tiếp tục sở hữu API/business layer; Node/npm chỉ tồn tại trong build stage, không có trong production runtime.
- Browser dashboard dùng projection version hiện hành trong `_STORAGE_VERSION` và phải giữ `reopen_reason`; không expose storage payload, raw ticket, trace hoặc internal ID. Freshdesk entry coverage chỉ expose aggregate hoặc Ticket ID/time/status drill-down, không expose conversation text, requester hoặc agent identity.
- TanStack Query giữ last-good snapshot; poll 2 giây khi loading/refreshing, 5 phút khi ổn định,
  30 giây backoff khi `stale_error` — đừng "sửa" nhánh thứ ba thành 2 giây.
- Theme là system-first (`prefers-color-scheme`) **cộng** control `Sáng`/`Tối`; giá trị duy nhất
  được persist là literal `light`/`dark` dưới `weekly-cs-theme-v1`, áp qua `data-theme` trên root.
  Spec 2026-07-30 nói "không toggle" — quyết định này thay nó, không phải quên.
- `transfer_reasons` đã đổi grain: có `step_result_missing`, và TPE khoá theo
  `(transstatus, step_result)` — không còn `code/status/case/mapped`. Đây là breaking change
  được đưa vào từ projection v5; fixture và Zod schema phải đi cùng nhau.

## Kiểm chứng giả định trước khi thiết kế

`runtime/dashboard_snapshot.json` đọc trực tiếp được: số production đã tổng hợp cấp tuần, không PII.
Dùng nó kiểm giả định trước khi thiết kế, đừng tin số trong spec cũ — số trong spec hết hạn nhanh.
Ví dụ `views.mon_fri.by_week[*].segments.skill` cho thấy độ phủ skill chạy khoảng 0,3% → 83% qua 5 tuần,
trong khi headline "coverage skill 50,2%" là trung bình che mất điều đó.

Số version cũng vậy: đọc `_STORAGE_VERSION` trong `dashboard_schema.py`, đừng tin con số
trong doc hay spec cũ.

Repo lớn (19 module Python, ~10 component React, SPEC-v2 943 dòng). Explore agent một lượt
"đọc hết" trả report ~57KB phải ghi ra file rồi đọc lại. Chia prompt theo tầng:
metric/pipeline, payload/schema, UI/copy.
- **Runtime deps chỉ 4**: `fastapi`, `httpx`, `python-dotenv`, `uvicorn`. Không numpy, không torch. K-means + silhouette viết tay thuần Python trong `reopen_sampling.py`. Đừng thêm dep nặng.
- `llm_client.embed()` là **Protocol** (`llm_client.py:110`) — thêm provider mới bằng implementation mới, không sửa caller.
- Một worker duy nhất khi chạy production: refresh lock và cooldown là process-local.
- Phạm vi ticket: chỉ trace có root input `source == "ticket"`. Direct chat bị loại trước khi khử trùng lặp.
- `coverage.tpe` của dashboard, Transstatus, và Step result chỉ đến từ
  `tool:get_transaction_processing_engine_data`. Đây là metric observation,
  tách biệt với gate P0 metadata.
- Gate P0 chỉ đọc root trace từ Langfuse. Mẫu số là toàn bộ raw ticket unit:
  valid session đếm một lần; keyed session lỗi và ticket unit không có key vẫn
  ở trong mẫu số. Không source segment, entry point, category hay điều kiện
  field-present nào được thu hẹp mẫu số.
- P0 dùng canonical first normalized Langfuse trace:
  `coverage_issue_category = issue_category_present_count / ticket_count` với
  ngưỡng `0.90`, và `coverage_tpe = tpe_present_count / ticket_count` với ngưỡng
  `0.85`. Population rỗng fail closed; `p0_pass` chỉ true khi cả hai flag true.
- `verify-dimensions` không đọc local overlay, demo/fixture hay API ticket khác;
  package runtime không yêu cầu credential Freshdesk. Link ticket Freshdesk chỉ
  là operator navigation sau click, không phải report data source.

## Frontend production candidate

- Hướng đã khóa là “Sổ điều hành tuần”; không thêm metric, filter, route, LLM narrative hoặc “DÒNG TUẦN”.
- Stack khóa: React 19.2, TypeScript 5.9 strict, Vite 8.1, TanStack Query/Table 5/8, Zod 4,
  **`@visx/scale` + `@visx/shape` (modular, không dùng umbrella `@visx/visx`)** và CSS Modules.
  Umbrella kéo cả bộ và phá ngân sách 250 KB gzip.
- Không gọi build là “official” trước UXD/Brand approval và Design System 2.0 mapping/deviation approval.
- PNG canonical được phép làm deviation nếu chưa thể xuất SVG an toàn; không tự dựng lại logo hoặc geometry.

## Ranh giới PII trên browser

Được phép: **Ticket ID**. Không được: UserID, TransID, số điện thoại, tên/email, nội dung hội thoại, prompt/response, raw payload, ID nội bộ Langfuse (`traceId`, `sessionId`).

Kiểm sau mỗi thay đổi payload:

```bash
curl -s http://127.0.0.1:8765/api/dashboard | grep -cE 'UserID|TransID|traceId|sessionId'   # phải là 0
```

## Trạng thái hiện tại (2026-07-31)

- Observed raw-only diagnostic rerun cho fixed window kết thúc
  `2026-07-31T10:00:00+07:00`: `ticket_count=6369`,
  `issue_category_present_count=5393`,
  `coverage_issue_category=0.8467577327680955`, `tpe_present_count=5045`,
  `coverage_tpe=0.7921180719108181`; `p0_issue_category_pass=false`,
  `p0_tpe_pass=false`, `p0_pass=false`. Kết quả chính xác được kỳ vọng với
  `--require-p0` trên cùng current source là exit `1`; verdict hiện tại là
  `p0_data=FAIL`, `go_live=BLOCKED`. Đây chưa phải claim đã hoàn tất final
  current-source release rerun.
- `reopen_reason.status = "pending"`, `labeled 0/93` — chưa gán nhãn lần nào.
- Bước 8 của spec reopen §10 đã hoàn tất ngày 2026-07-31 theo ủy quyền rõ ràng của PO: ba GPT-5.6 Sol Ultra phân tích độc lập 300 dòng discovery và một GPT-5.6 Sol Ultra chốt 7 reopen driver/action-gap trong `config/reopen_labels.v1.json`. Golden sample đã được rút ngẫu nhiên thuần từ 12 tuần hoàn tất tại `as-of=2026-07-31T00:00:00+07:00`: `artifacts/reopen_golden/golden.csv` có 200 dòng gồm 170 session ngoài discovery và 30 duplicate ẩn, toàn bộ `human_label` còn trống. Đây chưa phải root cause đã xác minh; đang **DỪNG chờ người gán golden độc lập**, chưa chạy labeling live/shadow/`eval-labels` và chưa bật chiều này lên dashboard.
- CLI chung vẫn **cố ý không có** cờ `pii_approved`. Module hẹp `weekly_cs_report.reopen_sample_runner` hiện yêu cầu SHA-256 khớp đúng `pii_review.csv`, mode `0600`/thư mục `0700`, lock chống chạy trùng, và 200 dòng review đầu khớp mẫu xác định tái dựng từ chính population của `--as-of`/`--weeks` trước mọi lệnh gọi model.
- Runtime yêu cầu đúng 6 biến: `LABEL_API_KEY`, `LABEL_BASE_URL`, `LABEL_MODEL=gemma-3-27b`, `EMBED_API_KEY`, `EMBED_BASE_URL`, `EMBED_MODEL=intfloat/multilingual-e5-base`. Không có provider toggle hoặc fallback; Gemma structured generation và HF embedding 768 chiều đã được kiểm chứng live ngày 2026-07-30. Chưa kiểm chứng Docker.

## Legacy UI — chỉ dùng rollback

Các lỗi dưới đây thuộc `static/index.html`; migration mới sửa trong SPA, không tiếp tục trang điểm legacy.

- `th{position:sticky;top:var(--sticky-offset)}` áp cả trong `.weekly-table-scroll` / `.explorer-table` — hai container này có `overflow-x:auto` nên là **scroll container**, khiến header bảng nằm cách mép trên bảng 134px thay vì 0. Trong container cuộn phải `top:0`.
- `renderTrend` (`static/index.html:70`) chạy `index` trên cả 13 tuần kể cả 8 tuần rỗng → 5 cột dồn về 1/3 phải. `preserveAspectRatio="none"` + `viewBox="0 0 320 160"` render ở 1374px = giãn ngang 4,3×.
- Chart hiện vẽ cột (volume) + 2 đường (tỉ lệ) cùng khung = **hai thang y**, vi phạm luật chart. Phải tách hai chart.

Chi tiết và cách sửa: `docs/superpowers/specs/2026-07-30-dashboard-ui-uplift-design.md`.
