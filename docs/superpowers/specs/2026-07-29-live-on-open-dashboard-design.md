# Live-on-open Weekly CS Dashboard Design

**Status:** Approved  
**Approval:** The user approved the five-minute refresh model on 2026-07-29.  
**Audience:** CS, developers, and product owners with internal access.  
**Source:** Langfuse project `cmqubjzur000hz507ptubh2l9`.  
**Business timezone:** `Asia/Ho_Chi_Minh`.

## 1. Decision

Replace the local static demo with a small internal web service. Every page
open checks the server for current data. The server returns the last good
aggregate immediately and starts one background refresh when that aggregate is
more than five minutes old.

The service does not recompute all 12 weeks independently for every viewer.
The current dataset requires roughly 93 paginated trace requests and one
observation request for each of 1,186 transfers. Recomputing on every page view
would create at least about 1,279 Langfuse requests per viewer, increase page
latency, and create a request stampede when several people open the link.

The page also checks again every five minutes while it remains open. A
same-origin **Làm mới ngay** action may request a refresh, but it joins an
existing refresh rather than starting a duplicate one.

## 2. Scope

The live dashboard keeps the approved V1 metric contract:

- only traces whose root input has `source == "ticket"` exactly; direct chat
  sessions are excluded before deduplication and analysis;
- 12 completed Monday-Friday cohorts plus current WTD;
- ticket count and AI First;
- AI xử lý đến cuối, AI hỗ trợ trước rồi CS tiếp quản, and CS tiếp quản ngay;
- reopen lifetime and mature reopen-within-seven-days;
- AI reply count per ticket;
- transfer business, TPE, and guardrail/rule categories;
- data-quality and source-freshness diagnostics;
- survey remains out of scope.

The page adds a bounded ticket table so an internal viewer can investigate an
aggregate. Ticket ID is permitted. Raw trace or observation payloads are not.

This change does not write scores, traces, or observations to Langfuse. The
live service is read-only.

## 3. Privacy Contract

### Browser-safe allowlist

The dashboard API may expose only:

- a numeric `ticket_id` from a ticket-source lifecycle; a generic Langfuse
  session ID is never a browser fallback;
- cohort week and cohort status;
- the approved outcome and AI First flags;
- reopen flags and AI reply count;
- normalized business, TPE, and guardrail/rule category labels;
- normalized data-quality labels;
- weekly aggregates, counts, rates, and freshness timestamps.

### Prohibited browser fields

The dashboard API, HTML, browser logs, URLs, and persisted web snapshots must
not contain:

- user or account IDs;
- transaction IDs;
- phone numbers;
- customer names, emails, addresses, or payment identifiers;
- ticket title, description, message, prompt, model response, or conversation
  contents;
- raw `input`, `output`, `metadata`, observation, or trace payloads;
- trace IDs, observation IDs, score IDs, or Langfuse credentials.

The browser payload is constructed from explicit response models. It is not
produced by removing a blacklist from a raw payload. Transfer category
`raw_values` and source fields are excluded even when they appear safe.

Ticket ID remains an internal operational identifier. The application must
still run behind the company VPN and an authenticated reverse proxy or SSO.

## 4. Architecture

```text
Browser
  │  GET /api/dashboard
  │  GET /api/tickets
  │  POST /api/refresh
  ▼
Internal FastAPI service
  ├── browser-safe response projection
  ├── five-minute last-good cache
  ├── single-flight refresh lock
  └── existing deterministic analytics pipeline
        │
        ▼
Langfuse Public API (server-side credentials only)
```

The existing modules remain authoritative:

- `cohort.py` owns business-week boundaries;
- `classification.py` owns ticket lifecycle outcomes;
- `categories.py` owns transfer taxonomy;
- `pipeline.py` owns aggregation and invariants;
- `langfuse_client.py` owns authenticated, retried API reads.

Analysis orchestration moves out of the CLI into a reusable report service.
The CLI and web service call the same function, so they cannot silently drift.

## 5. Refresh and Cache State

The cache has these externally visible states:

- `loading`: no last-good snapshot exists and the first refresh is running;
- `ready`: the successful cache commit is younger than five minutes;
- `refreshing`: a last-good snapshot is being served while one refresh runs;
- `stale_error`: the latest refresh failed and the last-good snapshot remains
  available.

`GET /api/dashboard` behaves as follows:

1. Return `200` with the last-good aggregate when one exists.
2. If it is stale, atomically acquire the refresh lock and start a background
   refresh. Other viewers reuse the same in-flight job.
3. Return `202` with `loading` only when no snapshot exists yet.
4. Never replace a valid snapshot with an empty or partial result.

After a successful refresh, the service validates all metric invariants and
the browser-safe schema, writes a temporary protected snapshot, and atomically
replaces the last-good snapshot. Runtime directories are mode `700`; snapshot
files are mode `600`.

`generated_at` is captured near refresh start, while cache age begins at the
successful commit. The upstream read can take several minutes, so five minutes
is a refresh-throttling interval rather than a source-data freshness SLA.

After a failed refresh, the service records only a sanitized error class,
failure time, and retry guidance. Credentials, request bodies, ticket data,
and upstream response bodies are never returned to the browser.

