# Dashboard UI Uplift — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nâng tầng trình bày `static/index.html` từ "đúng kỹ thuật nhưng khó dùng" lên mức giao được cho CS lead / PO / dev, đạt đủ 9 tiêu chí ở spec §9.

**Architecture:** Một file `src/weekly_cs_report/static/index.html` (69 KB, inline `<style>` + `<script>`, dòng dài kiểu minified). Không thêm file runtime, không thêm dependency, không đổi backend Python. Test đi qua hai tầng đã có sẵn trong `tests/test_frontend_contract.py`: so chuỗi trên HTML thô, và hành vi JS qua harness Node (`HARNESS` + `run()` ở dòng 48-83, chạy `node -e`). Đo DOM thật là việc của Claude qua Chrome DevTools MCP, không phải của Codex.

**Tech Stack:** HTML + CSS + vanilla JS (không framework, không thư viện chart, SVG vẽ tay). Test: pytest + `node -e` harness. Kiểm màu: `node scripts/validate_palette.js`.

**Spec nguồn:** `docs/superpowers/specs/2026-07-30-dashboard-ui-uplift-design.md`. Khi plan này và spec đó lệch nhau, mục "Deviation" dưới đây thắng và nói rõ lý do.

---

## Global Constraints

Mọi task đều bị ràng buộc bởi toàn bộ mục này. Đọc lại trước mỗi task.

- **100% `<style>`/`<script>` inline.** CSP sha256 sinh từ nội dung inline ở `web.py:197`. Không asset ngoài, không CDN, không thư viện chart, không `<link>`, không `<img src>`.
- **`page.count(".style.") == 1`** — assertion đang sống ở `tests/test_frontend_contract.py:102`. Chỉ đúng một chỗ trong JS được phép chạm `.style.`: `syncStickyOffset()`. Mọi kích thước động khác phải đi qua `setAttribute` trên SVG, hoặc class, hoặc thuộc tính `value`/`max`. **Không** `element.style.width = ...`.
- **Không style attribute trong markup** — `assert not re.search(r"<[^>]+\sstyle=", page)` ở dòng 104.
- **Không `innerHTML` / `insertAdjacentHTML` / `document.write`** — dòng 93.
- **Không chuỗi `http://` hoặc `https://`** trong trang, trừ namespace SVG `http://www.w3.org/2000/svg` — dòng 91-92.
- **`page.count("Cập nhật") <= 2`** (spec §5). Hiện có đúng 3: `applyEnvelope` (dòng 99), `renderKpis` (dòng 62), `buildWeeklyExport` (dòng 69). Task 8 xoá cái ở `renderKpis` → còn 2. Không thêm chuỗi `Cập nhật` mới ở bất kỳ đâu.
- **Không đổi công thức metric, không đổi 4 định nghĩa outcome, không đổi payload `/api/dashboard` và `/api/tickets`.** Không thêm/bớt field trong envelope hay snapshot.
- **Không serialize text khách hàng, ID nội bộ Langfuse (`traceId`, `sessionId`), UserID, TransID, số điện thoại, email ra browser.** Ticket ID được phép.
- Repo đã được khởi tạo Git sau khi plan này được viết. Các step **CHECKPOINT** (chạy full suite + ghi số đo) vẫn giữ nguyên; chỉ tạo commit khi user yêu cầu, và không commit `.env`, `runtime/`, `artifacts/`, cache hoặc credential.
- **Không tuyên bố đã verify Docker.** Docker không chạy được ở môi trường này.
- `.env` mode `0600`, `runtime/` mode `0700`, snapshot `0600` — không đổi.
- Một họ chữ (`system-ui`). Tối đa 5 màu phân biệt. Thang khoảng cách 4px: `4 · 8 · 12 · 16 · 24 · 32`, không giá trị lẻ.
- **Không bao giờ mã hoá tốt/xấu bằng màu đơn độc.** Mỗi lần dùng phải kèm `▲`/`▼` + số, hoặc nhãn chữ. Lý do đo được: `#D93025` ↔ `#0F9D58` có CVD ΔE 6.1 (deutan).
- **Không bao giờ vẽ 0 cho tuần không có dữ liệu.** Trạng thái rỗng viết chữ.
- Baseline phải giữ: **687 test pass, exit 0** (`.venv/bin/pytest -q`). Số test được phép tăng. Test bị sửa phải nằm trong danh sách "Test được phép sửa" — sửa ngoài danh sách đó là lỗi plan, dừng và báo.

## Phân vai

| Ai | Làm gì |
|---|---|
| **Codex (GPT 5.6 sol)** | Implement toàn bộ task dưới đây. Chạy `.venv/bin/pytest -q`. Chạy `node scripts/validate_palette.js`. Ghi output vào report. |
| **Claude** | Đo DOM thật bằng Chrome DevTools MCP ở cuối mỗi lô (`1440x900` và emulate `390x844x3,mobile,touch`). Codex **không có** browser MCP — Codex không được tự nhận đã đo DOM, và không được viết "đã kiểm bằng mắt". |
| **PO (user)** | Chốt hai judgment call đánh dấu `[PO]` dưới đây. Không chặn: plan đã chọn mặc định, PO đổi một dòng là xong. |

## Deviation so với spec — đọc trước khi code

Ba chỗ spec đòi thứ payload hiện tại không có. Không đổi payload (ràng buộc cứng), nên plan làm khác và ghi rõ:

**D1 — Delta của thẻ WTD.** Spec §3.2: *"Nếu thẻ đang hiển thị WTD thì delta so cùng kỳ tuần trước"*. Không làm được: `views[*].weekly[]` là tổng hợp cả tuần, không có dữ liệu bán phần của tuần trước để so cùng kỳ. Thêm được thì phải đổi payload. **Plan làm:** thẻ WTD hiện delta `—` và caption `WTD chưa đủ tuần — không so sánh trực tiếp` (giữ hành vi `kpiDelta` hiện tại). Câu hỏi §5.2 thứ nhất vẫn trả lời được vì tuần hoàn chỉnh gần nhất luôn có delta.

**D2 — Đếm giây cooldown.** Spec §3.10 dòng 4: *"cooldown 429 → nút tự vô hiệu + đếm giây còn lại"*. `/api/refresh` (`web.py:171-178`) **không trả 429**; nó gọi `request_refresh(force=True)` và luôn trả 200 kèm envelope. Cooldown 60 giây là nội bộ `dashboard_cache.py:21` (`_MANUAL_REFRESH_COOLDOWN`), `next_manual_refresh_at` **không** nằm trong envelope. **Plan làm:** đếm ngược 60 giây phía client, hằng số soi chiếu server, đặt tên `REFRESH_COOLDOWN_SECONDS=60` kèm comment trỏ tới `dashboard_cache.py:21`. Giới hạn đã biết: reload trang mất đồng hồ; cooldown do đường lỗi server đặt thì client không biết. Ghi giới hạn này vào "Cách đọc".
> `[PO]` Muốn đúng như spec thì phải thêm `next_manual_refresh_at` vào envelope — đó là đổi payload API, cần PO cho phép riêng. Mặc định của plan: **không** đổi.

**D3 — Ngưỡng cảnh báo reopen.** Spec §3.2 viết *"reopen 7 ngày > trung vị..."* nhưng thẻ KPI đang hiển thị `reopen_lifetime_rate`, không phải `reopen_within_7d`. **Plan làm:** áp ngưỡng lên chính đại lượng thẻ đang hiển thị (`reopen_lifetime_rate`). Đây là ngưỡng **trình bày** (thẻ nào sáng viền), không phải công thức metric — không vi phạm "không đổi công thức metric".

Và một chỗ **spec sai, code đúng** (spec §1.4 đã tự ghi nhận): `--warn` là `#A45F00`, không phải `#F29900` như `SPEC-v2` §5.3. Giữ code.

## Bẫy đã phát hiện khi đọc code — không có trong spec

**B1 — `#3B86E8` làm vỡ contrast chữ nút primary.** Chữ trắng trên `#3B86E8` chỉ đạt **3,65:1**, dưới sàn 4,5:1 cho chữ. `.button.primary`, `.toggle button[aria-pressed=true]`, `.tab[aria-selected=true]` đều `color:#FFF`. Trong dark, chữ trên accent phải là mực `#111418` (5,07:1). Xử ở T6 bằng biến `--on-accent`.

**B2 — hai vai trò của `--warn` không được gộp.** `--warn` là nét vẽ (sàn 3:1), `--warn-text` là chữ (sàn 4,5:1). Dark: `--warn` đổi sang `#B07A2E`, `--warn-text` **giữ** `#FFD166`.

**B3 — "index trên tập đã lọc" xung đột với "không nối qua tuần rỗng".** Test dòng 890 đòi đường bị ngắt tại tuần rỗng, và đó là luật đúng. Cách thoả cả hai ở T2: x tính theo chỉ số trong tập đã lọc, nhưng flush nhóm đường khi hai tuần được vẽ không cách nhau đúng 7 ngày.

## Test được phép sửa

Ngoài danh sách này, không sửa test nào.

| Test | Task | Vì sao |
|---|---|---|
| `test_static_palette_meets_text_and_interactive_non_text_contrast` (dòng 900) | T6 | `#5675A8` bị bỏ khỏi vai trò phân loại; dark thêm `#3B86E8`/`#B07A2E` |
| `test_kpi_definitions_are_revealed_by_keyboard_focus_and_touch_activation` (dòng 486) | T9 | 4 nút định nghĩa/thẻ gộp thành 1 disclosure cho cả hàng (spec §3.2) |
| `test_reopen_warning_marks_only_completed_week_increase_above_five_points` (dòng 443) | T13 | Ngưỡng đổi từ "delta > 5 điểm so tuần trước" sang "trung vị + 5 điểm" (spec §3.2) |
| `test_reopen_warning_uses_display_rounded_threshold_and_complete_values_only` (dòng 458) | T13 | Cùng lý do |
| `test_trend_has_full_text_tooltips_and_navigation_highlight_hook` (dòng 858) | T11 | `trendChart` tách thành `trendVolumeChart` + `trendRateChart` |
| `test_trend_caption_matches_solid_ai_and_dashed_reopen_rendered_encoding` (dòng 874) | T11 | Cùng lý do |
| `test_trend_breaks_lines_at_missing_weeks_instead_of_bridging_the_gap` (dòng 890) | T11 | Cùng lý do; **invariant "không nối qua tuần rỗng" phải giữ**, chỉ đổi id |
| `REQUIRED_IDS` (dòng 15-33) | T11, T13, T14 | Bỏ `trendChart`; thêm `trendVolumeChart`, `trendRateChart`, `attentionStrip`, `firstLoadBlock`, `staleErrorLine`, `kpiDefinitionsToggle`, `kpiDefinitionsPanel` |
| `run()` hooks (dòng 79) | T13 | Thêm `renderAttentionStrip` vào `globalThis.__test` |

Cố ý **không** sửa, phải vẫn xanh nguyên trạng:
- `test_p4_dom_contract_and_security_surface` (dòng 86) — hàng rào bảo mật + `.style.` count.
- `test_p4_defers_sticky_table_headers_until_the_topbar_offset_is_measured` (dòng 179) — assert nguyên văn `html.sticky-offset-ready th{position:sticky;top:var(--sticky-offset)`. T1 thêm rule **cụ thể hơn** phía sau, không sửa rule này.
- `test_p4_responsive_sticky_shell_measures_the_topbar_and_keeps_keyboard_focus_safe` (dòng 147) — chờ `initialOffset === "91px"` từ `topbar._rect={height:91}` trong harness, không phụ thuộc CSS thật.
- `test_mobile_table_has_exactly_six_default_columns_and_quality_marks_stale_data` (dòng 844) — `mobileColumns=new Set([0,1,3,7,9,12])` không đổi.
- Toàn bộ `test_p5_*` (Ticket Explorer, 22 field, CSV 1.000 dòng).

## File Structure

| File | Trách nhiệm | Thay đổi |
|---|---|---|
| `src/weekly_cs_report/static/index.html` | Toàn bộ tầng trình bày | Sửa ở mọi task |
| `tests/test_frontend_contract.py` | Hợp đồng chuỗi + hành vi JS | Thêm test mới; sửa 9 mục trong bảng trên |
| `scripts/validate_palette.js` | Validator màu (dev-only, không phải runtime dep) | **Tạo mới** ở T0 |
| `docs/superpowers/reports/2026-07-30-ui-uplift-report.md` | Nhật ký số đo từng lô | **Tạo mới** ở T0, append mỗi lô |

Không tạo file HTML/CSS/JS nào khác. Không tách `index.html` — tách là phá CSP hash.

---

## Task 0: Dựng công cụ kiểm chứng

**Files:**
- Create: `scripts/validate_palette.js`
- Create: `docs/superpowers/reports/2026-07-30-ui-uplift-report.md`

**Interfaces:**
- Consumes: không.
- Produces: lệnh `node scripts/validate_palette.js` (cú pháp lấy từ `--help`) in kết quả 5 tiêu chí; file report để mọi task sau append.

Validator gốc nằm trong skill `dataviz`, đường dẫn theo session nên không bền. Copy vào repo để mọi lần chạy sau tái lập được. Spec §1.4 đã tham chiếu `node scripts/validate_palette.js` như thể nó ở repo.

- [ ] **Step 1: Tìm validator gốc**

```bash
find / -name "validate_palette.js" -not -path "*/node_modules/*" 2>/dev/null | head -1
```
Kỳ vọng: một đường dẫn dưới `bundled-skills/.../dataviz/scripts/validate_palette.js`. Không tìm thấy thì **dừng và báo** — không tự viết validator, tự viết là phán màu bằng mắt kiểu khác.

- [ ] **Step 2: Copy vào repo**

```bash
mkdir -p scripts
cp "<đường dẫn tìm được>" scripts/validate_palette.js
```

- [ ] **Step 3: Chạy trên hai cặp màu đã chốt, lưu output**

```bash
node scripts/validate_palette.js --help
```
Đọc `--help` lấy đúng cú pháp, rồi chạy:
- sáng: `#0068FF`, `#A45F00`, surface `#fcfcfb`
- tối: `#3B86E8`, `#B07A2E`, surface `#1a1a19`

Kỳ vọng: cả hai PASS 5/5 (spec §1.4 đã đo). Không PASS thì **dừng**, dán output, chờ quyết — không tự đổi màu.

- [ ] **Step 4: Tạo file report với baseline**

```markdown
# Report — UI uplift

## Baseline trước khi sửa (đo 2026-07-30, Chrome DevTools MCP)

| Chỉ số | 1440x900 | 390x844x3 mobile+touch |
|---|---|---|
| stickyHeight | 132px | 276px |
| tapTargetsUnder44 | — | 31 |
| pageOverflowX | false | false |
| thOffsetFromWrapTop | 134px | 134px |
| trendFirstBarX | dồn 1/3 phải | — |
| chiều cao trang | 4.972px | 6.638px |

Test: 687 pass, exit 0.

## Palette validator — cặp đã chốt

<dán output Step 3>

## Lô 1
<append sau khi xong>
```

- [ ] **Step 5: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: 687 pass, exit 0 (T0 không chạm code chạy được).

---

# LÔ 1 — Ba lỗi bố cục

Mục tiêu lô: `thOffsetFromWrapTop === 0`, chart không còn dồn phải, bảng tuần không mở đầu bằng 8 dòng rỗng. Không chạm palette, không chạm thang chữ.

## Task 1: `th` sticky trong container cuộn

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:9` (`:root`), `:10` (rule `th`)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: biến CSS `--sticky-offset` (giữ nguyên, do `syncStickyOffset()` đặt).
- Produces: biến CSS `--table-sticky-top` = `0`, hằng số **tĩnh trong CSS**, không do JS đặt. Task sau không được viết JS đặt biến này (`.style.` count).

Nguyên nhân đo được: `.weekly-table-scroll` và `.explorer-table` có `overflow-x:auto` nên là scroll container. `th{top:var(--sticky-offset)}` = 133px làm header nằm cách mép trên bảng 134px. Trong scroll container phải `top:0`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_frontend_contract.py`:

```python
def test_sticky_table_headers_pin_to_zero_inside_scroll_containers():
    """th sticky trong container overflow:auto phải top:0; offset của trang đẩy header vào giữa bảng."""
    page = page_text()
    assert "--table-sticky-top:0" in page
    assert "html.sticky-offset-ready th{position:sticky;top:var(--sticky-offset)" in page
    assert re.search(
        r"html\.sticky-offset-ready \.weekly-table-scroll th,"
        r"html\.sticky-offset-ready \.explorer-table th\{top:var\(--table-sticky-top\)\}",
        page,
    )
    assert page.count(".style.") == 1
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py::test_sticky_table_headers_pin_to_zero_inside_scroll_containers
```
Kỳ vọng: FAIL ở `assert "--table-sticky-top:0" in page`.

- [ ] **Step 3: Thêm biến vào `:root`**

Ở dòng 9, đổi cuối khối `:root`:

từ `--radius:6px;--sticky-offset:0px}`
thành `--radius:6px;--sticky-offset:0px;--table-sticky-top:0}`

- [ ] **Step 4: Thêm rule cụ thể hơn ngay sau rule sticky hiện có**

Ở dòng 10, tìm nguyên văn:

```css
html.sticky-offset-ready th{position:sticky;top:var(--sticky-offset)}
```

đổi thành:

```css
html.sticky-offset-ready th{position:sticky;top:var(--sticky-offset)}html.sticky-offset-ready .weekly-table-scroll th,html.sticky-offset-ready .explorer-table th{top:var(--table-sticky-top)}
```

Rule cũ **giữ nguyên nguyên văn** — `test_p4_defers_sticky_table_headers...` so chuỗi trên nó.

- [ ] **Step 5: Chạy test, phải PASS**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: cả file xanh, kể cả `test_p4_defers_sticky_table_headers...` và `test_p4_dom_contract_and_security_surface`.

- [ ] **Step 6: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥688 pass, exit 0.

---

## Task 2: Chart chỉ vẽ tuần có dữ liệu, giữ nguyên luật không nối qua tuần rỗng

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:70` (`renderTrend`)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: `rows(view)` — mảng weekly, mỗi item có `cohort_week` (`YYYY-MM-DD`), `cohort_status` (`complete`|`wtd`), `has_data`, `total_tickets`, `ai_first_rate`, `reopen_lifetime_rate`.
- Produces: `isConsecutiveCohortWeek(previousWeek, currentWeek) -> boolean` (dùng lại ở T7 và T11); `renderTrend(weekly)` giữ y nguyên tên, giữ `data-week`, `role="button"`, `tabindex="0"`, `aria-label` trên mỗi cột.

Xem B3 ở đầu plan. Không được bỏ `flush()`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_trend_places_first_data_week_at_the_left_edge_and_scales_to_render_box():
    """8 tuần rỗng đứng đầu từng đẩy 5 cột dữ liệu về 1/3 phải; preserveAspectRatio=none giãn ngang 4,3x."""
    page = page_text()
    assert 'preserveAspectRatio="none"' not in page
    assert 'preserveAspectRatio","xMidYMid meet"' in page

    observed = run(page, r"""
const empty=[4,11,18,25].map(day=>({cohort_week:`2026-05-${String(day).padStart(2,"0")}`,has_data:false,total_tickets:0}));
const full=(date)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_rate:.8,reopen_lifetime_rate:.2});
globalThis.__test.renderTrend([...empty,full("2026-06-01"),full("2026-06-08"),full("2026-06-15")]);
const bars=document.getElementById("trendChart").children.filter(node=>node.tagName==="rect");
process.stdout.write(JSON.stringify({count:bars.length,firstX:Number(bars[0].getAttribute("x")),lastX:Number(bars.at(-1).getAttribute("x"))}));
""")
    assert observed["count"] == 3, "chỉ vẽ tuần có dữ liệu"
    assert observed["firstX"] <= 32, "cột đầu phải ở 1/10 đầu của viewBox rộng 320"
    assert observed["lastX"] >= 280, "cột cuối phải gần mép phải"


def test_trend_still_refuses_to_bridge_a_missing_week_after_filtering():
    """Bỏ tuần rỗng khỏi trục x không được biến hai tuần cách nhau thành liền mạch."""
    observed = run(page_text(), r"""
const full=(date)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_rate:.8,reopen_lifetime_rate:.2});
globalThis.__test.renderTrend([full("2026-07-06"),{cohort_week:"2026-07-13",has_data:false,total_tickets:0},full("2026-07-20")]);
const svg=document.getElementById("trendChart");
process.stdout.write(JSON.stringify({polylines:svg.children.filter(node=>node.tagName==="polyline").length}));
""")
    assert observed["polylines"] == 4
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "trend_places_first_data_week or trend_still_refuses"
```
Kỳ vọng: test thứ nhất FAIL ở `preserveAspectRatio="none" not in page`. Test thứ hai PASS ngay (hành vi hiện tại đã đúng) — nó là **canary chống hồi quy**, phải vẫn PASS sau Step 3.

- [ ] **Step 3: Thay `renderTrend`**

Thay toàn bộ dòng 70 bằng:

```javascript
      function isConsecutiveCohortWeek(previous,current){if(!previous||!current)return false;const a=new Date(`${previous}T00:00:00Z`),b=new Date(`${current}T00:00:00Z`);return b.getTime()-a.getTime()===604800000}
      function renderTrend(weekly){const svg=$("trendChart"),empty=$("trendEmpty"),source=weekly||[],data=source.filter(item=>item&&item.has_data!==false&&Number(item.total_tickets)>0);clear(svg);svg.setAttribute("viewBox","0 0 320 160");svg.setAttribute("preserveAspectRatio","xMidYMid meet");empty.hidden=Boolean(data.length);if(!data.length){empty.hidden=false;return}const max=Math.max(...data.map(x=>Number(x.total_tickets))),aiGroups=[],reopenGroups=[];let ai=[],reopen=[],previousWeek=null;const flush=()=>{if(ai.length){aiGroups.push(ai);ai=[]}if(reopen.length){reopenGroups.push(reopen);reopen=[]}};data.forEach((item,index)=>{if(previousWeek&&!isConsecutiveCohortWeek(previousWeek,item.cohort_week))flush();previousWeek=item.cohort_week;const x=24+index*(272/Math.max(data.length-1,1)),height=116*Number(item.total_tickets)/max,label=`Tuần ${dateRange(item.cohort_week)}: ${number(item.total_tickets)} ticket · AI First ${percent(item.ai_first_rate)} · Reopen ${percent(item.reopen_lifetime_rate)}`,activate=()=>setWeekFilter(item.cohort_week,true),bar=svgElement("rect",null,item.cohort_status==="wtd"?"bar wtd-bar":"bar");bar.setAttribute("x",x-7);bar.setAttribute("y",145-height);bar.setAttribute("width","14");bar.setAttribute("height",height);bar.setAttribute("role","button");bar.setAttribute("tabindex","0");bar.setAttribute("data-week",item.cohort_week);bar.setAttribute("aria-label",`${label}. Nhấn Enter để lọc tuần này.`);bar.appendChild(svgElement("title",label));bar.addEventListener("click",activate);bar.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();activate()}});svg.appendChild(bar);ai.push(`${x},${145-108*Number(item.ai_first_rate||0)}`);if(item.reopen_lifetime_rate==null){if(reopen.length){reopenGroups.push(reopen);reopen=[]}}else reopen.push(`${x},${145-108*Number(item.reopen_lifetime_rate)}`)});flush();[["line-ai",aiGroups],["line-reopen",reopenGroups]].forEach(([klass,groups])=>groups.forEach(points=>{const path=svgElement("polyline",null,klass);path.setAttribute("points",points.join(" "));if(klass==="line-reopen")path.setAttribute("stroke-dasharray","6 4");svg.appendChild(path)}));const volumeLabel=svgElement("text","Cột: tổng ticket","axis-label"),rateLabel=svgElement("text","Đường: tỷ lệ","axis-label");volumeLabel.setAttribute("x","4");volumeLabel.setAttribute("y","10");rateLabel.setAttribute("x","232");rateLabel.setAttribute("y","10");svg.append(volumeLabel,rateLabel);setText("trendCaption",`Có ${number(data.length)} tuần có dữ liệu. Cột là tổng ticket, đường liền xanh là AI First, đường đứt vàng là reopen; WTD có viền đứt. Tuần không có dữ liệu bị bỏ khỏi trục và đường bị ngắt tại đó. Click hoặc Enter trên cột để lọc.`)}
```

Bốn thay đổi so với bản cũ, đúng bốn thứ này:
1. `source.forEach` → `data.forEach`, `source.length` → `data.length`, hệ số ngang `288` → `272` (chừa chỗ cho nhãn `Đường: tỷ lệ` ở `x=232`, hết cảnh `<text>` tràn hộp đo được `scrollWidth 179 / clientWidth 36`).
2. `preserveAspectRatio` `none` → `xMidYMid meet`.
3. `flush()` chuyển từ "khi gặp item rỗng" sang "khi hai tuần được vẽ không cách nhau đúng 604800000 ms".
4. Caption thêm câu giải thích tuần rỗng bị bỏ khỏi trục.

- [ ] **Step 4: Chạy test trend**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k trend
```
Kỳ vọng: tất cả xanh, kể cả `test_trend_has_full_text_tooltips_and_navigation_highlight_hook` (viewBox vẫn `0 0 320 160`) và `test_trend_caption_matches_solid_ai_and_dashed_reopen_rendered_encoding` (caption vẫn chứa `đường liền xanh là AI First` và `đường đứt vàng là reopen`).

- [ ] **Step 5: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥690 pass, exit 0.

---

## Task 3: Gộp các tuần rỗng thành một dòng mở được

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:41` (`state`), `:68` (`renderWeeklyTable`), `:11` (CSS)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: `weeklyValues(item)` (không sửa), `dateRange(week)`.
- Produces: `state.emptyWeeksExpanded: boolean` (mặc định `false`); `weeklyDataRow(item) -> <tr>`; `emptyWeekGroups(weekly) -> Array<item | item[]>`; dòng gộp là `<tr class="empty-row empty-group">` chứa một `<button class="empty-group-toggle">`.

Yêu cầu: các tuần `has_data === false` **liền kề nhau** gộp thành một dòng `N tuần không có dữ liệu (dd/mm – dd/mm)`, bấm để mở. Gộp theo cụm liền kề, không gộp toàn bảng — tuần rỗng nằm giữa dữ liệu phải giữ đúng vị trí thời gian. Cụm chỉ một tuần thì không gộp.

- [ ] **Step 1: Viết test thất bại**

```python
def test_weekly_table_collapses_a_run_of_empty_weeks_into_one_row():
    """Bảng tuần từng mở đầu bằng 8 dòng 'Không có dữ liệu' trước dữ liệu thật."""
    observed = run(page_text(), r"""
const empty=(date)=>({cohort_week:date,has_data:false,total_tickets:0});
const full=(date)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:5,ai_then_cs_count:3,direct_cs_count:2,reopen_lifetime_numerator:1,reopen_lifetime_rate:.1,ai_reply_mean_ai_first:1.5,gt4_turn_with_cs:0,gt4_turn_without_cs:0,unclassified_count:0});
const weekly=[empty("2026-05-04"),empty("2026-05-11"),empty("2026-05-18"),full("2026-05-25"),full("2026-06-01")];
globalThis.__test.renderWeeklyTable(weekly);
const body=document.getElementById("weeklyRows");
const collapsed=body.children.map(row=>row.className);
const toggle=body.children.find(row=>row.className.includes("empty-group")).children[0].children[0];
const collapsedText=toggle.textContent;
toggle.dispatchEvent({type:"click"});
const expanded=document.getElementById("weeklyRows").children.map(row=>row.className);
process.stdout.write(JSON.stringify({collapsed,collapsedText,expanded}));
""")
    assert len(observed["collapsed"]) == 3, "3 tuần rỗng + 2 tuần dữ liệu -> 1 dòng gộp + 2 dòng"
    assert observed["collapsed"][0] == "empty-row empty-group"
    assert "3 tuần không có dữ liệu" in observed["collapsedText"]
    assert "04/05" in observed["collapsedText"]
    assert len(observed["expanded"]) == 5, "mở ra thì hiện đủ 5 dòng"


def test_weekly_table_keeps_an_interior_empty_week_in_place():
    """Tuần rỗng nằm giữa dữ liệu không được gộp lên đầu — thứ tự thời gian là thông tin."""
    observed = run(page_text(), r"""
const empty=(date)=>({cohort_week:date,has_data:false,total_tickets:0});
const full=(date)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:5,ai_then_cs_count:3,direct_cs_count:2,reopen_lifetime_numerator:1,reopen_lifetime_rate:.1,ai_reply_mean_ai_first:1.5,gt4_turn_with_cs:0,gt4_turn_without_cs:0,unclassified_count:0});
globalThis.__test.renderWeeklyTable([full("2026-06-01"),empty("2026-06-08"),full("2026-06-15")]);
const rows=document.getElementById("weeklyRows").children;
process.stdout.write(JSON.stringify({classes:rows.map(row=>row.className),second:rows[1].textContent}));
""")
    assert observed["classes"] == ["", "empty-row", ""], "cụm một tuần thì không gộp"
    assert "Không có dữ liệu" in observed["second"]
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "collapses_a_run_of_empty or interior_empty_week"
```
Kỳ vọng: FAIL — hiện tại `collapsed` có 5 phần tử.

- [ ] **Step 3: Thêm state**

Ở dòng 41, trong object `state`, sau `showFull:false,` thêm `emptyWeeksExpanded:false,`.

- [ ] **Step 4: Thay `renderWeeklyTable`**

Thay toàn bộ dòng 68 bằng:

```javascript
      function weeklyDataRow(item){const tr=element("tr",null,item.cohort_status==="wtd"?"wtd":"");if(item.has_data===false)tr.className="empty-row";weeklyValues(item).forEach((value,index)=>{const cell=element("td",value,mobileColumns.has(index)?"":"compact-hide");if(index===9&&item.has_data!==false&&item.reopen_lifetime_rate==null)cell.setAttribute("title","Cần 7 ngày sau tuần cohort");tr.appendChild(cell)});return tr}
      function emptyWeekGroups(weekly){const groups=[];let run=[];(weekly||[]).forEach(item=>{if(item&&item.has_data===false){run.push(item);return}if(run.length){groups.push(run);run=[]}groups.push(item)});if(run.length)groups.push(run);return groups}
      function renderWeeklyTable(weekly){const target=$("weeklyRows");clear(target);emptyWeekGroups(weekly).forEach(entry=>{if(!Array.isArray(entry)){target.appendChild(weeklyDataRow(entry));return}if(entry.length<2||state.emptyWeeksExpanded){entry.forEach(item=>target.appendChild(weeklyDataRow(item)));return}const tr=element("tr",null,"empty-row empty-group"),td=element("td"),toggle=element("button",`${number(entry.length)} tuần không có dữ liệu (${dateRange(entry[0].cohort_week).split(" – ")[0]} – ${dateRange(entry.at(-1).cohort_week).split(" – ").at(-1)}) · bấm để mở`,"empty-group-toggle");toggle.type="button";toggle.setAttribute("aria-expanded","false");toggle.addEventListener("click",()=>{state.emptyWeeksExpanded=true;renderWeeklyTable(weekly)});td.setAttribute("colspan","14");td.appendChild(toggle);tr.appendChild(td);target.appendChild(tr)});if(!(weekly||[]).length){const tr=element("tr",null,"empty-row");const td=element("td","Không có dữ liệu trong tuần này");td.setAttribute("colspan","14");tr.appendChild(td);target.appendChild(tr)}}
```

