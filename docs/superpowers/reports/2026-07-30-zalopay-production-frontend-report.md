# Zalopay production frontend — verification evidence

Branch `codex/zalopay-production-frontend`. Recorded 2026-07-30, with a modular
Visx build addendum measured on 2026-07-31. Every number below is copied from a
command that was actually run in this environment.

## What changed

| Area | Files |
|---|---|
| Zod contract | `frontend/src/lib/dashboard-schema.ts` |
| Pure libraries | `frontend/src/lib/{format,narrative,runtime-state,ticket-columns,weekly-export,selectors,api}.ts` |
| Runtime | `frontend/src/hooks/useDashboardRuntime.ts` |
| Surface | `frontend/src/components/{AppShell,DecisionLedger,WeeklyReport,BelowFold,TicketExplorer,DashboardScreen}.tsx`, `dashboard.module.css` |
| Design tokens | `frontend/src/styles/global.css` |
| Entry | `frontend/index.html`, `frontend/src/main.tsx` |
| Delivery | `src/weekly_cs_report/web.py` |
| Rollback | `src/weekly_cs_report/static/legacy/index.html` |
| Packaging | `pyproject.toml`, `Dockerfile`, `.dockerignore`, `.gitignore` |
| Tests | `frontend/test/{report-sections,resilience}.test.tsx`, `frontend/e2e/dashboard.spec.ts`, `tests/test_spa_delivery.py`, `tests/test_deployment_contract.py` |
| Harness | `vite.config.ts`, `tsconfig.app.json`, `playwright.config.ts`, `scripts/e2e_server.py` |

Removed in that pass: `frontend/src/components/below-fold/{format,types,ticket-export}.ts`
and `frontend/src/components/TrendSection.{tsx,module.css}` — an unreviewed
parallel fork whose `formatInteger` turned a non-finite value into `0`, in
direct conflict with the "empty is never zero" rule. Its `@visx/visx` umbrella
dependency was removed at the same time. That cleanup was not a permanent
rejection of Visx or a requirement to keep hand-written SVG.

## Stack status

The stack in this report is the measured implementation baseline, not an
irrevocable product constraint. `package.json` now includes modular
`@visx/scale` and `@visx/shape`; the current chart source uses their
band/linear scales, bars and line paths inside the existing semantic SVG
shell. It retains keyboard interaction targets and accessible
`<title>`/`<desc>`/caption output. Production build, missing-week gap and chart
interaction tests pass; the bundle table below contains the post-migration
measurement. Visx remains replaceable if another implementation measures
better without weakening strict CSP, accessibility, interaction or bundle
contracts.

## Defects found and fixed during this pass

| # | Defect | Evidence | Fix |
|---|---|---|---|
| 1 | `data_quality.counts` schema required every quality label; Zod 4 treats `z.record(z.enum)` as exhaustive while `_validate_quality` only rejects *unknown* labels | `dashboard-schema.test.ts` RED | `z.partialRecord(QualityLabelSchema, …)` |
| 2 | `toStartWith` in `weekly-export.test.ts` is a Bun matcher and does not exist in Vitest | `Error: Invalid Chai property: toStartWith` | equivalent `csv.startsWith(...)` assertion |
| 3 | `npm run typecheck` was a no-op: the root tsconfig has `files: []` and `tsc --noEmit` does not follow project references | `tsc -p tsconfig.app.json --noEmit` behaved differently | script now targets the app project |
| 4 | Ticket bulk export did not catch a failed fetch — unhandled promise rejection and no operator feedback | Vitest unhandled rejection on a 422 | `try`/`catch` around the paged fetch |
| 5 | Chart `<desc>` was wired through `aria-labelledby`, so it was swallowed into the accessible *name* and the description was empty | `toHaveAccessibleDescription` RED | split into `aria-labelledby` + `aria-describedby` |
| 6 | Dark mode: `--brand-blue #0033c9` on `--surface #151b23` measures 1,91:1 | axe `color-contrast`, serious | `--brand-ink` overridden to `#6685df` (4,95:1) |
| 7 | Skip link was below the 44px mobile target | E2E target sweep | `min-height: 44px` |
| 8 | `<caption>` inside the scroll container pushed the sticky header 38px below the container edge | E2E sticky measurement | description moved outside the scroller, table named via `aria-labelledby` |
| 9 | Title and narrative described the latest week while the ledger described the 12-week range — two unlabelled scopes side by side | desktop screenshot: "92 ticket" beside "90,9% (10 ticket)" | `selectScope()`; title, narrative, ledger and rail all read the latest observed week, and the scope is stated in prose above the ledger |
| 10 | Attention rail printed the raw field name `issue_category` | screenshot | `coverageLabel()` map |
| 11 | Weekly Report started inside the first mobile viewport when a week produced no warnings | E2E mobile layout rule | `.decision { min-height: 100svh }` at ≤640px |

