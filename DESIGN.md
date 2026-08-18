# Design System

## Status

**Production candidate.** This document records the brand and surface contract
as it is actually implemented in `frontend/src`, measured from the shipped
build — not from intent. It is not "official": UXD/Brand Owner and Design
System Owner acceptance has not been performed. See §Deviations.

Updated on 2026-08-18 against `frontend/src` and storage/browser schema v21.

## Direction

- Visitor mode: Operate.
- World: **Sổ điều hành tuần** — one continuous operational ledger surface with
  hard alignment, compact rows and restrained brand accents.
- Signature: the four-cell decision ledger directly beneath the dynamic title,
  sharing a single frame.
- Refusal: generic SaaS card mosaic, ornamental gradients, glass, large-radius
  cards, donut/gauge charts, dual-axis charts and decorative motion.
- Approved comp: `.impeccable/mocks/weekly-ledger-c-approved.png`.

## Brand assets — as shipped

| Asset | File | Bytes | Use |
|---|---|---:|---|
| Horizontal full-colour logo | `assets/brand/logos/zalopay-logo-color.png` | 33 784 | light shell |
| Horizontal white logo | `assets/brand/logos/zalopay-logo-white.png` | 29 523 | dark shell |
| App icon | `assets/brand/icons/zalopay-app-icon.png` | 33 238 | favicon |
| Z graphic, light shell | `assets/brand/graphics/zalopay-z-light.png` | 32 195 | right shell edge |
| Z graphic, dark shell | `assets/brand/graphics/zalopay-z-dark.png` | 31 497 | right shell edge |

The build imports these project-local files; `frontend/src/assets/` no longer
duplicates them. `assets/brand-provenance.json` pins the canonical source path
and hashes for the complete Zalopay asset inventory. The PNG files are exact
copies from `../docs/zalopay-guideline`. The OTF files under
`assets/brand/fonts/source/` are also exact copies and are retained only as
reproducible inputs; they are not browser assets. The three WOFF2 files under
`assets/brand/fonts/web/` are deterministic outputs of
`scripts/generate_brand_fonts.py`. This manifest contains 11 files.

`scripts/verify_brand_assets.py --require-canonical` performs a live audit when
the sibling guideline directory is available. A standalone CI checkout proves
the pinned Zalopay and third-party manifests, project hashes, inventory,
references and budget, not a new read of the external guideline or a fresh
download from the Langfuse URL.

The shell-edge graphics are official analogous Z assets: light uses canonical
`png/visual-42.png`, dark uses `png/visual-43.png`. The graphic appears once,
is cropped only at the publication's right edge on wide screens, and is never
CSS-recoloured. It is decorative (`aria-hidden="true"`, `alt=""`). This
replaces the earlier crop of the horizontal logo, which was not an approved
decorative use.

Theme resolution is system-first. On the first visit, or when no valid saved
choice exists, CSS follows `prefers-color-scheme`; the app shell then exposes a
visible `Sáng` / `Tối` control so the reader can override it. The resolved mode
is applied through `data-theme` on the document root and the only persisted
value is the non-sensitive literal `light` or `dark` under
`weekly-cs-theme-v1`. Missing, invalid or corrupt values fall back safely to
the system preference.

Both official logo variants and both official Z graphics are bundled
same-origin. CSS shows the variant for the resolved theme: full-colour logo and
light Z in light mode; white logo and dark Z in dark mode. Before hydration,
the system preference still selects the correct pair. The override uses no
inline script, inline style, external request or CSP relaxation.

The two horizontal logo variants share one fixed visual frame: `106×24px` on
desktop and `88×20px` at the compact breakpoint. Both are absolutely aligned
inside that frame with `object-fit: contain` and left-centre positioning, so a
theme switch cannot move the product title or reflow the brand lockup.

The logo `<img>` carries `alt=""` and the brand name is supplied by adjacent
text, so assistive technology announces `Zalopay` exactly once.

Logos are never redrawn, distorted, recoloured, outlined or shadowed. The
user-facing literal is always exactly `Zalopay`.

### Third-party integration asset

| Asset | File | Bytes | Use |
|---|---|---:|---|
| Official Langfuse colour icon | `assets/icons/langfuse-icon.svg` | 2 999 | compact Ticket-cell Tracing link |