`emptyWeeksExpanded` một chiều (mở rồi không thu lại) — cố ý, giữ đơn giản; nó không mang nghĩa lọc nên không cần reset ở `resetFilters`.

- [ ] **Step 5: Thêm CSS**

Ở dòng 11 (khối CSS phụ), thêm vào cuối:

```css
.empty-group-toggle{border:0;padding:0;color:var(--muted);background:transparent;font:inherit;text-align:left;text-decoration:underline}
```

- [ ] **Step 6: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh, kể cả `test_p4_dom_contract_and_security_surface` (`.style.` vẫn 1) và `test_weekly_renderer_keeps_wtd_and_no_data_as_text_not_zeroes` (dòng 603).

- [ ] **Step 7: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥692 pass, exit 0.

---

## Task 4: Ghim cột Tuần + gợi ý còn nội dung khi cuộn ngang

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:11` (CSS)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: `--table-sticky-top` từ T1.
- Produces: không có API JS mới. Thuần CSS — `.style.` count đã kín.

Đo được: `#weeklyTableScroll` `scrollWidth 1770 / clientWidth 1390` ở khung 1440 → cột 14 bị cắt và không có dấu hiệu nào cho biết còn nội dung.

- [ ] **Step 1: Viết test thất bại**

```python
def test_first_table_column_is_pinned_and_scroll_has_a_visible_hint():
    """Cuộn ngang mất nhãn tuần thì mọi ô số còn lại vô nghĩa."""
    page = page_text()
    assert re.search(r"\.weekly-table-scroll th:first-child[^{]*\{[^}]*position:sticky", page)
    assert re.search(r"\.weekly-table-scroll th:first-child[^{]*\{[^}]*left:0", page)
    assert re.search(r"\.explorer-table th:first-child", page)
    assert "background-attachment:local,local,scroll,scroll" in page
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py::test_first_table_column_is_pinned_and_scroll_has_a_visible_hint
```
Kỳ vọng: FAIL ở regex đầu.

- [ ] **Step 3: Thêm CSS**

Ở dòng 11, thêm vào cuối:

```css
.weekly-table-scroll th:first-child,.explorer-table th:first-child,.weekly-table-scroll td:first-child,.explorer-table td:first-child{position:sticky;left:0;z-index:3;border-right:1px solid var(--line);background:var(--paper)}.weekly-table-scroll th:first-child,.explorer-table th:first-child{z-index:4;background:var(--subtle)}.weekly-table-scroll,.explorer-table{background-image:linear-gradient(to right,var(--paper),transparent 12px),linear-gradient(to left,var(--paper),transparent 12px),linear-gradient(to right,rgba(17,20,24,.16),transparent 12px),linear-gradient(to left,rgba(17,20,24,.16),transparent 12px);background-repeat:no-repeat;background-size:32px 100%,32px 100%,12px 100%,12px 100%;background-position:0 0,100% 0,0 0,100% 0;background-attachment:local,local,scroll,scroll}
```

Kỹ thuật gợi ý cuộn: hai lớp `local` (cuộn cùng nội dung, che) + hai lớp `scroll` (đứng yên, là bóng mờ). Cuộn hết một bên thì lớp `local` che đúng lớp bóng bên đó → bóng tự tắt. Không JS, không listener.

Hàng zebra `tbody tr:nth-child(even){background:#FAFBFC}` bị ô ghim `background:var(--paper)` phủ ở cột đầu. Chấp nhận: cột đầu là nhãn, 13 cột còn lại vẫn zebra để dò dòng.

- [ ] **Step 4: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh. `rgba(` không phạm luật nào; không có `http`.

- [ ] **Step 5: CHECKPOINT LÔ 1**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥693 pass, exit 0.

**Rồi DỪNG và báo Claude đo DOM.** Claude chạy ở `1440x900` và emulate `390x844x3,mobile,touch`, append vào report:

```js
(() => {
  const wrap = document.getElementById("weeklyTableScroll");
  const th = wrap.querySelector("th");
  const bar = document.getElementById("trendChart").querySelector("rect");
  return {
    thOffsetFromWrapTop: Math.round(th.getBoundingClientRect().top - wrap.getBoundingClientRect().top),
    trendFirstBarX: bar ? Number(bar.getAttribute("x")) : null,
    weeklyRowCount: document.getElementById("weeklyRows").children.length,
    pageOverflowX: document.documentElement.scrollWidth > window.innerWidth,
    stickyHeight: Math.ceil(document.querySelector(".topbar").getBoundingClientRect().height)
  };
})()
```

Ngưỡng lô 1: `thOffsetFromWrapTop === 0` · `trendFirstBarX <= 32` (đơn vị viewBox) · `pageOverflowX === false`. `stickyHeight` chưa cần đạt (Lô 4).

---

# LÔ 2 — Token thiết kế và thẻ KPI

## Task 5: Thang chữ 4 bậc và `--content-max`

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:9-11` (CSS)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Produces: biến CSS `--gutter:24px`, `--content-max:1120px`, `--table-max:100%`. Bốn bậc chữ: `display` / `metric` / `body` / `caption`. Bậc dưới 12px bị xoá hoàn toàn.

Nguyên nhân "khó nhìn": `11px` ở `.kpi-note`, `.eyebrow`, `.kpi-delta`, `.definition-control`, `th`; `9px` ở `.axis-label`. `.rank-row` cột nhãn `1066px` để trống ~1.000px giữa nhãn và số.

- [ ] **Step 1: Viết test thất bại**

```python
def test_type_scale_has_no_step_below_twelve_pixels_and_content_is_width_capped():
    """11px và 9px là nguyên nhân chính của 'tối giản đến mức khó nhìn'."""
    page = page_text()
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    sizes = {int(value) for value in re.findall(r"font-size:(\d+)px", style)}
    assert sizes and min(sizes) >= 12, f"còn bậc chữ dưới 12px: {sorted(sizes)}"
    assert "--content-max:1120px" in page
    assert "--gutter:24px" in page
    assert re.search(r"\.rank-row\{[^}]*grid-template-columns:minmax\(0,1fr\) 200px", page)
    assert re.search(r"\.kpi-value\{[^}]*font-size:28px", page)
    assert re.search(r"\.kpi-value\{[^}]*font-variant-numeric:tabular-nums", page)
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py::test_type_scale_has_no_step_below_twelve_pixels_and_content_is_width_capped
```
Kỳ vọng: FAIL, `min(sizes)` là `9` (`.axis-label`).

- [ ] **Step 3: Thêm ba biến bố cục vào `:root`**

Ở dòng 9, đổi cuối khối `:root`:

từ `--sticky-offset:0px;--table-sticky-top:0}`
thành `--sticky-offset:0px;--table-sticky-top:0;--gutter:24px;--content-max:1120px;--table-max:100%}`

- [ ] **Step 4: Nâng mọi bậc chữ dưới 12px lên 12px**

Ở dòng 10, đổi giá trị, không đổi selector:

| Selector | Từ | Thành |
|---|---|---|
| `.eyebrow` | `font-size:11px` | `font-size:12px` |
| `.kpi-delta` | `font-size:11px` | `font-size:12px` |
| `.kpi-note` | `font-size:11px` | `font-size:12px` |
| `.definition-control` | `font-size:11px` | `font-size:12px` |
| `th` | `font-size:11px` | `font-size:12px` |
| `.axis-label` | `font-size:9px` | `font-size:12px` |

`.axis-label` từ 9px lên 12px trong `viewBox` rộng 320: nhãn `Cột: tổng ticket` khoảng 90 đơn vị — vẫn trong `x=4..232`. Kiểm lại ở T11 khi tách chart.

- [ ] **Step 5: Đặt `.kpi-value` về bậc `metric` và `.rank-row` về cột cố định**

Ở dòng 10:

- `.kpi-value{margin-top:1px;font-size:22px;font-weight:750;font-variant-numeric:tabular-nums;letter-spacing:-.04em}` → `.kpi-value{margin-top:4px;font-size:28px;font-weight:750;font-variant-numeric:tabular-nums;letter-spacing:-.03em}`
- `.rank-row{display:grid;grid-template-columns:minmax(0,1fr) 80px 72px 150px;gap:8px;align-items:center;padding:7px 0;border-bottom:1px solid var(--line);text-align:right}` → `.rank-row{display:grid;grid-template-columns:minmax(0,1fr) 200px 80px 72px 150px;gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line);text-align:right}`

Cột `200px` mới là chỗ cho bar SVG ở T10. Bước này chỉ cắt khoảng trống 1.000px.

- [ ] **Step 6: Giới hạn bề rộng khối chữ**

Ở dòng 11, thêm vào cuối:

```css
.narrative,.diagnostic-list,#segmentList,.quality-lines,#howToReadPanel{max-width:var(--content-max)}.weekly-table-scroll,.explorer-table{max-width:var(--table-max)}
```

Ở dòng 10 xoá `max-width:980px` trong `.narrative` (còn `.narrative{margin:5px 0;color:var(--ink)}`) để không có hai nguồn sự thật về bề rộng.

- [ ] **Step 7: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh.

- [ ] **Step 8: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥694 pass, exit 0.

---

## Task 6: Palette §2.4 — bỏ `#5675A8`, sửa dark accent, sửa chữ nút primary dark

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:9-10` (CSS)
- Modify: `tests/test_frontend_contract.py:900-921`
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Produces: `--accent` sáng `#0068FF` / tối `#3B86E8`; `--warn` sáng `#A45F00` / tối `#B07A2E`; `--volume` đổi từ hex cố định sang `color-mix(in srgb,var(--accent) 72%,transparent)`; biến mới `--on-accent` (chữ đặt trên nền accent).

Xem B1 và B2 ở đầu plan. `#5675A8` FAIL chroma `0.087` < sàn `0.1` → mắt đọc thành xám, bị bỏ khỏi vai trò phân loại. Cột volume đứng một mình trong chart riêng (T11) nên không cần màu phân loại.

- [ ] **Step 1: Viết test thất bại**

```python
def test_palette_drops_the_failing_chroma_swatch_and_fixes_dark_accent_text():
    """#5675A8 chroma 0.087 < sàn 0.1: mắt đọc thành xám. Chữ trắng trên #3B86E8 chỉ 3,65:1."""
    page = page_text()
    assert "#5675A8" not in page, "màu FAIL chroma không được còn vai trò phân loại"
    assert "#3B86E8" in page and "#B07A2E" in page, "cặp dark đã qua validator"
    assert "--on-accent" in page
    assert re.search(r"\.button\.primary[^{]*\{[^}]*color:var\(--on-accent\)", page)
    assert re.search(r"prefers-color-scheme:dark\)\{:root\{[^}]*--accent:#3B86E8", page)
    assert re.search(r"prefers-color-scheme:dark\)\{:root\{[^}]*--on-accent:#111418", page)
    assert "#F29900" not in page, "SPEC-v2 §5.3 ghi #F29900 nhưng validator WARN contrast 2.19"
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py::test_palette_drops_the_failing_chroma_swatch_and_fixes_dark_accent_text
```
Kỳ vọng: FAIL ở `"#5675A8" not in page`.

- [ ] **Step 3: Sửa `:root` sáng**

Ở dòng 9:

từ `--accent:#0068FF;--volume:#5675A8;--good:#0F9D58;`
thành `--accent:#0068FF;--on-accent:#FFF;--volume:color-mix(in srgb,var(--accent) 72%,transparent);--good:#0F9D58;`

- [ ] **Step 4: Sửa khối dark**

Ở dòng 10, trong `@media (prefers-color-scheme:dark){:root{...}}`:

từ `--muted:#B8BEC7;--volume:#7C8794;--good-text:#5DDB93;--bad:#FF8A80;--warn:#FFD166;--warn-text:#FFD166}`
thành `--muted:#B8BEC7;--accent:#3B86E8;--on-accent:#111418;--good-text:#5DDB93;--bad:#FF8A80;--warn:#B07A2E;--warn-text:#FFD166}`

Bốn điểm:
- `--volume` bỏ khỏi khối dark: nó đã suy ra từ `--accent` qua `color-mix`, tự theo dark.
- `--good-text:#5DDB93` và `--bad:#FF8A80` giữ (đã đạt 4,5:1 trên `#111418`).
- `--warn` (nét vẽ, sàn 3:1) đổi `#FFD166` → `#B07A2E`.
- `--warn-text` (chữ, sàn 4,5:1) **giữ** `#FFD166`. Hai vai trò khác nhau, đừng gộp.

- [ ] **Step 5: Dùng `--on-accent` ở mọi chỗ chữ đặt trên accent**

Ở dòng 10:

- `.button.primary,.toggle button[aria-pressed="true"],.tab[aria-selected="true"]{border-color:var(--accent);color:#FFF;background:var(--accent)}` → `...color:var(--on-accent);background:var(--accent)}`
- `.skip-link{...color:#FFF;background:var(--accent);...}` → `color:var(--on-accent)`

- [ ] **Step 6: Cập nhật test contrast**

Trong `test_static_palette_meets_text_and_interactive_non_text_contrast`, thay hai vòng lặp bằng:

```python
    for foreground, background in (
        ("#111418", "#FFFFFF"), ("#5F6368", "#FFFFFF"), ("#087F47", "#FFFFFF"),
        ("#D93025", "#FFFFFF"), ("#8A5A00", "#FFFFFF"), ("#FFFFFF", "#0068FF"),
        ("#E9EAEE", "#111418"), ("#B8BEC7", "#111418"), ("#5DDB93", "#111418"),
        ("#FF8A80", "#111418"), ("#FFD166", "#111418"), ("#111418", "#3B86E8"),
    ):
        assert ratio(foreground, background) >= 4.5
    for foreground, background in (
        ("#767676", "#FFFFFF"), ("#A45F00", "#FFFFFF"),
        ("#7C8794", "#111418"), ("#FFD166", "#111418"),
        ("#B07A2E", "#111418"), ("#3B86E8", "#111418"),
    ):
        assert ratio(foreground, background) >= 3
```

Đổi so với bản cũ: nhóm ≥4.5 thêm `("#111418","#3B86E8")`; nhóm ≥3 bỏ `("#5675A8","#FFFFFF")`, thêm `("#B07A2E","#111418")` và `("#3B86E8","#111418")`.

- [ ] **Step 7: Chạy validator, dán output vào report**

```bash
node scripts/validate_palette.js "#0068FF,#A45F00" --surface "#fcfcfb"
node scripts/validate_palette.js "#3B86E8,#B07A2E" --surface "#1a1a19"
```
(Cú pháp thật lấy từ `--help` ở T0.) Cả hai phải PASS 5/5. Không PASS thì dừng, dán output, chờ quyết.

- [ ] **Step 8: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh. `test_p4_dom_contract_and_security_surface` dòng 96 vẫn đòi `#0068FF`, `#111418`, `#E3E6EA`, `#F7F8FA` có mặt — cả bốn vẫn còn.

- [ ] **Step 9: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥695 pass, exit 0.

---

