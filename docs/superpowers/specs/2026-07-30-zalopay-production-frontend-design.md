# Spec — Zalopay production frontend candidate

## 1. Outcome

Thay presentation layer inline hiện tại bằng một React SPA được build và đóng
gói cùng FastAPI. Backend, metric, payload, privacy và refresh semantics giữ
nguyên theo [`../../SPEC-v2.md`](../../SPEC-v2.md).

Bản build là production candidate cho tới khi UXD/Design System phê duyệt
component mapping hoặc deviation.

## 2. Design contract

### Mode và thesis

- Mode: Operate.
- Direction: **Sổ điều hành tuần**.
- First viewport phải trả lời trong 10 giây: AI xử lý bao nhiêu, điều gì đang
  hỏng, dữ liệu có đáng tin hay không.
- Chữ ký thị giác là một decision ledger liền mạch, không phải bốn card SaaS.
- Xóa “DÒNG TUẦN”; giữ trình tự trạng thái → báo cáo → so sánh → chẩn đoán →
  chi tiết.

### Brand

- User-facing literal duy nhất: `Zalopay`.
- Logo không dựng lại; light dùng horizontal full-color, dark dùng white mark.
- Aeonik Pro 400/500/700 self-hosted WOFF2; số KPI dùng Medium 500 và
  `tabular-nums`.
- Light tokens: blue `#0033C9`, green `#00CF6A`, canvas `#F4F7FC`, surface
  `#FFFFFF`, ink `#111418`, muted `#5B6573`, rule `#D9E1EC`, success text
  `#006B3A`, warning `#FF8A00`, critical `#B42318`.
- Dark tokens: canvas `#0D1117`, surface `#151B23`, text `#E9EEF5`, rule
  `#2D3540`, interactive blue `#6685DF`, green `#00CF6A`.
- Không dùng white text trên brand green; không dùng color-only status.

### Composition

1. Sticky app shell: logo, product name, cohort, data-quality badge, updated
   time, refresh, section navigation, reset, help and active filters.
2. Dynamic title and deterministic narrative.
3. Four-cell decision ledger: AI First, total CS transfer, reopen after AI
   First, and `>4 turn` without CS.
4. Action rail with only actionable warnings.
5. Weekly Report table with 14 columns, Copy and CSV.
6. Aligned volume/rate trends; segment table; transfer diagnostics; rule
   compliance; data quality; Ticket Explorer.

At 1440×900 sections ① and ② fit vertically above the fold. Weekly rows are
about 32px high. Header and first column are sticky inside the local scroller.

At 390×844 there is no global horizontal overflow. The ledger becomes 2×2;
navigation and tables scroll locally. Weekly Report initially exposes six core
columns and an explicit “Xem đủ cột” control.

### Interaction and states

- Four runtime states: loading, ready, refreshing, stale_error.
- Refreshing and stale_error retain last-good data.
- Empty weeks say “Không có dữ liệu”; reopen not mature uses `—` plus
  explanation.
- Motion is limited to 120–180ms state transitions and respects reduced motion.
- Dark mode follows `prefers-color-scheme`; no theme toggle.
- Semantic tables, visible focus, live regions, chart title/description/caption
  and 44px mobile targets are mandatory.

## 3. Current implementation baseline

Đây là baseline đang được triển khai và kiểm thử, không phải khóa công nghệ
vĩnh viễn:

- Node 24 LTS, npm 11, React 19.2, TypeScript 5.9, Vite 8.1.
- TanStack Query 5, TanStack Table 8, Zod 4 và modular Visx 4
  (`@visx/scale`, `@visx/shape`).
- Native HTML và CSS Modules plus global CSS custom properties đang được dùng
  vì phù hợp với strict CSP và semantic accessibility.
- Vitest, React Testing Library, MSW, Playwright and axe.
- Initial JavaScript ≤250KB gzip, CSS ≤80KB gzip, fonts ≤300KB total.

Charting không bị khóa vào native SVG hoặc Visx. Source hiện dùng
`scaleBand`/`scaleLinear` và `Bar`/`LinePath` của modular Visx bên trong native
semantic SVG, đồng thời giữ `<title>`/`<desc>`/caption và interaction targets.
Production build, data-gap và interaction tests của migration này đã pass
trong budget. Engineering chỉ giữ Visx khi bằng chứng tổng thể tiếp tục tốt hơn
hoặc bằng giải pháp thay thế; accessibility, CSP và release gates vẫn áp dụng
cho mọi thay đổi sau đó.

Framework hoặc library có thể thay đổi khi không mở rộng product scope và vẫn
vượt toàn bộ API/privacy, accessibility, visual, performance, packaging và
rollback gates. External CDN vẫn bị cấm theo security contract, không phải vì
preference về stack.

Vite emits a hashed static bundle into the Python package build area. FastAPI
serves the selected SPA or legacy page with
`DASHBOARD_FRONTEND_MODE=legacy|spa`. HTML is no-store; hashed assets are
private/immutable. Production CSP permits only same-origin script, style, font,
image and API connections and forbids inline script/style attributes.

## 4. Compatibility

- API payload and semantics remain unchanged.
- Preserve `weekly-cs-ticket-columns-v1`.
- Preserve the §5.18 DOM IDs for one release as compatibility hooks while tests
  migrate from source-string assertions to accessible behavior.
- Keep current inline UI at `static/legacy/index.html` for one rollback window.
- Do not touch LLM/reopen work outside the frontend scope.

## 5. Release gates

- Frontend coverage ≥80%; Python suite remains green.
- Desktop/mobile light/dark visual, keyboard, axe, CSP, external-network and
  overflow checks pass.
- Privacy deny-list and API semantic parity pass.
- Copy/CSV exports retain exact 14-column behavior.
- At least two CS users complete the defined task test.
- UXD/Brand Owner closes Design System mapping/deviation before the release is
  called official.
- Docker image behavior is verified in a runtime where Docker is available.
