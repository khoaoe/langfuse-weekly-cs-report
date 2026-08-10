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

```
Palette (light, surface #fcfcfb, categorical): 2 slots
  [PASS] Lightness band         all 2 inside L 0.43–0.77
  [PASS] Chroma floor           all 2 >= 0.1
  [PASS] CVD separation         worst adjacent #A45F00↔#0068FF ΔE 33.0 (protan) · tritan 24.1
  [PASS] Normal-vision floor    worst adjacent #A45F00↔#0068FF ΔE 36.1 (normal)
  [PASS] Contrast vs surface    all 2 >= 3:1

  → ALL CHECKS PASS  (CVD in the 6–8 floor band is legal ONLY with secondary encoding: direct labels, gaps, or texture)
  scope: categorical palettes only. For a lone status/text color check WCAG text contrast; for a sequential ramp, lightness monotonicity.


Palette (dark, surface #1a1a19, categorical): 2 slots
  [PASS] Lightness band         all 2 inside L 0.48–0.67
  [PASS] Chroma floor           all 2 >= 0.1
  [PASS] CVD separation         worst adjacent #B07A2E↔#3B86E8 ΔE 26.4 (protan) · tritan 21.5
  [PASS] Normal-vision floor    worst adjacent #B07A2E↔#3B86E8 ΔE 27.8 (normal)
  [PASS] Contrast vs surface    all 2 >= 3:1

  → ALL CHECKS PASS  (CVD in the 6–8 floor band is legal ONLY with secondary encoding: direct labels, gaps, or texture)
  scope: categorical palettes only. For a lone status/text color check WCAG text contrast; for a sequential ramp, lightness monotonicity.
```

## Lô 1

### Codex checkpoint — 2026-07-30

- Task 0: `scripts/validate_palette.js` đã có trong repo; hai palette hai màu ở trên PASS toàn bộ 5 tiêu chí khi chạy:
  - `node scripts/validate_palette.js '#0068FF,#A45F00' --mode light --surface '#fcfcfb'`
  - `node scripts/validate_palette.js '#3B86E8,#B07A2E' --mode dark --surface '#1a1a19'`
- Task 1: header bảng dùng `--table-sticky-top:0` trong chính container cuộn.
- Task 2: trend chỉ bố trí các tuần có dữ liệu, không còn `preserveAspectRatio="none"`, và canary vẫn giữ đường đứt tại tuần rỗng.
- Task 3: các tuần rỗng liền kề được gộp thành một dòng có thể mở; tuần rỗng nằm giữa hai tuần dữ liệu vẫn giữ đúng vị trí.
- Task 4: cột đầu được ghim; gợi ý còn nội dung ngang dùng bốn lớp gradient CSS, không thêm listener JavaScript.
- Sáu contract test của Lô 1 đều pass:
  - `test_sticky_table_headers_pin_to_zero_inside_scroll_containers`
  - `test_trend_places_first_data_week_at_the_left_edge_and_scales_to_render_box`
  - `test_trend_still_refuses_to_bridge_a_missing_week_after_filtering`
  - `test_weekly_table_collapses_a_run_of_empty_weeks_into_one_row`
  - `test_weekly_table_keeps_an_interior_empty_week_in_place`
  - `test_first_table_column_is_pinned_and_scroll_has_a_visible_hint`
- Targeted checkpoint Lô 1: `6 passed`, exit 0.
- Full suite tại checkpoint Lô 1: 728 test được collect, exit 0.
- `page.count(".style.") == 1`.

### Đo DOM sau Lô 1

Chưa đo trong phiên Codex này. Theo phân vai của plan, Claude cần đo `thOffsetFromWrapTop`, `trendFirstBarX`, `weeklyRowCount`, `pageOverflowX` và `stickyHeight` ở desktop/mobile trước khi ghi kết quả trực quan.

## Lô 5 — lớp thẩm mỹ

- Stack giữ đúng kiến trúc CSP: semantic HTML, CSS custom properties, JavaScript thuần và SVG đều inline; không thêm dependency hay asset ngoài.
- `DÒNG TUẦN` mã hóa bốn outcome bằng độ dài, có mốc AI First và cung reopen nét đứt; tuần chưa đủ cohort không bị vẽ thành reopen `0`.
- Palette ba màu light/dark đều PASS 5/5; contrast nhãn `--accent-2` là `5.96:1` ở light và `6.34:1` ở dark.
- Năm contract test mới của Lô 5 đều pass; `tests/test_frontend_contract.py` đạt `62 passed`.
- Full suite cuối phiên: `765 passed in 14.70s`, exit 0.
- Static safeguards: `.style.` = 1; `<style>` = 1; `<script>` = 1; không `style=`, không unsafe DOM API, không URL ngoài trừ SVG namespace; CSS font-size chỉ còn `{12,14,18,34}`.
- Chưa đo DOM hoặc kiểm trực quan desktop/mobile trong phiên Codex này.