## Task 7: Sparkline 13 tuần trong thẻ KPI

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:62` (`renderKpis`), `:11` (CSS)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: `rows(view)`, `isConsecutiveCohortWeek` (T2).
- Produces: `sparklineSeries(weekly, field) -> number[][]` (nhóm liên tục, nhóm dưới 2 điểm bị bỏ); `sparkline(weekly, field) -> SVGElement|null` — `<svg class="kpi-sparkline">` chứa một `<polyline class="spark-line">` mỗi nhóm; không nhóm nào thì trả `null`.

**Không được vẽ 0 cho tuần rỗng** (§5.3) — chỉ nối các tuần có dữ liệu, và như T2, ngắt tại tuần không liền kề. Không listener trên từng điểm (rủi ro hiệu năng spec §8). **Không** dùng `preserveAspectRatio="none"` — assertion `'preserveAspectRatio="none"' not in page` quét cả trang.

- [ ] **Step 1: Viết test thất bại**

```python
def test_kpi_sparkline_skips_empty_weeks_and_breaks_at_gaps():
    """Vẽ 0 cho tuần không có dữ liệu là bịa số; nối qua khoảng trống cũng vậy."""
    page = page_text()
    assert 'class="kpi-sparkline"' in page or '"kpi-sparkline"' in page

    observed = run(page, r"""
const full=(date,ai)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:ai,reopen_lifetime_rate:.1,gt4_turn_without_cs:0});
globalThis.__test.setSnapshot({generated_at:"2026-07-30T10:00:00Z"});
globalThis.__test.renderKpis({weekly:[full("2026-06-01",.5),{cohort_week:"2026-06-08",has_data:false,total_tickets:0},full("2026-06-15",.7),full("2026-06-22",.8)],rule_gt4:{gt4_turn_without_cs:0},ai_first:{rate:.8,count:8},totals:{eligible_ticket_count:30}});
const card=document.getElementById("kpiGrid").children[0];
const spark=card.children.find(node=>node.getAttribute("class")==="kpi-sparkline");
process.stdout.write(JSON.stringify({exists:Boolean(spark),polylines:spark?spark.children.filter(n=>n.tagName==="polyline").length:0,points:spark?spark.children.filter(n=>n.tagName==="polyline").map(n=>n.getAttribute("points")):[]}));
""")
    assert observed["exists"] is True
    assert observed["polylines"] == 1, "3 tuần dữ liệu với 1 khoảng trống -> nhóm 1 điểm bị bỏ, còn 1 nhóm"
    assert all("," in value for value in observed["points"])


def test_kpi_sparkline_absent_when_fewer_than_two_data_weeks():
    """Một điểm không phải xu hướng — vẽ ra là gợi ý sai."""
    observed = run(page_text(), r"""
globalThis.__test.setSnapshot({generated_at:"2026-07-30T10:00:00Z"});
globalThis.__test.renderKpis({weekly:[{cohort_week:"2026-06-22",cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,reopen_lifetime_rate:.1,gt4_turn_without_cs:0}],rule_gt4:{gt4_turn_without_cs:0},ai_first:{rate:.8,count:8},totals:{eligible_ticket_count:10}});
const cards=document.getElementById("kpiGrid").children;
process.stdout.write(JSON.stringify({sparklines:cards.map(card=>card.children.filter(node=>node.getAttribute("class")==="kpi-sparkline").length)}));
""")
    assert observed["sparklines"] == [0, 0, 0, 0]
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k kpi_sparkline
```
Kỳ vọng: FAIL ở assertion `"kpi-sparkline"`.

- [ ] **Step 3: Thêm hai hàm ngay trước `renderKpis`**

Chèn thành dòng mới trước dòng 62:

```javascript
      function sparklineSeries(weekly,field){const series=[];let run=[],previousWeek=null;(weekly||[]).forEach(item=>{const value=item&&item.has_data!==false&&Number(item.total_tickets)>0?item[field]:null;if(value==null){if(run.length>1)series.push(run);run=[];previousWeek=null;return}if(previousWeek&&!isConsecutiveCohortWeek(previousWeek,item.cohort_week)){if(run.length>1)series.push(run);run=[]}previousWeek=item.cohort_week;run.push(Number(value))});if(run.length>1)series.push(run);return series}
      function sparkline(weekly,field){const series=sparklineSeries(weekly,field);if(!series.length)return null;const flat=series.flat(),min=Math.min(...flat),max=Math.max(...flat),span=max-min||1,count=(weekly||[]).length||1,svg=svgElement("svg",null,"kpi-sparkline");svg.setAttribute("viewBox","0 0 100 24");svg.setAttribute("aria-hidden","true");let offset=0;series.forEach(group=>{const points=group.map((value,index)=>`${((offset+index)*(100/Math.max(count-1,1))).toFixed(1)},${(22-20*(value-min)/span).toFixed(1)}`);offset+=group.length;const line=svgElement("polyline",null,"spark-line");line.setAttribute("points",points.join(" "));svg.appendChild(line)});return svg}