This icon is not a Zalopay asset and is deliberately excluded from
`assets/brand-provenance.json`. `assets/third-party-provenance.json` records the
official source
`https://langfuse.com/brand-assets/icon/color/langfuse-icon.svg` and exact-copy
SHA-256. It is bundled same-origin; `assetsInlineLimit: 0` forces a hashed SVG
file instead of a data URL, and loading the dashboard never fetches it from
Langfuse. The `<img>` is decorative (`alt=""`, `aria-hidden="true"`); the
enclosing link carries the accessible name
`Mở các trace của ticket {ticketId} trên Langfuse trong thẻ mới`. The two
manifests together cover all 12 governed asset payload files in the curated
`assets/` store.

## Typography — as shipped

Aeonik Pro, self-hosted WOFF2, `font-display: swap`, three weights:

| Weight | File | Bytes |
|---|---|---:|
| Regular 400 | `assets/brand/fonts/web/aeonik-pro-regular.woff2` | 52 000 |
| Medium 500 | `assets/brand/fonts/web/aeonik-pro-medium.woff2` | 56 892 |
| Bold 700 | `assets/brand/fonts/web/aeonik-pro-bold.woff2` | 62 792 |

Total 171 684 B (167,7 KiB) against a 300 KB budget.

- Body 400; controls, KPI values and table data 500; headings 700.
- All numeric cells use `font-variant-numeric: tabular-nums`.
- Sentence case throughout; uppercase only where the source taxonomy requires it.

## Colour — as shipped (`frontend/src/styles/global.css`)

### Light

| Token | Value | Role |
|---|---:|---|
| `--brand-blue` | `#0033c9` | brand |
| `--brand-ink` | `#0033c9` | AI First ledger value |
| `--brand-green` | `#00cf6a` | non-text accent, selection fill with dark text |
| `--canvas` | `#f4f7fc` | application background |
| `--surface` | `#ffffff` | report surface |
| `--surface-sunken` | `#eef2f9` | table header, hover |
| `--ink` | `#111418` | primary text |
| `--muted` | `#5b6573` | secondary text (5,8:1 on surface) |
| `--rule` / `--rule-strong` | `#d9e1ec` / `#b9c6d8` | rules and borders |
| `--interactive` | `#0033c9` | links, selected controls |
| `--success-text` | `#006b3a` | accessible positive text |
| `--warning` / `--warning-text` | `#ff8a00` / `#7a4200` | warning mark / warning text (8,0:1) |
| `--critical` / `--critical-text` | `#b42318` / `#b42318` | actionable failure (6,6:1) |
| `--focus` | `#0033c9` | focus ring |

### Dark (system default or explicit `Tối`)

| Token | Value | Role |
|---|---:|---|
| `--canvas` | `#0d1117` | application background |
| `--surface` | `#151b23` | report surface |
| `--ink` | `#e9eef5` | primary text |
| `--muted` | `#9fadbf` | secondary text (7,6:1 on surface) |
| `--rule` / `--rule-strong` | `#2d3540` / `#3d4855` | rules and borders |
| `--interactive` | `#6685df` | links, selected controls |
| `--brand-ink` | `#6685df` | AI First ledger value (4,95:1) |
| `--success-text` | `#4ad991` | positive text |
| `--warning-text` | `#ffc978` | warning text (11,4:1) |
| `--critical-text` | `#ff9c93` | failure text (8,7:1) |
| `--focus` | `#8fa9ec` | focus ring |

### Chart series

Light `#0068ff` / `#a45f00`; dark `#3b86e8` / `#b07a2e`. These are the pairs
recorded in `AGENTS.md` as passing the `dataviz` validator 5/5.

Brand green is never paired with white text and never carries small text on
white. Colour never carries meaning alone: every toned value has a text label,
and every rail item states the measured condition plus its next action.
Critical rail items use critical tone, not a severity prefix.

## Layout — as shipped

