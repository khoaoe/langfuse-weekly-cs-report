# Zalopay production frontend — implementation plan

## Global constraints

- Preserve all backend data, metric, privacy and refresh contracts.
- Do not modify `llm_client.py`, `test_llm_client.py`, `CLAUDE.md`, `uv.lock`
  or unrelated reopen work.
- Existing dirty changes are user-owned; never reset or overwrite them.
- User-facing brand literal is `Zalopay`.
- No external runtime dependency, CDN, unsafe-inline or unsafe-eval.
- TDD is required; frontend coverage must be at least 80%.
- Production candidate must not be called official before UXD/Design System
  approval.

## Task 1 — Foundation and RED contracts

- Add frontend package, strict TypeScript, Vite, Vitest/RTL/MSW and Playwright.
- Write RED tests for API parsing, formatting, narrative, export, runtime state,
  brand casing and component behavior.
- Add product/design spec artifacts and the emitted design-direction comment.

## Task 2 — App shell, decision ledger and Weekly Report

- Build same-origin query client and four runtime states.
- Build sticky app shell, deterministic narrative, decision ledger and action
  rail.
- Build 14-column weekly semantic table, Copy TSV, CSV BOM, WTD/empty/maturity
  behavior and mobile six-column view.

## Task 3 — Analysis and diagnostics

- Build aligned trend panels with shared week filter.
- Build segment tabs/table, transfer diagnostics, rule compliance and data
  quality disclosure.
- Keep every number labelled and preserve privacy-safe categorical values.

## Task 4 — Ticket Explorer and responsive hardening

- Preserve filters, pagination, sort, column visibility persistence and
  1,000-row CSV export.
- Implement mobile/table local scrolling, dark mode, keyboard/focus and reduced
  motion.

## Task 5 — FastAPI, CSP and packaging

- Preserve legacy page for rollback and add `legacy|spa` mode.
- Serve hashed assets with auth, immutable private cache and strict CSP.
- Include recursive assets in wheel and build with multi-stage Node/Python
  Docker.

## Task 6 — Verification and finish

- Run frontend coverage, typecheck, lint, production build and bundle budgets.
- Run full pytest, Playwright desktop/mobile light/dark, axe and privacy/network
  checks.
- Perform two bounded visual inspection rounds.
- Run independent code/design review and write final `DESIGN.md` plus TDD
  evidence from the verified build.