```

- [ ] **Step 4: Gắn sparkline vào thẻ**

Trong `renderKpis` (dòng 62), ở đoạn cuối `data.forEach(...)`, tìm nguyên văn:

```javascript
card.append(element("div",label,"kpi-label"),element("div",value,"kpi-value"),element("div",delta,"kpi-delta"),element("div",`${note}
```

đổi thành:

```javascript
const sparkFields={"AI First":"ai_first_rate","Tổng ticket":"total_tickets","Reopen sau AI First":"reopen_lifetime_rate",">4 turn không CS":"gt4_turn_without_cs"},spark=sparkline(rows(view),sparkFields[label]);card.append(element("div",label,"kpi-label"),element("div",value,"kpi-value"),element("div",delta,"kpi-delta"));if(spark)card.appendChild(spark);card.append(element("div",`${note}
```

Giữ nguyên phần sau `${note}` đến hết `grid.appendChild(card)`.

- [ ] **Step 5: Thêm CSS**

Ở dòng 11, cuối:

```css
.kpi-sparkline{display:block;width:100%;height:24px;margin-top:4px}.spark-line{fill:none;stroke:var(--accent);stroke-width:1.5}
```

- [ ] **Step 6: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh, kể cả `test_kpi_definitions_are_revealed_by_keyboard_focus_and_touch_activation` — sparkline là `svg`, không phải `button`, nên `card.children.find(node=>node.tagName==="button")` vẫn tìm ra nút định nghĩa.

- [ ] **Step 7: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥697 pass, exit 0.

---

## Task 8: Thẻ KPI còn một dòng nhiễu — bỏ timestamp lặp

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:62` (`renderKpis`)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: `updated(snapshot)` (giữ, vẫn dùng ở `applyEnvelope`, `copyWeekly`, `exportTicketsCsv`).
- Produces: `renderKpis` không còn sinh chuỗi `Cập nhật` — đưa `page.count("Cập nhật")` từ 3 về 2.

- [ ] **Step 1: Viết test thất bại**

```python
def test_kpi_cards_do_not_repeat_the_topbar_timestamp():
    """Timestamp lặp 4 lần trong hàng KPI là 4 dòng nhiễu cho 4 dòng số."""
    page = page_text()
    assert page.count("Cập nhật") <= 2
    observed = run(page, r"""
globalThis.__test.setSnapshot({generated_at:"2026-07-30T10:00:00Z"});
globalThis.__test.renderKpis({weekly:[{cohort_week:"2026-06-15",cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.7,reopen_lifetime_rate:.1,gt4_turn_without_cs:0},{cohort_week:"2026-06-22",cohort_status:"complete",has_data:true,total_tickets:12,ai_first_count:10,ai_first_rate:.8,reopen_lifetime_rate:.1,gt4_turn_without_cs:0}],rule_gt4:{gt4_turn_without_cs:0},ai_first:{rate:.8,count:10},totals:{eligible_ticket_count:22}});
const notes=document.getElementById("kpiGrid").children.map(card=>card.children.filter(node=>String(node.className).startsWith("kpi-note")).map(node=>node.textContent).join(""));
process.stdout.write(JSON.stringify({notes}));
""")
    assert all("Cập nhật" not in note for note in observed["notes"])
    assert all(note.count("·") <= 2 for note in observed["notes"]), "caption tối đa 1 dòng, không xâu chuỗi"
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py::test_kpi_cards_do_not_repeat_the_topbar_timestamp
```
Kỳ vọng: FAIL ở `page.count("Cập nhật") <= 2` (hiện 3).

- [ ] **Step 3: Xoá biến `refresh` và chỗ dùng nó**

Trong dòng 62:

- Xoá khỏi danh sách `const`: `,refresh=state.snapshot&&state.snapshot.generated_at?` ` · Cập nhật ${updated(state.snapshot)}`:""`
- Trong `card.append(...)`, đổi `` `${note}${attention?" · Tăng trên 5 điểm":""}${refresh}` `` thành `` `${note}${attention?" · Tăng trên 5 điểm":""}` ``

- [ ] **Step 4: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh. `updated()` vẫn có 3 caller — không xoá hàm.

- [ ] **Step 5: CHECKPOINT LÔ 2**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥698 pass, exit 0.

**DỪNG, báo Claude đo DOM.** Ngưỡng lô 2 (cộng dồn lô 1): không còn chữ nào render dưới 12px.

```js
(() => {
  const small = Array.from(document.querySelectorAll("*")).filter(node => {
    const size = parseFloat(getComputedStyle(node).fontSize);
    return node.textContent.trim() && size < 12;
  }).length;
  const kpi = document.getElementById("kpiGrid").getBoundingClientRect();
  return { textUnder12px: small, kpiHeight: Math.round(kpi.height) };
})()
```

Ngưỡng: `textUnder12px === 0` · `kpiHeight <= 220`.

---

# LÔ 3 — Segment và chart

## Task 9: Một disclosure định nghĩa cho cả hàng KPI

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:25` (markup `#week`), `:62` (`renderKpis`), `:114` (`initialise`), `:10` (CSS)
- Modify: `tests/test_frontend_contract.py:486-513`, `REQUIRED_IDS`
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Produces: `id="kpiDefinitionsToggle"` (button) + `id="kpiDefinitionsPanel"` (`<dl>`, `hidden` mặc định) trong markup tĩnh của section `#week`; `kpiLabels`, `kpiDefinitions`, `initialiseKpiDefinitions()`. Bốn `.definition-control` per-card bị xoá. Thẻ giữ `title` và `aria-describedby` trỏ tới `<dd id="kpiDefinition{index}">` trong panel chung.

Cùng khuôn với `initialiseWeeklyDefinitions()` (dòng 65) — dùng lại đúng mẫu đó, đừng phát minh mẫu thứ hai.

- [ ] **Step 1: Thêm id vào `REQUIRED_IDS` và thay test cũ**

Thêm `"kpiDefinitionsToggle", "kpiDefinitionsPanel",` vào `REQUIRED_IDS`.

Thay toàn bộ `test_kpi_definitions_are_revealed_by_keyboard_focus_and_touch_activation` (dòng 486-513) bằng:

```python
def test_kpi_definitions_use_one_disclosure_for_the_whole_row():
    """4 nút 'Định nghĩa' trên 4 thẻ là 4 dòng nhiễu; 1 disclosure cho cả hàng là đủ (spec §3.2)."""
    page = page_text()
    assert 'id="kpiDefinitionsToggle"' in page
    assert 'id="kpiDefinitionsPanel"' in page
    assert "definition-control" not in page, "nút per-card phải biến mất"

    observed = run(page, r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({status:"ready",refreshing:false,last_error_code:null,snapshot:null,items:[],page:1,page_size:50,total:0})});
document.dispatchEvent({type:"DOMContentLoaded"});
globalThis.__test.setSnapshot({generated_at:"2026-07-30T10:00:00Z"});
globalThis.__test.renderKpis({weekly:[{cohort_week:"2026-06-22",cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,reopen_lifetime_rate:.1,gt4_turn_without_cs:0}],rule_gt4:{gt4_turn_without_cs:0},ai_first:{rate:.8,count:8},totals:{eligible_ticket_count:10}});
const toggle=document.getElementById("kpiDefinitionsToggle"),panel=document.getElementById("kpiDefinitionsPanel");
const before={hidden:panel.hidden,expanded:toggle.getAttribute("aria-expanded")};
toggle.dispatchEvent({type:"click"});
const terms=panel.children.filter(node=>node.tagName==="dt").map(node=>node.textContent);
const described=document.getElementById("kpiGrid").children.map(card=>card.getAttribute("aria-describedby"));
const ids=panel.children.filter(node=>node.tagName==="dd").map(node=>node.getAttribute("id"));
process.stdout.write(JSON.stringify({before,after:{hidden:panel.hidden,expanded:toggle.getAttribute("aria-expanded")},terms,described,ids}));
""")
    assert observed["before"] == {"hidden": True, "expanded": "false"}
    assert observed["after"] == {"hidden": False, "expanded": "true"}
    assert observed["terms"] == [
        "AI First", "Tổng ticket", "Reopen sau AI First", ">4 turn không CS",
    ]
    assert observed["described"] == observed["ids"], "mỗi thẻ trỏ tới đúng định nghĩa của nó"
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py::test_kpi_definitions_use_one_disclosure_for_the_whole_row
```
Kỳ vọng: FAIL ở `'id="kpiDefinitionsToggle"' in page`.

- [ ] **Step 3: Thay markup section `#week`**

Ở dòng 25, đổi:

từ
```html
<section id="week" class="section"><div class="section-head"><div><p class="eyebrow">① Tuần này</p><h2>WTD và tuần trước</h2></div></div><div id="kpiGrid" class="kpi-grid"></div></section>
```
thành
```html
<section id="week" class="section"><div class="section-head"><div><p class="eyebrow">① Tuần này</p><h2>Tuần gần nhất so với tuần hoàn chỉnh trước đó</h2></div><div><button id="kpiDefinitionsToggle" class="button" type="button" aria-controls="kpiDefinitionsPanel" aria-expanded="false">Định nghĩa 4 chỉ số</button></div></div><div id="kpiGrid" class="kpi-grid"></div><dl id="kpiDefinitionsPanel" class="weekly-definitions" role="region" aria-labelledby="kpiDefinitionsToggle" hidden></dl></section>
```

Đổi luôn `<h2>` vì "WTD và tuần trước" mô tả sai — section không hiện tuần trước. Spec §0 nhận diện đây là một trong ba chỗ trượt câu hỏi §5.2.

- [ ] **Step 4: Thêm hàm khởi tạo panel và gọi trong `initialise`**

Chèn thành dòng mới ngay trước dòng 62:

```javascript
      const kpiLabels=["AI First","Tổng ticket","Reopen sau AI First",">4 turn không CS"];
      const kpiDefinitions={"AI First":"Tỷ lệ ticket có phản hồi AI thực chất: AI xử lý trọn cộng AI trả lời rồi chuyển CS.","Tổng ticket":"Số ticket đủ điều kiện trong phạm vi đang hiển thị, không tính direct chat.","Reopen sau AI First":"Tỷ lệ ticket AI First có reopen lifetime; chỉ so sánh các tuần đã hoàn tất.",">4 turn không CS":"Số ticket quá 4 turn nhưng chưa chuyển CS; cần xử lý."};
      function initialiseKpiDefinitions(){const toggle=$("kpiDefinitionsToggle"),panel=$("kpiDefinitionsPanel");clear(panel);kpiLabels.forEach((label,index)=>{const term=element("dt",label),description=element("dd",kpiDefinitions[label]);description.setAttribute("id",`kpiDefinition${index}`);panel.append(term,description)});panel.hidden=true;toggle.addEventListener("click",()=>{const open=panel.hidden;panel.hidden=!open;toggle.setAttribute("aria-expanded",String(open))})}
```

Trong `initialise()` (dòng 114), sau `initialiseWeeklyDefinitions();` thêm `initialiseKpiDefinitions();`.

- [ ] **Step 5: Bỏ nút per-card trong `renderKpis`**

Trong dòng 62:
- Xoá khai báo `definitions={...}` và thay mọi `definitions[label]` bằng `kpiDefinitions[label]`.
- Xoá `control`, `definitionText`, `revealDefinition` và mọi `control.setAttribute(...)`, `definitionText.setAttribute(...)`, `control.type="button"`, `control.addEventListener(...)`.
- Giữ `card.setAttribute("aria-describedby",definitionId)` với `definitionId=`kpiDefinition${definitionIndex}`` — trỏ sang `<dd>` trong panel chung.
- Trong `card.append(...)` bỏ hai phần tử cuối `control,definitionText`.

- [ ] **Step 6: Bỏ CSS không còn dùng**

Ở dòng 10:
- Xoá `.definition-control{margin-top:6px;padding:4px 8px;font-size:12px}`
- Xoá `.kpi-definition{margin:6px 0 0;padding:6px;border-left:3px solid var(--accent);background:var(--subtle);font-size:12px}`
- `.kpi-definition[hidden],.weekly-definitions[hidden]{display:none}` → `.weekly-definitions[hidden]{display:none}`

- [ ] **Step 7: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh.

- [ ] **Step 8: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥698 pass, exit 0 (test cũ bị thay, không cộng thêm).

---

## Task 10: Segment thành bảng thật, bar có sàn 2px, ngưỡng kèm ký hiệu

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:72` (`appendSegmentRow`), `:73` (`renderSegments`), `:10-11` (CSS)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: `view.segments[dimension]` — object `{ [label]: {total, ai_first, transferred, reopen} }`; `view.by_week[week].segments[dimension]`; `state.snapshot.coverage[dimension]`.
- Produces: `segmentBar(value, max) -> SVGElement` — `<svg class="rank-bar" viewBox="0 0 200 8">` chứa `<rect class="rank-bar-track">` và `<rect class="rank-bar-value">`, `width` có **sàn 2px**. `appendSegmentRow(list, key, name, item, max, filterable)` giữ nguyên chữ ký.

Đo được: thang linear max `3.911` vs min `131` → mọi bar sau cái đầu còn 3-8px. `<progress>` không đặt được sàn mà không chạm `.style.` → chuyển sang SVG rect. `skill` coverage `50,2%` là thấp nhất → tab dựa trên chiều đó phải nói rõ.

- [ ] **Step 1: Viết test thất bại**

```python
def test_segment_bars_have_a_two_pixel_floor_and_keep_exact_counts():
    """max 3.911 vs min 131 trên thang linear làm bar nhỏ còn 3px — biến mất khỏi trang."""
    observed = run(page_text(), r"""
globalThis.__test.setSegmentDimension("issue_category");
globalThis.__test.renderSegments({segments:{issue_category:{"Thanh toán-IBFT":{total:3911,ai_first:3684,transferred:469,reopen:120},"Khuyến mãi":{total:131,ai_first:3,transferred:127,reopen:0}}}});
const rows=document.getElementById("segmentList").children.filter(node=>node.className==="rank-row");
const bars=rows.map(row=>{const svg=row.children.find(node=>node.getAttribute("class")==="rank-bar");return Number(svg.children.filter(n=>n.getAttribute("class")==="rank-bar-value")[0].getAttribute("width"))});
process.stdout.write(JSON.stringify({bars,texts:rows.map(row=>row.textContent)}));
""")
    assert observed["bars"][0] == 200, "hàng lớn nhất chiếm hết 200 đơn vị"
    assert observed["bars"][1] >= 2, f"hàng nhỏ nhất phải còn thấy: {observed['bars'][1]}"
    assert "3.911" in observed["texts"][0]
    assert "131" in observed["texts"][1]


def test_segment_marks_bad_cells_with_a_symbol_not_colour_alone():
    """CVD ΔE 6.1 giữa đỏ và xanh: màu đơn độc không mang được thông tin."""
    observed = run(page_text(), r"""
globalThis.__test.setSegmentDimension("issue_category");
globalThis.__test.renderSegments({segments:{issue_category:{"Khuyến mãi":{total:362,ai_first:8,transferred:352,reopen:0}}}});
const row=document.getElementById("segmentList").children.filter(node=>node.className==="rank-row")[0];
process.stdout.write(JSON.stringify({text:row.textContent}));
""")
    assert "▼" in observed["text"], "AI 2,2% và chuyển CS 97,2% là ngưỡng xấu, phải có ký hiệu"


def test_segment_caption_declares_low_coverage_dimensions():
    """Tab dựa trên chiều phủ 50,2% mà không nói ra thì người đọc tưởng là toàn bộ."""
    observed = run(page_text(), r"""
globalThis.__test.setSnapshot({generated_at:"2026-07-30T10:00:00Z",coverage:{issue_category:.9,skill:.502}});
globalThis.__test.setSegmentDimension("skill");
globalThis.__test.renderSegments({segments:{skill:{"topup":{total:100,ai_first:80,transferred:20,reopen:2}}}});
process.stdout.write(JSON.stringify({caption:document.getElementById("segmentCaption").textContent}));
""")
    assert "50,2%" in observed["caption"]
    assert "không có dữ liệu skill" in observed["caption"]
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "segment_bars_have_a_two_pixel or segment_marks_bad_cells or segment_caption_declares"
```
Kỳ vọng: cả ba FAIL.

- [ ] **Step 3: Thay `appendSegmentRow`**

Thay toàn bộ dòng 72 bằng:

```javascript
      function segmentBar(value,max){const svg=svgElement("svg",null,"rank-bar");svg.setAttribute("viewBox","0 0 200 8");svg.setAttribute("aria-hidden","true");const track=svgElement("rect",null,"rank-bar-track"),fill=svgElement("rect",null,"rank-bar-value"),width=Math.max(2,Math.round(200*Number(value||0)/Math.max(max,1)));track.setAttribute("x","0");track.setAttribute("y","0");track.setAttribute("width","200");track.setAttribute("height","8");fill.setAttribute("x","0");fill.setAttribute("y","0");fill.setAttribute("width",String(width));fill.setAttribute("height","8");svg.append(track,fill);return svg}
      function appendSegmentRow(list,key,name,item,max,filterable=true){const row=element("div",null,"rank-row"),label=filterable?element("button",name):element("span",name,"rank-label"),total=Math.max(1,Number(item.total||0)),aiRate=Number(item.ai_first||0)/total,transferRate=Number(item.transferred||0)/total,aiMark=aiRate<.2?" ▼":"",transferMark=transferRate>.8?" ▼":"";if(filterable){label.type="button";label.addEventListener("click",()=>setSegmentFilter(key,name))}label.setAttribute("title",`${name}: ${number(item.total)} ticket · ${number(item.reopen||0)} reopen`);row.append(label,segmentBar(item.total,max),element("span",`${number(item.total)} N`),element("span",`${percent(aiRate)} AI${aiMark}`,aiMark?"bad-cell":""),element("span",`${percent(transferRate)} chuyển CS${transferMark}`,transferMark?"bad-cell":""));list.appendChild(row)}
```

Ngưỡng `aiRate < 20%` và `transferRate > 80%` là ngưỡng **trình bày**, không phải metric. Lấy từ ví dụ spec §3.3 (`Khuyến mãi: 2,2% AI · 97,2% chuyển CS` bị gọi là "gần như không phủ").
> `[PO]` Hai số 20% / 80% là judgment call. Đổi được bằng một dòng.

- [ ] **Step 4: Đổi cột `.rank-row` và caption trong `renderSegments`**

Ở dòng 10:
- `.rank-row{...grid-template-columns:minmax(0,1fr) 200px 80px 72px 150px;...}` → `grid-template-columns:minmax(0,320px) 200px 80px minmax(0,1fr) minmax(0,1fr)`
- Trong `@media (max-width:768px)`: `.rank-row{grid-template-columns:minmax(0,1fr) 48px 58px 120px}` → `.rank-row{grid-template-columns:minmax(0,1fr) 80px 72px}` và thêm `.rank-row>*:nth-child(2){display:none}` (bỏ bar trên mobile, số vẫn còn)

Trong `renderSegments` (dòng 73), thêm vào cuối hàm, sau `toggle.textContent=...`:

```javascript
const coverage=state.snapshot&&state.snapshot.coverage&&state.snapshot.coverage[key],dimensionName={issue_category:"nhóm vấn đề",app:"app",product_code:"nghiệp vụ",skill:"skill",intent:"intent"}[key]||key,base="Xếp theo số ticket giảm dần; chọn một hàng để mang filter xuống Ticket Explorer.";setText("segmentCaption",coverage!=null&&Number(coverage)<.8?`Chiều này phủ ${percent(coverage)} ticket; phần còn lại không có dữ liệu ${dimensionName}. ${base}`:base);
```

- [ ] **Step 5: Thêm CSS, xoá CSS của `<progress>`**

Ở dòng 11, thêm vào cuối:

```css
.rank-bar{display:block;width:200px;height:8px}.rank-bar-track{fill:var(--subtle)}.rank-bar-value{fill:var(--volume)}.bad-cell{color:var(--bad);font-weight:700}.rank-row button,.rank-label{max-width:320px}
```

Xoá ở dòng 11: `.rank-bar{accent-color:var(--volume)}`, `.rank-bar::-webkit-progress-value{background:var(--volume)}`, `.rank-bar::-moz-progress-bar{background:var(--volume)}`. Xoá ở dòng 10: `.rank-bar{width:100%;height:8px}`.

- [ ] **Step 6: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh. Hai test segment cũ (dòng 699, 712) đọc `.className==="rank-row"` và `textContent` — vẫn khớp. **Nếu chúng đọc `progress` thì dừng và báo** trước khi sửa, vì chúng không nằm trong danh sách được phép sửa.

- [ ] **Step 7: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥701 pass, exit 0.

---

## Task 11: Tách chart thành hai — hết hai thang y

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:27` (markup `#trend`), `:70` (`renderTrend`), `:10-11` (CSS)
- Modify: `tests/test_frontend_contract.py` — `REQUIRED_IDS`, ba test trend (dòng 858, 874, 890), và test T2
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Produces: `id="trendVolumeChart"` (cột, một chuỗi, một thang, không legend) và `id="trendRateChart"` (hai đường, thang 0-100%, legend sát chart). `trendChart` **biến mất**. `renderTrend(weekly)` giữ tên, vẽ cả hai. Cột giữ `data-week`, `role="button"`, `tabindex="0"`, `aria-label`; click/Enter vẫn gọi `setWeekFilter`.

Lỗi chart số một: cột (volume) và hai đường (tỉ lệ) cùng khung = hai thang y.

- [ ] **Step 1: Cập nhật `REQUIRED_IDS` và bốn test**

Trong `REQUIRED_IDS`, đổi `"trendChart",` thành `"trendVolumeChart", "trendRateChart",`.

Trong test T2 `test_trend_places_first_data_week_at_the_left_edge_and_scales_to_render_box`, đổi `getElementById("trendChart")` thành `getElementById("trendVolumeChart")`.

Thay ba test (dòng 858-897) bằng:

```python
def test_trend_splits_volume_and_rate_into_two_single_scale_charts():
    """Cột volume và đường tỉ lệ trên một khung = hai thang y, lỗi chart số một."""
    page = page_text()
    assert 'id="trendVolumeChart"' in page and 'id="trendRateChart"' in page
    assert 'id="trendChart"' not in page
    assert 'preserveAspectRatio="none"' not in page

    observed = run(page, r"""
globalThis.__test.renderTrend([{cohort_week:"2026-07-20",cohort_status:"complete",has_data:true,total_tickets:10,ai_first_rate:.8,reopen_lifetime_rate:.2}]);
const volume=document.getElementById("trendVolumeChart"),rate=document.getElementById("trendRateChart");
process.stdout.write(JSON.stringify({
  volumeRects:volume.children.filter(node=>node.tagName==="rect").length,
  volumePolylines:volume.children.filter(node=>node.tagName==="polyline").length,
  ratePolylines:rate.children.filter(node=>node.tagName==="polyline").length,
  rateRects:rate.children.filter(node=>node.tagName==="rect"&&String(node.getAttribute("class")).includes("bar")).length,
  volumeText:volume.textContent,
  namespaces:[...volume.children,...rate.children].map(node=>node.namespaceURI)
}));
""")
    assert observed["volumeRects"] == 1, "chart cột chỉ có cột"
    assert observed["volumePolylines"] == 0, "không đường nào trên chart cột"
    assert observed["rateRects"] == 0, "không cột nào trên chart đường"
    assert "10 ticket" in observed["volumeText"]
    assert "AI First 80,0%" in observed["volumeText"]
    assert set(observed["namespaces"]) == {"http://www.w3.org/2000/svg"}
    assert "IntersectionObserver" in page
    assert 'aria-current","location"' in page


def test_trend_rate_chart_keeps_solid_ai_and_dashed_reopen_encoding():
    page = page_text()
    assert re.search(r"\.line-reopen\{[^}]*stroke-dasharray:6 4", page)
    assert not re.search(r"\.line-ai\{[^}]*stroke-dasharray", page)
    observed = run(page, r"""
const full=(date,ai,reopen)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_rate:ai,reopen_lifetime_rate:reopen});
globalThis.__test.renderTrend([full("2026-07-13",.7,.1),full("2026-07-20",.8,.2)]);
const lines=document.getElementById("trendRateChart").children.filter(node=>node.tagName==="polyline");
const byClass=Object.fromEntries(lines.map(line=>[line.getAttribute("class"),line.getAttribute("stroke-dasharray")]));
process.stdout.write(JSON.stringify({byClass,caption:document.getElementById("trendCaption").textContent}));
""")
    assert observed["byClass"] == {"line-ai": None, "line-reopen": "6 4"}
    assert "đường liền xanh là AI First" in observed["caption"]
    assert "đường đứt vàng là reopen" in observed["caption"]


def test_trend_rate_chart_still_breaks_lines_at_a_missing_week():
    observed = run(page_text(), r"""
const full=(date)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_rate:.8,reopen_lifetime_rate:.2});
globalThis.__test.renderTrend([full("2026-07-06"),{cohort_week:"2026-07-13",has_data:false,total_tickets:0},full("2026-07-20")]);
process.stdout.write(JSON.stringify({polylines:document.getElementById("trendRateChart").children.filter(node=>node.tagName==="polyline").length}));
""")
    assert observed["polylines"] == 4
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k trend
```
Kỳ vọng: FAIL ở `'id="trendVolumeChart"' in page`.

- [ ] **Step 3: Thay markup section `#trend`**

Ở dòng 27, đổi:

từ
```html
<div class="chart"><svg id="trendChart" role="img" aria-label="Xu hướng tuần"></svg><p id="trendEmpty" hidden>Không có dữ liệu trong tuần này.</p></div>
```
thành
```html
<div class="chart"><h3 class="chart-title">Volume theo tuần</h3><svg id="trendVolumeChart" role="img" aria-label="Tổng ticket theo tuần"></svg><p id="trendEmpty" hidden>Không có dữ liệu trong tuần này.</p></div><div class="chart"><h3 class="chart-title">AI First và Reopen theo tuần (%)</h3><p class="chart-legend"><span class="legend-ai">— AI First</span> <span class="legend-reopen">-- Reopen sau AI First</span></p><svg id="trendRateChart" role="img" aria-label="Tỷ lệ AI First và reopen theo tuần"></svg></div>
```

- [ ] **Step 4: Thay `renderTrend`**

Thay toàn bộ hàm `renderTrend` (bản T2) bằng:

```javascript
      function renderTrend(weekly){const volume=$("trendVolumeChart"),rate=$("trendRateChart"),empty=$("trendEmpty"),source=weekly||[],data=source.filter(item=>item&&item.has_data!==false&&Number(item.total_tickets)>0);clear(volume);clear(rate);volume.setAttribute("viewBox","0 0 320 120");volume.setAttribute("preserveAspectRatio","xMidYMid meet");rate.setAttribute("viewBox","0 0 320 120");rate.setAttribute("preserveAspectRatio","xMidYMid meet");empty.hidden=Boolean(data.length);if(!data.length){empty.hidden=false;setText("trendCaption","Không có tuần nào có dữ liệu trong cửa sổ đang xem.");return}const max=Math.max(...data.map(x=>Number(x.total_tickets))),step=272/Math.max(data.length-1,1),xAt=index=>24+index*step,aiGroups=[],reopenGroups=[];let ai=[],reopen=[],previousWeek=null;const flush=()=>{if(ai.length>1)aiGroups.push(ai);ai=[];if(reopen.length>1)reopenGroups.push(reopen);reopen=[]};data.forEach((item,index)=>{if(previousWeek&&!isConsecutiveCohortWeek(previousWeek,item.cohort_week))flush();previousWeek=item.cohort_week;const x=xAt(index),height=Math.max(1,88*Number(item.total_tickets)/max),label=`Tuần ${dateRange(item.cohort_week)}: ${number(item.total_tickets)} ticket · AI First ${percent(item.ai_first_rate)} · Reopen ${percent(item.reopen_lifetime_rate)}`,activate=()=>setWeekFilter(item.cohort_week,true),bar=svgElement("rect",null,item.cohort_status==="wtd"?"bar wtd-bar":"bar");bar.setAttribute("x",x-8);bar.setAttribute("y",100-height);bar.setAttribute("width","16");bar.setAttribute("height",height);bar.setAttribute("role","button");bar.setAttribute("tabindex","0");bar.setAttribute("data-week",item.cohort_week);bar.setAttribute("aria-label",`${label}. Nhấn Enter để lọc tuần này.`);bar.appendChild(svgElement("title",label));bar.addEventListener("click",activate);bar.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();activate()}});volume.appendChild(bar);if(item.cohort_status==="wtd"){const wtd=svgElement("text","WTD","axis-label");wtd.setAttribute("x",x-8);wtd.setAttribute("y","114");volume.appendChild(wtd)}ai.push(`${x},${100-88*Number(item.ai_first_rate||0)}`);if(item.reopen_lifetime_rate==null){if(reopen.length>1)reopenGroups.push(reopen);reopen=[]}else reopen.push(`${x},${100-88*Number(item.reopen_lifetime_rate)}`)});flush();[["line-ai",aiGroups],["line-reopen",reopenGroups]].forEach(([klass,groups])=>groups.forEach(points=>{const path=svgElement("polyline",null,klass);path.setAttribute("points",points.join(" "));if(klass==="line-reopen")path.setAttribute("stroke-dasharray","6 4");rate.appendChild(path)}));[[0,"0%"],[44,"50%"],[88,"100%"]].forEach(([offset,text])=>{const tick=svgElement("text",text,"axis-label");tick.setAttribute("x","2");tick.setAttribute("y",String(100-offset+4));rate.appendChild(tick)});[0,Math.floor((data.length-1)/2),data.length-1].filter((value,index,list)=>list.indexOf(value)===index).forEach(index=>{const tick=svgElement("text",dateRange(data[index].cohort_week).split(" – ")[0],"axis-label");tick.setAttribute("x",String(Math.min(xAt(index),280)));tick.setAttribute("y","116");rate.appendChild(tick)});setText("trendCaption",`Có ${number(data.length)} tuần có dữ liệu. Chart trên là tổng ticket; chart dưới là tỷ lệ trên thang 0–100%, đường liền xanh là AI First, đường đứt vàng là reopen. Tuần WTD có viền đứt và nhãn WTD. Tuần không có dữ liệu bị bỏ khỏi trục và đường bị ngắt tại đó. Click hoặc Enter trên cột để lọc. Số chính xác nằm ở bảng ② Báo cáo tuần.`)}
```

Bốn thay đổi thực chất so với bản T2: hai `<svg>` thay một; `viewBox` cao 120 mỗi cái; nhãn trục `0/50/100%` + ba mốc thời gian trên chart đường; nhãn chữ `WTD` dưới cột WTD. `flush()` giờ đòi `length > 1` — điểm lẻ không tạo `polyline` một điểm (vô hình, làm sai số đếm).

- [ ] **Step 5: Thêm CSS**

Ở dòng 11, cuối:

```css
.chart-title{margin:0 0 4px;font-size:12px;font-weight:750;letter-spacing:.02em}.chart-legend{margin:0 0 4px;font-size:12px}.legend-ai{color:var(--accent);font-weight:700}.legend-reopen{color:var(--warn-text);font-weight:700}#trend .chart+.chart{margin-top:12px}
```

Ở dòng 10, `.chart svg{display:block;width:100%;height:170px}` → `.chart svg{display:block;width:100%;height:140px}`.

- [ ] **Step 6: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh, kể cả `test_week_filter_updates_kpis_and_segment_buckets_not_only_diagnostics` (dòng 669) — hành vi lọc theo tuần không đổi — và `test_p4_uses_schema_views_transfer_contract_and_responsive_scroller` (dòng 142 assert `"line-reopen" in page` và `'setAttribute("tabindex","0")' in page`, cả hai còn).

- [ ] **Step 7: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥701 pass, exit 0.

---

## Task 12: Lớp hover — crosshair và tooltip

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:70` (`renderTrend`), `:11` (CSS)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: `data`, `xAt`, `step` trong `renderTrend`.
- Produces: mỗi tuần trên chart đường có một `<rect class="hit-area">` rộng `step`, cao hết khung, trong suốt, mang `<title>`; và hai `<circle class="rate-marker marker-ai|marker-reopen">` r=4 mang `<title>`. **Không** listener `mousemove`.

Spec §3.5 đòi "crosshair + tooltip", nhưng listener `mousemove` cần đo toạ độ và đặt vị trí động → phá `.style.` count. Thay bằng: vùng bấm phủ hết chiều cao (là crosshair khi hover, qua CSS `:hover`), tooltip là `<title>` gốc SVG. Không JS thêm, không rủi ro hiệu năng.

- [ ] **Step 1: Viết test thất bại**

```python
def test_rate_chart_has_markers_and_full_height_hit_areas_with_titles():
    """Marker nhỏ và vùng bấm chỉ bằng nét vẽ thì không ai trỏ được vào điểm nào."""
    page = page_text()
    assert ".hit-area" in page and ".rate-marker" in page
    observed = run(page, r"""
const full=(date,ai)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_rate:ai,reopen_lifetime_rate:.2});
globalThis.__test.renderTrend([full("2026-07-13",.7),full("2026-07-20",.8)]);
const rate=document.getElementById("trendRateChart");
const hits=rate.children.filter(node=>node.getAttribute("class")==="hit-area");
const markers=rate.children.filter(node=>String(node.getAttribute("class")).includes("rate-marker"));
process.stdout.write(JSON.stringify({hits:hits.length,markers:markers.length,titles:hits.map(node=>node.children.map(child=>child.textContent).join("")),heights:hits.map(node=>Number(node.getAttribute("height")))}));
""")
    assert observed["hits"] == 2, "một vùng bấm mỗi tuần"
    assert observed["markers"] == 4, "AI First và reopen, mỗi tuần một marker"
    assert all("AI First" in title for title in observed["titles"])
    assert all(height >= 100 for height in observed["heights"]), "vùng bấm phủ hết chiều cao = crosshair"
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py::test_rate_chart_has_markers_and_full_height_hit_areas_with_titles
```
Kỳ vọng: FAIL ở `".hit-area" in page`.

- [ ] **Step 3: Thêm marker và hit area trong `renderTrend`**

Trong hàm `renderTrend` (bản T11), sau `flush();` và **trước** khối nhãn trục `[[0,"0%"],[44,"50%"],[88,"100%"]]`, chèn:

```javascript
data.forEach((item,index)=>{const x=xAt(index),hit=svgElement("rect",null,"hit-area"),label=`Tuần ${dateRange(item.cohort_week)}: AI First ${percent(item.ai_first_rate)} · Reopen ${percent(item.reopen_lifetime_rate)}`;hit.setAttribute("x",String(x-step/2));hit.setAttribute("y","0");hit.setAttribute("width",String(step));hit.setAttribute("height","110");hit.appendChild(svgElement("title",label));rate.appendChild(hit);const aiMarker=svgElement("circle",null,"rate-marker marker-ai");aiMarker.setAttribute("cx",String(x));aiMarker.setAttribute("cy",String(100-88*Number(item.ai_first_rate||0)));aiMarker.setAttribute("r","4");aiMarker.appendChild(svgElement("title",label));rate.appendChild(aiMarker);const reopenMarker=svgElement("circle",null,"rate-marker marker-reopen");reopenMarker.setAttribute("cx",String(x));reopenMarker.setAttribute("cy",String(item.reopen_lifetime_rate==null?100:100-88*Number(item.reopen_lifetime_rate)));reopenMarker.setAttribute("r","4");reopenMarker.appendChild(svgElement("title",item.reopen_lifetime_rate==null?`Tuần ${dateRange(item.cohort_week)}: chưa đủ 7 ngày để tính reopen`:label));rate.appendChild(reopenMarker)});
```

`r=4` trong `viewBox` cao 120 render ở ~140px CSS → đường kính thực ≈ 8px, đạt sàn spec §3.5 "marker ≥ 8px".

Chú ý thứ tự append: `hit-area` phải nằm **sau** `polyline` để nhận hover, nhưng `marker` cũng sau `hit-area` để không bị che. Đúng thứ tự trong đoạn trên.

- [ ] **Step 4: Thêm CSS**

Ở dòng 11, cuối:

```css
.hit-area{fill:transparent}.hit-area:hover{fill:color-mix(in srgb,var(--accent) 8%,transparent)}.rate-marker{stroke:var(--paper);stroke-width:1}.marker-ai{fill:var(--accent)}.marker-reopen{fill:var(--warn)}.bar{transition:fill 120ms}
```

- [ ] **Step 5: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh. `test_trend_rate_chart_still_breaks_lines_at_a_missing_week` vẫn `polylines == 4` (marker là `circle`, không phải `polyline`). `test_trend_splits_volume_and_rate...` vẫn `rateRects == 0` vì T11 đã đếm riêng `rect` có class chứa `bar` — `hit-area` không tính.

- [ ] **Step 6: CHECKPOINT LÔ 3**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥702 pass, exit 0.

**DỪNG, báo Claude đo DOM.**

```js
(() => {
  const rects = Array.from(document.querySelectorAll("#trendVolumeChart rect.bar"));
  const rate = document.getElementById("trendRateChart").getBoundingClientRect();
  const volume = document.getElementById("trendVolumeChart").getBoundingClientRect();
  const bars = Array.from(document.querySelectorAll("#segmentList .rank-bar-value"));
  return {
    volumeBars: rects.length,
    volumeAspect: +(volume.width / volume.height).toFixed(2),
    rateAspect: +(rate.width / rate.height).toFixed(2),
    smallestSegmentBarPx: bars.length ? Math.min(...bars.map(node => node.getBoundingClientRect().width)) : null,
    axisLabelOverflow: Array.from(document.querySelectorAll(".axis-label")).some(node => node.getBoundingClientRect().right > rate.right + 1)
  };
})()
```

Ngưỡng: `smallestSegmentBarPx >= 2` · `axisLabelOverflow === false` · `volumeAspect` và `rateAspect` ≤ 4 (không còn giãn 4,3x).

---

# LÔ 4 — Hoàn thiện sản phẩm

## Task 13: Dải "Cần xử lý" — phần tử chữ ký

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:25` (markup, thêm section), `:62` (`renderKpis` — ngưỡng), `:96` (`renderDashboard`), `:11` (CSS)
- Modify: `tests/test_frontend_contract.py:443-485`, `REQUIRED_IDS`, `run()` hooks (dòng 79)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: `rows(view)`, `view.segments.issue_category`, `view.rule_gt4.gt4_turn_without_cs`, `snapshot.unmapped_tpe_codes`.
- Produces:
  - `medianOf(values) -> number|null` — trung vị; `null` khi mảng rỗng.
  - `reopenAttentionThreshold(view) -> number|null` — trung vị `reopen_lifetime_rate` của các tuần `has_data !== false && cohort_status === "complete" && reopen_lifetime_rate != null`, **cộng 0.05**; trả `null` khi dưới 3 tuần đủ điều kiện.
  - `renderAttentionStrip(view, snapshot)` — render tối đa 3 `<li>` vào `#attentionStrip`; không dòng nào thì xoá hết con và `hidden = true`.
  - `id="attentionStrip"` (`<ul>`, `hidden` mặc định) trong section mới `#attentionSection`.

Ngưỡng cũ (`delta > 5 điểm so tuần trước`) bị thay bằng trung vị + 5 điểm, vì delta-so-tuần-trước báo động giả khi hai tuần liền kề đều thấp. Dưới 3 tuần có dữ liệu thì **không** tính ngưỡng và **không** cảnh báo. Xem D3.

- [ ] **Step 1: Cập nhật hooks, `REQUIRED_IDS`, và thay hai test ngưỡng cũ**

Thêm `"attentionStrip",` vào `REQUIRED_IDS`. Trong `run()` (dòng 79), thêm `renderAttentionStrip,` vào `globalThis.__test={...}`.

Thay `test_reopen_warning_marks_only_completed_week_increase_above_five_points` và `test_reopen_warning_uses_display_rounded_threshold_and_complete_values_only` (dòng 443-485) bằng:

```python
def test_reopen_attention_uses_median_of_complete_weeks_plus_five_points():
    """Delta so tuần trước báo động giả khi hai tuần liền kề đều thấp; trung vị bền hơn."""
    observed = run(page_text(), r"""
const week=(date,reopen)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:100,ai_first_count:80,ai_first_rate:.8,reopen_lifetime_rate:reopen,gt4_turn_without_cs:0});
globalThis.__test.setSnapshot({generated_at:"2026-07-30T10:00:00Z"});
// trung vị của .10 .10 .12 .12 = .11 -> ngưỡng .16
globalThis.__test.renderKpis({weekly:[week("2026-06-01",.10),week("2026-06-08",.10),week("2026-06-15",.12),week("2026-06-22",.12)],rule_gt4:{gt4_turn_without_cs:0},ai_first:{rate:.8,count:80},totals:{eligible_ticket_count:400}});
const below=document.getElementById("kpiGrid").children[2].className;
globalThis.__test.renderKpis({weekly:[week("2026-06-01",.10),week("2026-06-08",.10),week("2026-06-15",.12),week("2026-06-22",.20)],rule_gt4:{gt4_turn_without_cs:0},ai_first:{rate:.8,count:80},totals:{eligible_ticket_count:400}});
const above=document.getElementById("kpiGrid").children[2].className;
process.stdout.write(JSON.stringify({below,above}));
""")
    assert "attention" not in observed["below"], ".12 dưới ngưỡng .16 -> không cảnh báo"
    assert "attention" in observed["above"], ".20 trên ngưỡng .16 -> cảnh báo"


def test_reopen_attention_needs_three_complete_data_weeks_before_it_fires():
    """Hai tuần không đủ để có trung vị đáng tin — thà không cảnh báo còn hơn cảnh báo sai."""
    observed = run(page_text(), r"""
const week=(date,reopen)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:100,ai_first_count:80,ai_first_rate:.8,reopen_lifetime_rate:reopen,gt4_turn_without_cs:0});
globalThis.__test.setSnapshot({generated_at:"2026-07-30T10:00:00Z"});
globalThis.__test.renderKpis({weekly:[week("2026-06-15",.05),week("2026-06-22",.90)],rule_gt4:{gt4_turn_without_cs:0},ai_first:{rate:.8,count:80},totals:{eligible_ticket_count:200}});
process.stdout.write(JSON.stringify({className:document.getElementById("kpiGrid").children[2].className}));
""")
    assert "attention" not in observed["className"]


def test_attention_strip_disappears_entirely_when_nothing_crosses_a_threshold():
    """'Mọi thứ ổn' là một dòng nhiễu; không có gì thì không vẽ gì."""
    page = page_text()
    assert 'id="attentionStrip"' in page
    observed = run(page, r"""
const week=(date,reopen)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:100,ai_first_count:80,ai_first_rate:.8,reopen_lifetime_rate:reopen,gt4_turn_without_cs:0});
globalThis.__test.setSnapshot({generated_at:"2026-07-30T10:00:00Z",unmapped_tpe_codes:[]});
globalThis.__test.renderAttentionStrip({weekly:[week("2026-06-01",.10),week("2026-06-08",.10),week("2026-06-15",.10)],rule_gt4:{gt4_turn_without_cs:0},segments:{issue_category:{}}},{unmapped_tpe_codes:[]});
const strip=document.getElementById("attentionStrip");
process.stdout.write(JSON.stringify({hidden:strip.hidden,children:strip.children.length}));
""")
    assert observed == {"hidden": True, "children": 0}


def test_attention_strip_reports_at_most_three_problems_with_symbols_and_links():
    observed = run(page_text(), r"""
const week=(date,reopen,stuck)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:100,ai_first_count:80,ai_first_rate:.8,reopen_lifetime_rate:reopen,gt4_turn_without_cs:stuck||0});
globalThis.__test.setSnapshot({generated_at:"2026-07-30T10:00:00Z",unmapped_tpe_codes:[{code:"-217",count:2}]});
globalThis.__test.renderAttentionStrip({weekly:[week("2026-06-01",.10),week("2026-06-08",.10),week("2026-06-15",.30,7)],rule_gt4:{gt4_turn_without_cs:7},segments:{issue_category:{"Khuyến mãi":{total:362,ai_first:8,transferred:352,reopen:0}}}},{unmapped_tpe_codes:[{code:"-217",count:2}]});
const strip=document.getElementById("attentionStrip");
process.stdout.write(JSON.stringify({hidden:strip.hidden,lines:strip.children.map(node=>node.textContent),hrefs:strip.children.map(node=>{const link=node.children.find(child=>child.tagName==="a");return link&&link.getAttribute("href")})}));
""")
    assert observed["hidden"] is False
    assert 1 <= len(observed["lines"]) <= 3
    assert all("▼" in line for line in observed["lines"]), "ký hiệu kèm màu, không màu đơn độc"
    assert all(any(char.isdigit() for char in line) for line in observed["lines"]), "mỗi dòng có số"
    assert all(href and href.startswith("#") for href in observed["hrefs"])
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "reopen_attention or attention_strip"
```
Kỳ vọng: bốn FAIL.

- [ ] **Step 3: Thêm markup dải**

Ở dòng 25, ngay **sau** `</section>` của `#week`, thêm:

```html
      <section id="attentionSection" class="section" aria-labelledby="attentionHeading"><p class="eyebrow" id="attentionHeading">Cần xử lý</p><ul id="attentionStrip" class="attention-strip" hidden></ul></section>
```

- [ ] **Step 4: Thêm ba hàm mới**

Chèn thành dòng mới ngay trước `renderKpis`:

```javascript
      function medianOf(values){const sorted=values.filter(value=>value!=null&&Number.isFinite(Number(value))).map(Number).sort((a,b)=>a-b);if(!sorted.length)return null;const middle=Math.floor(sorted.length/2);return sorted.length%2?sorted[middle]:(sorted[middle-1]+sorted[middle])/2}
      function reopenAttentionThreshold(view){const eligible=rows(view).filter(item=>item&&item.has_data!==false&&item.cohort_status==="complete"&&item.reopen_lifetime_rate!=null);if(eligible.length<3)return null;const median=medianOf(eligible.map(item=>item.reopen_lifetime_rate));return median==null?null:median+.05}
      function renderAttentionStrip(view,snapshot){const strip=$("attentionStrip");clear(strip);const lines=[],threshold=reopenAttentionThreshold(view),available=rows(view).filter(item=>item&&item.has_data!==false&&Number(item.total_tickets)>0),latest=available.at(-1),stuck=Number(view&&view.rule_gt4&&view.rule_gt4.gt4_turn_without_cs||0),unmapped=Array.isArray(snapshot&&snapshot.unmapped_tpe_codes)?snapshot.unmapped_tpe_codes:[];if(stuck>0)lines.push([3,`▼ ${number(stuck)} ticket quá 4 turn nhưng chưa chuyển CS — user có thể đang kẹt`,"#rules","Rule"]);if(threshold!=null&&latest&&latest.reopen_lifetime_rate!=null&&Number(latest.reopen_lifetime_rate)>threshold)lines.push([2,`▼ Reopen ${percent(latest.reopen_lifetime_rate)} tuần ${dateRange(latest.cohort_week)} — cao hơn ngưỡng ${percent(threshold)} (trung vị các tuần hoàn chỉnh cộng 5 điểm)`,"#trend","Xu hướng"]);Object.entries(view&&view.segments&&view.segments.issue_category||{}).forEach(([name,item])=>{const total=Math.max(1,Number(item.total||0));if(Number(item.total||0)>=100&&Number(item.ai_first||0)/total<.2)lines.push([1,`▼ ${name}: ${percent(Number(item.ai_first||0)/total)} AI · ${percent(Number(item.transferred||0)/total)} chuyển CS trên ${number(item.total)} ticket — gần như không phủ`,"#segments","Segment"])});if(unmapped.length)lines.push([0,`▼ ${number(unmapped.length)} mã TPE chưa có trong taxonomy — ticket liên quan rơi vào "Không xác định"`,"#quality","Dữ liệu"]);if(!lines.length){strip.hidden=true;return}strip.hidden=false;lines.sort((a,b)=>b[0]-a[0]).slice(0,3).forEach(([,text,href,linkLabel])=>{const row=element("li",null,"attention-line"),link=element("a",`→ ${linkLabel}`,"attention-link");link.setAttribute("href",href);row.append(element("span",text),link);strip.appendChild(row)})}
```

- [ ] **Step 5: Đổi ngưỡng trong `renderKpis`, gọi dải trong `renderDashboard`**

Trong dòng 62, thay biểu thức `reopenAttention`:

từ `reopenAttention=hasSelected&&selected.cohort_status==="complete"&&previous&&previous.cohort_status==="complete"&&reopenDelta!=null&&reopenDelta>5`
thành `reopenThreshold=reopenAttentionThreshold(view),reopenAttention=hasSelected&&reopenThreshold!=null&&latestReopen!=null&&Number(latestReopen)>reopenThreshold`

Đổi chuỗi caption `" · Tăng trên 5 điểm"` thành `" · Trên ngưỡng cảnh báo"`.

`reopenDelta` có thể thành biến chết. Kiểm trước khi xoá:

```bash
grep -o "reopenDelta" src/weekly_cs_report/static/index.html | wc -l
grep -o "displayedRateDelta" src/weekly_cs_report/static/index.html | wc -l
```
Chỉ xoá khi số lần xuất hiện chứng minh không còn caller nào ngoài khai báo.

Trong `renderDashboard` (dòng 96), sau `renderKpis(view);` thêm `renderAttentionStrip(view,snapshot);`.

- [ ] **Step 6: Thêm CSS**

Ở dòng 11, cuối:

```css
.attention-strip{display:grid;gap:8px;margin:0;padding:0;max-width:var(--content-max);list-style:none}.attention-line{display:flex;gap:12px;align-items:baseline;justify-content:space-between;padding:8px;border-left:3px solid var(--bad);background:var(--subtle);font-weight:650}.attention-link{flex:0 0 auto;color:var(--accent)}#attentionSection{border-top:0;padding:4px 0 12px}
```

- [ ] **Step 7: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh.

- [ ] **Step 8: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥704 pass, exit 0.

---

## Task 14: Bốn trạng thái vận hành

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:18` (topbar), `:22` (markup `main`), `:99` (`applyEnvelope`), `:101` (`postRefresh`), `:11` (CSS)
- Modify: `tests/test_frontend_contract.py` — `REQUIRED_IDS`
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: envelope `{status, refreshing, last_error_code, last_error_at, snapshot}` (`web.py:350-360`). `status` ∈ `{"loading","refreshing","stale_error","ready"}` (`dashboard_cache.py:234-250`).
- Produces:
  - `id="firstLoadBlock"` — khối giữa trang, hiện khi `!snapshot`.
  - `id="staleErrorLine"` — dòng cạnh timestamp, hiện khi `last_error_code != null`.
  - `REFRESH_COOLDOWN_SECONDS = 60` + `startRefreshCooldown()` (xem D2).
- **Không** thêm field nào vào payload.

| Trạng thái | Nguồn | Hình thức |
|---|---|---|
| Lần đầu tải, chưa có snapshot | `snapshot === null` | `#firstLoadBlock` hiện; không vẽ khung rỗng, không vẽ 0 |
| Refresh nền, có dữ liệu cũ | `refreshing === true` + có snapshot | Chỉ báo cạnh timestamp; số vẫn hiện; không chặn tương tác |
| Refresh thất bại | `last_error_code != null` | `#staleErrorLine`; **không** stack trace, **không** chi tiết nội bộ |
| Bấm làm mới trong cooldown | client, 60s | Nút vô hiệu + đếm giây |

- [ ] **Step 1: Thêm id vào `REQUIRED_IDS` và viết test thất bại**

Thêm `"firstLoadBlock", "staleErrorLine",` vào `REQUIRED_IDS`.

```python
def test_first_load_shows_a_block_instead_of_empty_frames():
    """Vẽ khung rỗng hoặc số 0 khi chưa có snapshot là bịa dữ liệu."""
    page = page_text()
    assert "Đang lấy dữ liệu lần đầu" in page
    observed = run(page, r"""
globalThis.__test.applyEnvelope({status:"loading",refreshing:true,last_error_code:null,snapshot:null});
process.stdout.write(JSON.stringify({block:document.getElementById("firstLoadBlock").hidden,busy:document.getElementById("dashboardMain").getAttribute("aria-busy"),status:document.getElementById("liveStatus").textContent}));
""")
    assert observed["block"] is False
    assert observed["busy"] == "true"
    assert "Đang lấy dữ liệu lần đầu" in observed["status"]


def test_stale_error_line_names_the_code_without_leaking_internals():
    """Người đọc cần biết số đang cũ và cũ từ lúc nào; không cần stack trace."""
    page = page_text()
    assert "Lần cập nhật" in page
    observed = run(page, r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})});
const view={weekly:[],totals:{eligible_ticket_count:0},ai_first:{rate:null,count:0},rule_gt4:{},segments:{},transfer_reasons:{},by_week:{}};
globalThis.__test.applyEnvelope({status:"stale_error",refreshing:false,last_error_code:"langfuse_timeout",last_error_at:"2026-07-30T09:00:00Z",snapshot:{generated_at:"2026-07-30T08:00:00Z",views:{mon_sun:view,mon_fri:view},coverage:{},gate_status:{},data_quality:{},data_range:{},unmapped_tpe_codes:[]}});
const line=document.getElementById("staleErrorLine");
process.stdout.write(JSON.stringify({hidden:line.hidden,text:line.textContent,block:document.getElementById("firstLoadBlock").hidden}));
""")
    assert observed["hidden"] is False
    assert "langfuse_timeout" in observed["text"]
    assert "Traceback" not in observed["text"] and "  File " not in observed["text"]
    assert observed["block"] is True, "có snapshot thì khối lần-đầu phải tắt"


def test_refresh_button_counts_down_its_cooldown_instead_of_going_silent():
    """Bấm làm mới mà không có phản hồi nào là trạng thái không được vẽ."""
    page = page_text()
    assert "REFRESH_COOLDOWN_SECONDS=60" in page
    assert "dashboard_cache.py" in page, "hằng số soi chiếu server phải có comment trỏ nguồn"
    observed = run(page, r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({status:"ready",refreshing:false,last_error_code:null,snapshot:null,items:[],page:1,page_size:50,total:0})});
const button=document.getElementById("refreshButton");
globalThis.__test.postRefresh().then(()=>{
  process.stdout.write(JSON.stringify({disabled:button.disabled,text:button.textContent}));
});
""")
    assert observed["disabled"] is True
    assert "60" in observed["text"] or "Chờ" in observed["text"]
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "first_load_shows or stale_error_line or refresh_button_counts"
```
Kỳ vọng: ba FAIL.

- [ ] **Step 3: Thêm markup**

Ở dòng 18, sau `<span id="updatedAt" class="muted">Chưa cập nhật</span>` thêm:

```html
<span id="staleErrorLine" class="status bad" hidden></span>
```

Ở dòng 22, ngay sau `<main id="dashboardMain" class="main" tabindex="-1">` thêm:

```html
<div id="firstLoadBlock" class="first-load" hidden><strong>Đang lấy dữ liệu lần đầu từ Langfuse.</strong><p>Việc này mất vài phút. Trang tự cập nhật khi xong — không cần tải lại.</p></div>
```

- [ ] **Step 4: Thêm hằng số cooldown và hàm đếm ngược**

Chèn thành dòng mới ngay trước `postRefresh` (dòng 101):

```javascript
      // Soi chiếu _MANUAL_REFRESH_COOLDOWN ở dashboard_cache.py:21. Envelope không mang next_manual_refresh_at nên đồng hồ chạy phía client: reload trang là mất, và cooldown do đường lỗi server đặt thì client không biết.
      const REFRESH_COOLDOWN_SECONDS=60;
      function startRefreshCooldown(){const button=$("refreshButton");let remaining=REFRESH_COOLDOWN_SECONDS;button.disabled=true;setText("refreshButton",`Chờ ${remaining}s`);const tick=()=>{remaining-=1;if(remaining<=0){button.disabled=false;setText("refreshButton","Làm mới ngay");return}setText("refreshButton",`Chờ ${remaining}s`);window.setTimeout(tick,1000)};window.setTimeout(tick,1000)}
```

- [ ] **Step 5: Gọi cooldown trong `postRefresh`**

Trong dòng 101, sau `applyEnvelope(envelope);` thêm `startRefreshCooldown();`.

- [ ] **Step 6: Xử lý bốn trạng thái trong `applyEnvelope`**

Thay toàn bộ dòng 99 bằng:

```javascript
      function applyEnvelope(envelope){const snapshot=envelope&&envelope.snapshot,status=envelope&&envelope.status,errorCode=envelope&&envelope.last_error_code,errorAt=envelope&&envelope.last_error_at,block=$("firstLoadBlock"),errorLine=$("staleErrorLine");if(errorCode){errorLine.hidden=false;setText("staleErrorLine",`Lần cập nhật ${errorAt?new Date(errorAt).toLocaleTimeString("vi-VN"):"gần nhất"} thất bại (mã ${errorCode}). Đang hiển thị dữ liệu cũ.`)}else{errorLine.hidden=true;setText("staleErrorLine","")}if(!snapshot){block.hidden=false;$("dashboardMain").setAttribute("aria-busy","true");setText("liveStatus",status==="loading"||status==="refreshing"?"Đang lấy dữ liệu lần đầu từ Langfuse; việc này mất vài phút":"Đang lấy dữ liệu lần đầu từ Langfuse; chưa có số nào để hiển thị");return}block.hidden=true;$("dashboardMain").setAttribute("aria-busy","false");if(!state.snapshot||state.snapshot.generated_at!==snapshot.generated_at)state.ticketPage=1;state.snapshot=snapshot;clearInvalidActiveWeek(currentView());setText("updatedAt",`Cập nhật lúc ${updated(snapshot)}`);setText("liveStatus",status==="stale_error"?"Đang hiển thị dữ liệu gần nhất; lần cập nhật mới thất bại":status==="refreshing"?"Đang lấy dữ liệu mới từ Langfuse":"Dữ liệu sẵn sàng");$("statusChip").className=status==="stale_error"?"status warn":status==="refreshing"?"status":"status good";renderDashboard();loadTickets().catch(()=>renderTickets({items:[]}))}
```

Chuỗi `Cập nhật lúc` vẫn đúng 1 lần → tổng `Cập nhật` toàn trang vẫn 2.

- [ ] **Step 7: Thêm CSS**

Ở dòng 11, cuối:

```css
.first-load{max-width:var(--content-max);margin:32px 0;padding:24px;border:1px solid var(--line);background:var(--subtle)}.first-load p{margin:8px 0 0;color:var(--muted)}.first-load[hidden]{display:none}
```

- [ ] **Step 8: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh. `test_p4_responsive_sticky_shell...` (dòng 147) chạy `DOMContentLoaded` với `snapshot:null` — nhánh mới trả về sớm, nhưng test đó chỉ đọc `--sticky-offset`, `howToReadPanel`, `resetFilters`. Nếu vỡ thì **dừng và báo**, đừng sửa test đó.

- [ ] **Step 9: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥707 pass, exit 0.

---

## Task 15: Gom filter Ticket Explorer thành 3 nhóm, mọi control 44px

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:33` (markup `#tickets`), `:11` (CSS)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: `ticketSelectFilters`, `ticketBooleanFilters` (dòng 40) — **không đổi**. `buildTicketQuery` đọc theo `id`, mọi `id` phải giữ nguyên.
- Produces: ba `<fieldset>` có `<legend>`: `Định danh` · `Kết quả` · `Phân loại`. Nút `Lọc ticket` + `Xuất CSV` trong `.filter-actions` cuối form.

Đo được: 11 control bề rộng lệch nhau 64→332px; 31 tap target dưới 44px ở `390x844`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_ticket_filters_are_grouped_and_every_control_has_a_44px_touch_target():
    """11 control rải rác bề rộng 64-332px; 31 tap target dưới 44px trên điện thoại."""
    page = page_text()
    legends = re.findall(r"<legend>([^<]+)</legend>", page)
    assert legends == ["Định danh", "Kết quả", "Phân loại"]
    assert "repeat(auto-fit,minmax(200px,1fr))" in page
    assert re.search(r"#ticketFilters [^{]*\{[^}]*min-height:44px", page)
    for control_id in (
        "ticketIdInput", "outcomeInput", "issueCategoryInput", "appInput",
        "productCodeInput", "skillInput", "intentInput", "tpeCodeInput",
        "gt4TurnInput", "transferredInput", "weekendInput",
    ):
        assert f'id="{control_id}"' in page, "id phải giữ — buildTicketQuery đọc theo id"
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py::test_ticket_filters_are_grouped_and_every_control_has_a_44px_touch_target
```
Kỳ vọng: FAIL ở `legends == [...]`.

- [ ] **Step 3: Thay markup form**

Ở dòng 33, thay `<form id="ticketFilters" class="ticket-controls">...</form>` bằng:

```html
<form id="ticketFilters" class="ticket-filters"><fieldset class="filter-group"><legend>Định danh</legend><div class="filter-fields"><label>Ticket ID <input id="ticketIdInput" inputmode="numeric" pattern="[1-9][0-9]{0,19}"></label></div></fieldset><fieldset class="filter-group"><legend>Kết quả</legend><div class="filter-fields"><label>Outcome <select id="outcomeInput"><option value="">Tất cả</option><option value="ai_end_to_end">AI xử lý trọn</option><option value="ai_then_cs">AI trả lời rồi chuyển CS</option><option value="direct_cs">Chuyển CS ngay từ đầu</option><option value="unclassified">Chưa phân loại</option></select></label><label>Đã chuyển CS <select id="transferredInput"><option value="">Tất cả</option><option value="true">Có</option><option value="false">Không</option></select></label><label>&gt;4 turn <select id="gt4TurnInput"><option value="">Tất cả</option><option value="true">Có</option><option value="false">Không</option></select></label></div></fieldset><fieldset class="filter-group"><legend>Phân loại</legend><div class="filter-fields"><label>Nhóm vấn đề <select id="issueCategoryInput"><option value="">Tất cả</option></select></label><label>App <select id="appInput"><option value="">Tất cả</option></select></label><label>Nghiệp vụ <select id="productCodeInput"><option value="">Tất cả</option></select></label><label>Skill <select id="skillInput"><option value="">Tất cả</option></select></label><label>Intent <select id="intentInput"><option value="">Tất cả</option></select></label><label>Mã TPE <select id="tpeCodeInput"><option value="">Tất cả</option></select></label><label>Bắt đầu cuối tuần <select id="weekendInput"><option value="">Tất cả</option><option value="true">Có</option><option value="false">Không</option></select></label></div></fieldset><div class="filter-actions"><button class="button primary" type="submit">Lọc ticket</button><button id="ticketCsvButton" class="button" type="button">Xuất CSV kết quả đang lọc · tối đa 1.000</button></div></form>
```

Mọi `id` giữ nguyên. Thứ tự DOM đổi — `buildTicketQuery` đọc theo `id`, không theo thứ tự, nên an toàn.

- [ ] **Step 4: Thêm CSS**

Ở dòng 11, cuối:

```css
.ticket-filters{display:grid;gap:12px;margin:8px 0}.filter-group{margin:0;padding:12px;border:1px solid var(--line)}.filter-group legend{padding:0 4px;color:var(--muted);font-size:12px;font-weight:750;letter-spacing:.02em}.filter-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}.filter-fields label{display:grid;gap:4px;min-width:0;font-size:12px;font-weight:650}#ticketFilters input,#ticketFilters select,#ticketFilters .button{min-height:44px;max-width:100%;min-width:0}.filter-actions{display:flex;gap:12px;flex-wrap:wrap}.button,.toggle button,.tab,.navrow a,summary{min-height:44px;display:inline-flex;align-items:center}.navrow a{padding:0 4px}
```

Cảnh báo: `min-height:44px` cho `.button` làm topbar cao thêm. **Làm Task 16 ngay sau, đừng đo sticky ở giữa hai task.**

- [ ] **Step 5: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh, kể cả toàn bộ `test_p5_*`.

- [ ] **Step 6: CHECKPOINT**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥708 pass, exit 0.

---

## Task 16: Thu thanh cố định và hoàn thiện "Cách đọc"

**Files:**
- Modify: `src/weekly_cs_report/static/index.html:17-21` (topbar), `:24` (`howToReadPanel`), `:10` (CSS)
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: `--sticky-offset` (giữ), `--table-sticky-top` (T1).
- Produces: nav và chips chuyển ra **ngoài** `.topbar` (không sticky, cuộn cùng trang). **Không đổi thân hàm `syncStickyOffset`** — bị `test_p4_dom_contract_and_security_surface:103` so chuỗi nguyên văn và `.style.` count = 1. Nó vẫn đo `.topbar`, mà `.topbar` giờ chỉ còn một tầng.

Đo được: sticky `132px` = 18% chiều cao khả dụng desktop, `276px` = **33%** viewport mobile.

- [ ] **Step 1: Viết test thất bại**

```python
def test_sticky_bar_is_one_tier_and_nav_scrolls_with_the_page():
    """276px sticky = một phần ba màn hình điện thoại là thanh cố định."""
    page = page_text()
    assert re.search(r"\.topbar\{[^}]*max-height:96px", page)
    assert re.search(r"max-width:768px\)\{[^@]*\.topbar\{[^}]*max-height:120px", page)
    assert re.search(r"</header>\s*<nav id=\"sectionNav\"", page), "nav phải nằm ngoài header sticky"
    assert 'document.documentElement.style.setProperty("--sticky-offset",`${height}px`)' in page
    assert page.count(".style.") == 1


def test_how_to_read_covers_every_thing_a_new_reader_must_know():
    """Không có nó thì mọi câu hỏi đều đổ về PO."""
    page = page_text()
    panel = re.search(r'<aside id="howToReadPanel".*?</aside>', page, re.S).group(0)
    for phrase in (
        "AI xử lý trọn", "AI trả lời rồi chuyển CS", "Chuyển CS ngay từ đầu", "Chưa phân loại",
        "eopen", "Chất lượng DL", "gần thời gian thực, không phải real-time",
    ):
        assert phrase in panel, f"thiếu: {phrase}"
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "sticky_bar_is_one_tier or how_to_read_covers"
```
Kỳ vọng: cả hai FAIL.

- [ ] **Step 3: Đưa nav và chips ra ngoài header**

Ở dòng 17-21, đổi lồng nhau (giữ nguyên nội dung bên trong từng khối):

từ
```html
<header class="topbar">
  <div class="toolbar">…</div>
  <nav id="sectionNav" class="navrow" …>…</nav>
  <div id="activeFilterChips" class="chips" aria-live="polite"></div>
</header>
```
thành
```html
<header class="topbar">
  <div class="toolbar">…</div>
</header>
<nav id="sectionNav" class="navrow" aria-label="Điều hướng báo cáo">…</nav>
<div id="activeFilterChips" class="chips" aria-live="polite"></div>
```

`initialiseSectionNav()` dùng `document.querySelectorAll("#sectionNav a[href^='#']")` — không phụ thuộc vị trí.

- [ ] **Step 4: Chặn chiều cao topbar**

Ở dòng 10:

- `.topbar{position:sticky;top:0;z-index:4;margin:0 -24px;padding:8px 24px;…}` → thêm `max-height:96px;overflow:hidden`
- Trong `@media (max-width:768px)`: `.topbar{margin:0 -12px;padding:8px 12px}` → `.topbar{margin:0 -12px;padding:8px 12px;max-height:120px}`
- **Xoá** `.topbar>.toolbar{display:block}` và `.topbar>.toolbar>.toolbar{margin-top:8px}` (hai rule này là nguyên nhân topbar mobile cao 276px). Thay bằng `.topbar>.toolbar{flex-wrap:nowrap;overflow-x:auto;gap:8px}`
- `.topbar>.toolbar>.toolbar,.chips{max-width:100%}` giữ.

`overflow:hidden` trên `.topbar` là lưới an toàn; nội dung một tầng luôn thấp hơn.

- [ ] **Step 5: Viết lại "Cách đọc"**

Ở dòng 24, thay `<aside id="howToReadPanel" …>…</aside>` bằng:

```html
      <aside id="howToReadPanel" class="panel" tabindex="-1" hidden><strong>Cách đọc</strong><dl class="weekly-definitions"><dt>AI xử lý trọn</dt><dd>AI kết thúc ticket mà không chuyển CS.</dd><dt>AI trả lời rồi chuyển CS</dt><dd>AI có phản hồi thực chất trước khi bàn giao cho CS.</dd><dt>Chuyển CS ngay từ đầu</dt><dd>CS nhận ticket ngay, không có phản hồi AI thực chất trước đó.</dd><dt>Chưa phân loại</dt><dd>Không đủ tín hiệu để xếp vào ba nhóm trên.</dd><dt>Reopen sau AI First</dt><dd>Ticket AI First bị mở lại. Tỷ lệ chỉ hiện khi cohort đã đủ 7 ngày; tuần chưa đủ hiện dấu gạch, không hiện 0.</dd><dt>Chất lượng DL</dt><dd>Điểm tổng hợp coverage các chiều phân loại. Điểm thấp nghĩa là một phần ticket thiếu dữ liệu để phân loại, không phải metric sai.</dd><dt>WTD</dt><dd>Tuần đang chạy, chưa đủ tuần nên không so sánh trực tiếp với tuần hoàn chỉnh.</dd><dt>TPE và guardrail</dt><dd>TPE là mã trạng thái giao dịch; guardrail là luật an toàn/điều phối. Chuyển CS vì TPE và vì guardrail xử lý khác nhau hoàn toàn.</dd><dt>Độ mới của số</dt><dd>Dữ liệu là gần thời gian thực, không phải real-time: cache 5 phút, refresh nền khoảng 2 phút. Nút làm mới có thời gian chờ 60 giây tính phía trình duyệt — tải lại trang thì đồng hồ chờ mất.</dd></dl></aside>
```

- [ ] **Step 6: Chạy test**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```
Kỳ vọng: xanh. `test_p4_responsive_sticky_shell...` chờ `initialOffset === "91px"` từ `topbar._rect={height:91}` cứng trong harness, không phụ thuộc CSS thật.

- [ ] **Step 7: CHECKPOINT LÔ 4**

```bash
.venv/bin/pytest -q
```
Kỳ vọng: ≥710 pass, exit 0.

**DỪNG, báo Claude đo nghiệm thu cuối.**

---

## Nghiệm thu cuối — Claude chạy, ghi vào report

Chín tiêu chí spec §9.

- [ ] **1. Test**

```bash
.venv/bin/pytest -q
```
Ngưỡng: ≥687 pass, exit 0.

- [ ] **2. Ba câu hỏi §5.2 trong 10 giây ở 1440×900, không cuộn**

```js
(() => {
  const bottom = node => node ? Math.round(node.getBoundingClientRect().bottom) : null;
  const strip = document.getElementById("attentionStrip");
  return {
    innerHeight: window.innerHeight,
    kpiBottom: bottom(document.getElementById("kpiGrid")),
    stripHidden: strip.hidden,
    stripBottom: strip.hidden ? null : bottom(strip),
    dqVisible: bottom(document.getElementById("dqBadge")) < window.innerHeight,
    deltaTexts: Array.from(document.querySelectorAll(".kpi-delta")).map(n => n.textContent)
  };
})()
```
Ngưỡng: `kpiBottom < innerHeight` · `stripHidden === true` hoặc `stripBottom < innerHeight` · `dqVisible === true` · mọi `.kpi-delta` có nội dung, không `NaN`, không rỗng.

- [ ] **3. Bốn trạng thái vận hành đều có hình thức** — gọi `applyEnvelope` với bốn envelope qua `evaluate_script`, chụp ảnh mỗi trạng thái.

- [ ] **4-6. Số đo DOM ở hai viewport**

```js
(() => {
  const tap = Array.from(document.querySelectorAll("a,button,input,select,summary")).filter(node => {
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && (rect.height < 44 || rect.width < 44);
  });
  const offset = wrap => {
    const th = wrap && wrap.querySelector("th");
    return th ? Math.round(th.getBoundingClientRect().top - wrap.getBoundingClientRect().top) : null;
  };
  return {
    stickyHeight: Math.ceil(document.querySelector(".topbar").getBoundingClientRect().height),
    tapTargetsUnder44: tap.length,
    tapOffenders: tap.slice(0, 8).map(node => `${node.tagName}#${node.id || node.className}`),
    pageOverflowX: document.documentElement.scrollWidth > window.innerWidth,
    weeklyThOffset: offset(document.getElementById("weeklyTableScroll")),
    explorerThOffset: offset(document.querySelector(".explorer-table"))
  };
})()
```
Ngưỡng: `weeklyThOffset === 0` và `explorerThOffset === 0` · `tapTargetsUnder44 === 0` ở `390×844` · `stickyHeight <= 96` desktop / `<= 120` mobile · `pageOverflowX === false` cả hai viewport.

- [ ] **7. Quét PII**

```bash
curl -s http://127.0.0.1:8765/api/dashboard | grep -cE 'UserID|TransID|traceId|sessionId'
curl -s 'http://127.0.0.1:8765/api/tickets?page=1&page_size=50' | grep -cE 'UserID|TransID|traceId|sessionId'
```
Ngưỡng: cả hai `0`.

- [ ] **8. Validator palette** — chạy lại hai cặp, dán output. Ngưỡng: PASS 5/5 cả hai.

- [ ] **9. "Cách đọc"** — mở panel, xác nhận đủ 4 định nghĩa outcome, reopen, badge chất lượng, và câu "gần thời gian thực, không phải real-time".

Tiêu chí nào không đạt: ghi vào report **số đo thật**, không ghi "gần đạt". Chưa đủ 9/9 thì chưa được nói đã sẵn sàng giao user.

## Ngoài phạm vi plan này

- Deploy, image, domain, SSO.
- Chạy pipeline gán nhãn `reopen_reason` để lấp `labeled 0/93` — việc backend, spec khác.
- Bổ sung 15 mã TPE vào taxonomy — việc cấu hình. Plan này chỉ **hiện** lỗ hổng đó ở dải "Cần xử lý".
- Đổi cấu trúc thông tin sang tab/route — cần sửa `SPEC-v2` §5 trước.
- Bảng tuần mặc định 8 cột (spec §3.4). Hiện desktop 14 cột / mobile 6 cột đã có sẵn qua `compact-hide` + `mobileColumns`. Thêm bậc "desktop 8 cột" cần class thứ ba và một quyết định chọn 2 cột nào ngoài 6 cột mobile — chưa có cơ sở, để PO chốt rồi làm sau. Ghi rõ để không ai tưởng đã xong.
- Dark mode chưa kiểm bằng mắt trên thiết bị thật; plan chỉ pin giá trị đã qua validator.