- Content maximum 1600px; gutters 32 / 16 / 12px at desktop / tablet / mobile.
- Spacing scale 4, 8, 12, 16, 24, 32, 48px.
- Radius 0, 2 or 4px only.
- Elevation: one sticky-shell shadow. Report modules are separated by 1px rules.
- Weekly rows ≈ 32px on desktop.
- `body { overflow-x: hidden }`; tables own their overflow inside
  `.tableScroll` containers.
- Motion is limited to 120–180ms (`--duration: 140ms`) state transitions on
  controls. There is no entrance animation, and `prefers-reduced-motion`
  reduces every duration to 0,01ms.

### Surface composition

1. Sticky shell — logo, one official right-edge Z graphic, product name,
   weighted quality score badge, freshness, cohort toggle, visible `Sáng` /
   `Tối` theme control, refresh and section navigation.
2. Polite live region for runtime state.
3. Dynamic title + deterministic narrative.
4. Scope caption + four-cell decision ledger.
5. Action rail (only actionable warnings).
6. ① Weekly Report.
7. ② Trends, with one shared `Cùng kỳ đến Tn` / `Tuần đủ` control for both
   aligned panels when a same-period comparison is available. ③ `So sánh theo
   thuộc tính ticket` with Category / App / Product Code / Skill / Intent.
   ④ CSAT (`Mức hài lòng`). ⑤ Transfer and rule diagnostics. ⑥ Ticket Explorer.

The standalone "data quality" section (per-dimension `#dqBadge` breakdown) and
its own nav entry stay retired; they do not reappear here. The reader's "is
this data trustworthy" question is now answered by two narrower signals
instead of one section: the shell's `Độ tin cậy X/100` chip (item 1 above;
`calculateDataQualityScore` in `AppShell.tsx`) states one blended score, and
`selectCoverageNote()` (`selectors.ts`) names the single weakest coverage
dimension next to the decision ledger whenever any dimension falls under the
0,8 floor — never a full section of its own.

The segment caption is fixed product copy:

> Phân nhóm trực tiếp theo Category, App, Product Code, Skill hoặc Intent ghi nhận
> trong dữ liệu nguồn; không tự gộp hoặc diễn giải lại.

The cohort toggle order is fixed as `T2–T6`, then `T2–CN`; `T2–T6` is the
initial selection when the dashboard opens.

Measured at 1440×900: the ledger's last cell bottom is above the fold.
Measured at 390×844: the ledger is 2×2 and the Weekly Report starts in the
next viewport for both warning and healthy/no-warning fixtures. This is
enforced by a mobile `600px` decision minimum plus browser tests, not by a hard
`100svh` spacer.

## Components and states

- The current implementation prefers native semantic elements and CSS Modules
  because they meet the surface and CSP contracts with little runtime
  overhead. This is an implementation choice, not a permanent ban on a
  component or charting library. Any replacement must preserve semantic
  behavior and pass the same CSP, accessibility and bundle checks.
- No inline `style` prop is shipped because the production CSP forbids style
  attributes.
- Theme preference is the non-sensitive UI-only exception stored under
  `weekly-cs-theme-v1`. Dashboard snapshots, tickets and filters are never
  stored with it. The theme control reports both the current mode and the mode
  it will activate, remains keyboard-operable and keeps the global focus ring.
- Tables are semantic `<table>` with `<th scope="col">` / `<th scope="row">`.
  Descriptions are a paragraph above the scroller referenced by
  `aria-labelledby`, not `<caption>`, so the sticky header rests flush with the
  scroll container edge.
- Every data-table header is a native button with a visible `↕/↑/↓` indicator
  and `aria-sort`. Client-side aggregate tables sort immutable copies using raw
  values, Vietnamese natural text order, deterministic ties and null-last
  behavior in both directions.
- Weekly rows render newest-first by default and may be sorted in the view.
  Clipboard TSV starts directly with the 14 headers so it pastes as one
  rectangular table; CSV alone carries the fixed-width metadata row and UTF-8
  BOM. Both exports retain the governed newest-first row order and the rendered
  14-column order, independent of a temporary view sort.
- Ticket Explorer keeps `Ticket` as a mandatory row-header column. A valid
  Ticket ID is the visible Freshdesk deep link, with a compact official
  Langfuse icon link beside it in the same cell. The pair avoids a permanent
  utility column, retains one investigation identity, and exposes destination
  and new-tab behavior in accessible names. Invalid IDs remain text.