The server runs one application worker and exactly one active replica in V1.
This makes the in-process single-flight lock authoritative. A future
multi-worker or multi-replica deployment requires a shared lock and cache such
as Redis; it must not be enabled by changing the worker or replica count alone.

## 6. HTTP Contract

### `GET /`

Serves the dashboard application from the same origin as the API. The current
visual direction remains the approved Layered scorecard.

### `GET /api/dashboard`

Returns:

- refresh state and `generated_at`;
- source coverage and data-quality counts;
- KPI and outcome aggregates;
- weekly rows;
- transfer distributions;
- gate state and clearly labelled provisional/blocked dimensions.

Responses use `Cache-Control: no-store`.

### `GET /api/tickets`

Returns server-side paginated browser-safe ticket rows. Supported filters are:

- cohort week;
- outcome;
- business category;
- TPE category;
- guardrail/rule category;
- exact ticket ID.

Page size defaults to 50 and is capped at 100. Unknown filters, invalid dates,
and malformed ticket IDs return `422`. Results have a deterministic order.

### `POST /api/refresh`

Requests a refresh and returns the current refresh state. It does not wait for
the complete Langfuse read and never starts a second concurrent job.

### `GET /healthz`

Returns liveness only. `GET /readyz` returns `503` until a last-good snapshot
exists, then `200`. Neither endpoint exposes business data or upstream error
bodies.

## 7. User Experience

On first load the page shows one of:

- the current dashboard with `Cập nhật lúc …`;
- the current dashboard plus `Đang lấy dữ liệu mới`;
- a loading state when no snapshot has ever completed;
- the last-good dashboard plus a precise, non-sensitive refresh failure.

The dashboard automatically fetches the new snapshot after a background
refresh completes. It does not blank charts during refresh.

The ticket table appears below the aggregate views. It supports the approved
filters and shows ticket ID as ordinary text. A Langfuse deep link is not added
until the exact internal session route and its authorization behavior are
verified.

## 8. Authentication and Deployment

Local development binds to `127.0.0.1`. The container listens on port `8080`
only for an internal reverse proxy.

Production configuration requires:

- Langfuse credentials supplied by the runtime secret manager or environment;
- egress to `https://langfuse.zalopay.vn`;
- VPN/internal DNS access;
- SSO or an authenticated reverse proxy;
- a trusted identity header configured by DevOps;
- one Uvicorn worker and exactly one active replica.

The `.env` file is never copied into the container image. No public deployment
is acceptable because the source is internal and the dashboard contains ticket
IDs.

The workspace currently contains no internal registry, runtime, ingress,
domain, or SSO configuration. The implementation can produce a tested
container, but a shareable company URL requires those deployment inputs from
Dev/DevOps.

## 9. Data-quality Preconditions

Before the live service is presented as production-ready:

1. Enforce exact ticket-source scope before deduplication so chat turns cannot
   enter a ticket lifecycle.
2. Accept a missing legacy `freshdesk_id` without manufacturing a structural
   mismatch; only two present, non-empty, different IDs constitute
   `session_freshdesk_mismatch`.
3. Exclude guardrail/system-only outputs and the literal technical marker
   `ESCALATE_CS_MESSAGE` from substantive AI replies while preserving the
   canonical transfer classification.
4. Re-run the real read-only analysis, verify the core and category gates, and
   scan the final browser payload for prohibited fields.
5. Preserve the approved invariants and maturity rules from the original
   dashboard specification.

## 10. Testing

Implementation follows test-first development.

Required unit and integration coverage includes:

- missing `freshdesk_id` is accepted while a real non-empty mismatch is
  quarantined;
- browser response models cannot serialize prohibited fields;
- ticket ID is retained;
- ticket pagination and filters are bounded and validated;
- a fresh cache does not trigger Langfuse reads;
- a stale cache triggers exactly one refresh under concurrent requests;
- first boot returns `loading`;
- failed refresh preserves the last-good snapshot;
- successful refresh atomically replaces the snapshot;
- dashboard and ticket endpoints use `no-store`;
- credentials and upstream response bodies never enter errors or logs;
- all weekly and lifecycle invariants still reconcile;
- the static application works at desktop and mobile widths;
- keyboard focus and reduced-motion behavior remain usable.

Real Langfuse validation is read-only. It verifies a cold refresh, a warm cache
hit, the five-minute stale transition, and aggregate reconciliation against
the CLI. No automated test writes to the real project.

## 11. Acceptance

The live demo is ready when:

- the service starts locally without exposing credentials;
- opening the page automatically checks freshness;
- a stale snapshot starts one refresh and the page updates afterward;
- a warm page load returns the dashboard without recomputing 12 weeks;
- ticket IDs appear in the bounded detail table;
- a seeded PII fixture proves prohibited fields never reach API responses,
  snapshots, HTML, or logs;
- the real read-only refresh reconciles with the existing aggregate;
- all tests pass and the UI is visually checked.

The company-shareable delivery is complete only after the container is deployed
behind the approved internal SSO/reverse proxy and a reachable internal URL is
verified from another authorized account.