## Commands and results

```text
$ npm run typecheck            → exit 0
$ npm run test:coverage        → 15 files, 70 tests, 70 passed
                                 Statements 95,50% · Branches 87,91% ·
                                 Functions 93,20% · Lines 95,59%  (threshold 80)
$ npm run build                → exit 0
$ npm audit --audit-level=high → found 0 vulnerabilities
$ npm audit --audit-level=high --omit=dev
                               → found 0 vulnerabilities
$ npm run test:e2e             → 61 passed, 19 skipped, 0 failed
                                 (desktop-light, desktop-dark, mobile-light, mobile-dark)
$ .venv/bin/pytest -q          → exit 0, full Python suite passed
```

Skipped Playwright tests are the viewport-specific rules deliberately skipped
on the other viewport (`test.skip` on project name), not failures.

### Bundle budgets

| Budget | Limit | Measured |
|---|---:|---:|
| Initial JS, gzip | 250 KB | 135,31 kB by Vite |
| CSS, gzip | 80 KB | 4,83 kB by Vite |
| Fonts, total | 300 KB | 171 304 B (167,3 KB) |
| Production source maps | 0 | 0 |

### Privacy and API parity, measured against a live server

```text
$ curl -s http://127.0.0.1:8765/api/dashboard | grep -cE 'UserID|TransID|traceId|sessionId'
0

$ curl -s 'http://127.0.0.1:8765/api/tickets?page=1&page_size=1'
the 22 allowlisted projection fields, Ticket ID being the only identifier

$ curl -o /dev/null -w '%{http_code}' -X POST /api/refresh                     → 403
$ curl -o /dev/null -w '%{http_code}' -X POST -H 'X-Dashboard-Action: refresh' → 202
$ curl -o /dev/null -w '%{http_code}' '/api/tickets?page=0'                    → 422
```

The E2E server (`scripts/e2e_server.py`) drives the **real** FastAPI app with a
synthetic snapshot produced by the **real** `compute_report` + `project_dashboard`
pipeline, so it satisfies every reconciliation rule the production projection
enforces: 13 weekly rows, 7 with data, one WTD week, 92 tickets. No Langfuse
credential is used and no network call is made.

## Ready-to-ship criteria

| Criterion | Status | Evidence |
|---|---|---|
| Frontend coverage ≥80% | ĐẠT | 95,50 / 87,91 / 93,20 / 95,59 |
| Python suite green | ĐẠT | `.venv/bin/pytest -q` exit 0 |
| Desktop/mobile × light/dark visual, keyboard, axe, CSP, external-network, overflow | ĐẠT | 61 Playwright tests passed, 19 viewport-specific skips, 0 serious/critical axe violations, 0 external requests, 0 console errors |
| Privacy deny-list and API parity | ĐẠT | grep count 0; 403/202/422 above |
| Copy/CSV keep the exact 14 columns | ĐẠT | `report-sections.test.tsx` asserts the rendered `columnheader` list equals `WEEKLY_EXPORT_COLUMNS`, and the copied TSV header equals the same array |
| Bundle budgets | ĐẠT | table above |
| Wheel contains every nested asset | ĐẠT | `test_package_data_patterns_cover_every_nested_static_asset` compares the real `static/` tree against the `package-data` globs |
| Legacy rollback | ĐẠT | byte-identical copy, sha256 matches; `DASHBOARD_FRONTEND_MODE=legacy` covered by `test_spa_delivery.py` |
| Docker image behaviour | **CHƯA** | Docker cannot run here. Only the Dockerfile contract is tested |
| Two CS users complete the task test | **CHƯA** | not performed |
| UXD / Design System acceptance | **CHƯA** | not performed — the build is a production *candidate*, not official |
| Official SVG brand assets | **CHƯA** | PNG shipped verbatim; deviation recorded in `DESIGN.md` |

## Not verified

- Docker image behaviour, layer contents and startup.
- Real Langfuse data: every screenshot and E2E run uses synthetic traces.
- Any browser other than Chromium.
- Zalopay Design System component mapping.