- Ticket header sort is server-global and announced through `aria-sort`.
  Filtering precedes sorting, sorting precedes pagination, missing values stay
  last in either direction, and equal values use numeric Ticket ID ascending.
  The CSV exporter walks the same ordered pages and caps only after the first
  1,000 globally sorted rows.
- Outbound link presentation is not export data. Ticket CSV always contains
  the raw Ticket ID and never contains the two URLs, icon, or accessible
  destination labels.
- Ticket Explorer labels the compatibility field `tpe_code` as `Transstatus`;
  it is populated only for a single unique source Transstatus. The companion
  `tpe_status` remains null and is not rendered.
- Sticky header `top: 0` and sticky first column `left: 0` are measured against
  the container's client origin, both 0px after scrolling.
- Runtime states: loading, ready, refreshing, stale_error. Refreshing and
  stale_error keep the last-good snapshot; the server error code never appears
  in user-facing text.
- The source-faithful TPE contract was introduced in storage schema v5. The
  current storage schema is v21; persisted older snapshots are ignored and
  refreshed, never converted in place. v4 additionally carries
  `code/status/step/case/mapped` semantics that are not equivalent to
  `transstatus/step_result`.
- Freshdesk entry coverage is a separate source-faithful section. Its aggregate
  flow is keyed by Freshdesk ticket creation week and its drill-down is a
  separate paginated endpoint. `invoked_no_result` and `not_observed_invoked`
  are distinct states; the latter is displayed as `Không thấy lần gọi
  CS-agent` and is observational, not causal. Only Freshdesk category 3 with
  `private=false` and `incoming=false` counts as a public agent reply.
  The aggregate declares `source_start_week=2026-07-06`; private inventory and
  per-ticket coverage checkpoints resume with owner-only files and are never
  served to the browser. A partial Freshdesk run never replaces the published
  cache.
- Empty data is explicit: an empty week renders "Không có dữ liệu" and "—",
  never 0. A trend needs ≥2 observed weeks or it says so instead of drawing.
- Volume and rate are two aligned panels, never one dual-axis chart. When the
  active cohort view carries `same_period`, one two-state control above both
  panels reads `Cùng kỳ đến Tn | Tuần đủ`, defaults to `Tuần đủ`, switches both
  panels together and resets to `Tuần đủ` after a cohort change. Same-period
  mode derives every plotted row from that view's `same_period.by_week` and
  states `Mọi tuần đều cắt tới thứ Năm để so cùng kỳ.` with the actual cutoff
  weekday. The current SVG output has `<title>` via `aria-labelledby`, `<desc>`
  via `aria-describedby`, a legend and a prose caption. A chart library must
  keep or improve that accessible output rather than replacing it with a
  canvas-only or pointer-only interaction.
- Focus is visible everywhere (`:focus-visible` 2px outline, 2px offset).
  Every interactive control is ≥44px tall on mobile, including the skip link.
- `Tới nội dung chính` always targets focusable `main#dashboardMain`, including
  loading state. Its fixed 280px scroll clearance keeps the focused landmark
  below the sticky shell down to the verified compact `320×568` viewport.
- TPE diagnostics state that its rows can overlap and are observations, not
  proven causes. Narrative wording is "Tín hiệu chuyển CS nổi bật…".
- The TPE diagnostic is a semantic table with exactly four columns:
  `Transstatus`, `Step result`, `Ticket`, `Tỷ trọng`. Its row grain is the
  source pair `(transstatus, step_result)` from
  `tool:get_transaction_processing_engine_data`; it does not read the legacy
  pipe in `meta["Step result"]`.
- Step result tokens are shown verbatim after boundary validation. Missing
  values read `Không có Step result`. The UI never renders `Case`, canonical
  status, mapped/unmapped state, a taxonomy warning or a self-authored meaning.
  A short line under the table reports the measured count, denominator and rate
  of transferred tickets missing Step result, followed by the concrete
  consequence that those cases cannot be traced to a failing step. "Phần lớn"
  is used only when the measured missing share exceeds 50%.
- A separate semantic table is titled `Lý do chuyển CS` and has exactly six
  columns in this order: `Lý do chuyển CS`, `Giá trị nguồn`, `Nguồn phát hiện`,
  `Skill`, `Ticket`, `Tỷ lệ`. Human wording is visually first; raw rule/source
  tokens use code styling for Dev.
- That table is an exclusive partition anchored to the first canonical transfer
  trace. The two `cs_escalation` paths remain visually distinct:
  `Skill đề xuất chuyển CS` from
  `skill_guardrail_checked · stage=output`, and
  `Phản hồi AI được nhận diện là cần chuyển CS` from `output_guardrail`.
  Unknown rows show `Chưa xác định được từ trace` and em dashes for raw fields.
  No trace or observation identifier reaches the DOM.
- Every header in the aggregate transfer-reason table is keyboard-sortable;
  default order is Ticket descending, missing technical values remain last.
  Ticket Explorer displays the same human label from the v15 `transfer_reason`
  enum, while raw trigger details stay aggregate-only.
- A refresh with partial enrichment is not a publishable production snapshot.
  The service keeps the last complete snapshot; before the first complete
  refresh it remains in `loading`/`not ready`. Therefore the user-facing
  `Chưa xác định được từ trace` label is reserved for a complete trace read,
  not a failed or timed-out enrichment lane. The service logs only the
  allowlisted failed lane names and observation count for diagnosis.
- A running-week narrative uses the active cohort view's same-period current
  row and baseline when available:
  `AI First 78,0% (627 ticket). Tính tới thứ Tư, cùng kỳ 4 tuần trước trung bình 74,2% — tuần này đang nhỉnh hơn 3,8 điểm.`
  and
  `Reopen sau AI First 18,8%, cùng kỳ 4 tuần trước 21,5%.`
  If the view has no valid same-period block, it states only the observed WTD
  values; it never compares a partial week with a full week.
- The `Cách đọc` panel explains the split between comparison charts and the
  governed table with fixed copy:
  `Với WTD, phần tóm tắt và biểu đồ chỉ so các tuần tới cùng ngày đã hoàn tất khi đủ baseline; bảng tuần vẫn giữ số thực của tuần.`
- The action rail contains only the `>4 turn`, structural gate and partial
  enrichment warnings. Skill coverage sits in the Skill tab; missing Step
  result coverage sits beside the transfer diagnostic it qualifies.

## Security posture of the surface

Served by FastAPI with `DASHBOARD_FRONTEND_MODE=spa|legacy`. The document is
`no-store`; hashed assets are `private, max-age=31536000, immutable` and sit
behind the same proxy authentication as `/` and `/api/*`. Production CSP:

```
default-src 'self'; base-uri 'none'; object-src 'none'; frame-src 'none';
frame-ancestors 'none'; form-action 'self'; connect-src 'self';
img-src 'self' data:; font-src 'self'; style-src 'self'; style-src-elem 'self';
style-src-attr 'none'; script-src 'self'; script-src-attr 'none';
worker-src 'none'; manifest-src 'none'; media-src 'none'
```

No `unsafe-inline`, no `unsafe-eval`, no CDN, and no third-party subresource or
`connect` request. The only external browser behavior is explicit user
navigation from a validated Ticket ID to a fixed Freshdesk ticket path or the
approved Langfuse Tracing view with its Session ID filter. Both links use
`target="_blank"` and `rel="noopener noreferrer"`; the document is served with
`Referrer-Policy: no-referrer`.

The Tracing URL derives a custom `dateRange={fromMs}-{toMs}` from the oldest
week with data through the end of the snapshot day in Vietnam time. This avoids
the one-day table default hiding older matching traces without imposing a
fixed-age cap.

The Langfuse href contains one reviewed non-secret navigation constant, project
routing ID `cmqubjzur000hz507ptubh2l9`. This is a narrow exception recorded in
`docs/SPEC-v2.md` §7: it may exist only in the frontend bundle and approved
href. No `traceId`, `observationId`, or additional Session ID value is added to
API responses, storage, local storage or exports. The approved filter grammar
contains the literal field name `sessionId`; its value reuses the already
approved Ticket ID.

## Measured budgets

| Budget | Limit | Measured |
|---|---:|---:|
| Initial JavaScript, gzip | 250 KB | 140,76 kB by Vite |
| CSS, gzip | 80 KB | 5,49 kB by Vite |
| Fonts, total | 300 KB | 167,7 KiB |
| Production source maps | 0 | 0 |

## Current charting choice — replaceable

The current implementation uses modular `@visx/scale` and `@visx/shape` for
band/linear scales, bars and line paths inside the existing semantic SVG shell.
It retains native `<title>`, `<desc>`, captions and interaction targets.
Production build, missing-week gap and chart interaction tests pass with the
measured budget above.

This evidence supports Visx for the current candidate; it does not make Visx a
permanent product constraint. A future implementation may replace it when the
same behavior, accessibility, CSP and bundle gates prove the replacement is
better.

## Deviations — open, not accepted

1. **Raster brand assets.** Logos, Z graphics and the favicon ship as PNG taken
   verbatim from the project store, whose hashes match
   `../docs/zalopay-guideline`. The AI/PDF artboards were inspected and can
   technically be converted, but crop, clearspace and production geometry
   cannot be certified here without Brand Owner approval. Replace with an
   official SVG export plus a visual comparison before calling the build
   official.
2. **Design System mapping unverified.** No Zalopay Design System source was
   available in this environment, so the token names and component mappings
   here are derived from the shipped artifact, not reconciled against the
   system.
3. **UXD / Brand Owner acceptance not performed.** No sign-off exists.
4. **Ledger scope is the latest observed week**, not the 12-week range. For a
   complete week, title, narrative and ledger describe that same population.
   For WTD with a valid same-period block, the first two narrative metrics use
   the explicitly labelled completed-day cutoff while the title and ledger keep
   the full observed WTD scope; the `Cách đọc` panel states this split. The
   governed full-week range remains in the Weekly Report.
5. **Dark-mode brand value colour deviates from brand blue.** `#0033c9` on
   `#151b23` measures 1,91:1. Dark mode uses `#6685df` (4,95:1). This needs
   Brand Owner confirmation.
6. **`stale_error` polls every 30s.** The spec defines 2s (loading/refreshing)
   and 5 min (stable) only; 30s was chosen so a failing backend is not
   hammered.
7. **Docker is not verified locally.** Docker cannot run in this environment.
   CI is configured to build the image and smoke-test a seeded snapshot,
   readiness and authenticated/unauthenticated routes, but no successful remote
   workflow run was observed here. Local contract tests and workflow syntax do
   not prove runtime image behaviour.
8. **No CS user task test.** The spec's release gate asks for at least two CS
   users to complete the defined task test; that has not happened.
9. Nhãn trạng thái TPE hiển thị bằng enum tiếng Anh (`SUCCESSFUL`, `FAILED_NFC`, ...)
   thay vì dịch sang tiếng Việt. Đi ngược SPEC-v2 §5.3 (cấm trộn nhãn tiếng Anh
   trong câu tiếng Việt) và ngược convention `DATA_QUALITY_LABELS`
   (`frontend/src/lib/data-quality.ts:5-8`). PO quyết định giữ tiếng Anh ngày
   2026-08-18 sau khi được trình bày cả hai điểm trên. Xem lại nếu có phản hồi
   từ người dùng CS.
10. `--critical: #b42318` (đã gỡ ở bản này) và `--critical-text: #b42318` là màu đỏ
    không có trong palette Zalopay — guideline không có màu đỏ nào. Giữ lại vì
    ngữ nghĩa cảnh báo, theo Product Principle 4.

## Rollback

`src/weekly_cs_report/static/legacy/index.html` is a byte-identical copy of the
inline page (sha256
`5206d0d6f39ffdc24295e257064fa6c5dbb1e9f0d062d157f3f776d98442d63d`). Setting
`DASHBOARD_FRONTEND_MODE=legacy` serves the inline page with its sha256-based
CSP, unchanged.

## Design direction audit

- Impeccable seed key: `92c02d21`.
- The user-approved direction overrides the random candidate assignment.
- Challenger grammar was rejected where it reduced product clarity or broke the
  Zalopay palette; only strict wayfinding at decision points carries forward.
