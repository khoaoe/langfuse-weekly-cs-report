# Backend Production Readiness Design

**Date:** 2026-07-31
**Status:** Approved for implementation
**Scope:** Backend production candidate only; deployment is deferred

**Sửa 2026-08-10:** Dòng 34 ("Do not add a new user authentication method")
giả định deployment thật luôn có reverse proxy SSO đứng trước, đúng cho hạ
tầng production cuối cùng nhưng **không đúng** cho Zalopay Agent Base (PaaS
nội bộ dùng để demo/thử nghiệm) — Traefik ở đó chỉ route/TLS, không chèn
identity header, nên `auth_mode=proxy` khiến app crash-loop ngay khi khởi
động (thiếu biến bắt buộc) hoặc 401 toàn bộ traffic nếu ép biến đó. Thêm
`DASHBOARD_AUTH_MODE=basic` (xem `web.py` `_AUTH_MODES`): tin HTTP Basic Auth
của platform ở edge làm identity authority thay vì header SSO, chỉ dùng khi
platform đó **bắt buộc bật Basic Auth**. `proxy` vẫn nguyên vẹn, vẫn là chuẩn
cho hạ tầng production thật có SSO. Đây là mở rộng phạm vi hẹp cho môi trường
demo, không phải huỷ ràng buộc bảo mật của dòng 34 cho production.

## Verdict

The existing backend is a strong protected-dashboard foundation, but it is not
yet a production candidate. The release-changing gaps are:

1. a complete trace refresh has no shared wall-clock budget or page ceiling;
2. shutdown cannot cooperatively stop the active refresh;
3. the proxy identity header accepts ambiguous or oversized values;
4. runtime refresh events are not emitted as privacy-safe structured logs;
5. artifact writes can follow a planted symlink and are not atomic;
6. CI reports Python coverage but does not enforce the repository's coverage
   gate.

Deployment manifests, ingress, NetworkPolicy, PVC provisioning, secret
rotation, and a live rollout are explicitly outside this implementation.

## Product and release boundaries

- Keep the deterministic V1 analysis path. Do not call an LLM from the
  dashboard runtime.
- Keep the existing browser routes:
  `GET /api/dashboard`, `GET /api/tickets`, and `POST /api/refresh`.
- Keep dashboard storage schema version 4 and the current SPA payload contract.
- Keep Langfuse access GET-only. No score, trace, or observation writes.
- Add no runtime dependency beyond the current FastAPI, HTTPX, dotenv, and
  Uvicorn set.
- Keep exactly one process worker and one in-process refresh flight.
- Do not add a new user authentication method. The authenticated reverse proxy
  remains the identity authority. Direct service access must be prevented by
  deployment networking when deployment work resumes.
- Never log or return identities, query values, ticket IDs, trace IDs,
  credentials, raw upstream bodies, or exception messages.
- The real-data P0 gate is Langfuse-only. It reads root
  `input.source == "ticket"` traces and uses the complete raw ticket population
  for both measures. Issue-category coverage must be at least `0.90` and TPE
  metadata coverage at least `0.85`. The implementation must not use a local
  overlay or another ticket API, lower the thresholds, narrow the denominator
  by entry point/source/presence, or relabel missing data to make the gate pass.
- Dashboard `coverage.tpe` remains a separate observation-source measure and
  does not replace the raw trace-metadata P0 measure.

## Runtime refresh budget

The dashboard process owns one configurable full-refresh budget:

- `DASHBOARD_REFRESH_DEADLINE_SECONDS`
- default: `120`
- allowed inclusive range: `30..300`

The Langfuse trace reader also owns a page ceiling:

- `DASHBOARD_MAX_TRACE_PAGES`
- default: `500`
- allowed inclusive range: `1..500`
- each page remains capped at 100 traces

`compute_report` calculates one monotonic deadline. Core trace pagination uses
that deadline and the configured page ceiling. Observation enrichment starts in
parallel. Its exact deadline is
`min(full_deadline - 5 seconds, refresh_start + 110 seconds)`, so the
five-second drain reserve also applies when the configured full deadline is
less than 120 seconds. The report checks cancellation and the full deadline at
phase boundaries. Deadline, page-limit, and cancellation failures use fixed
exception types and fixed error codes; no upstream payload or URL value reaches
the browser.

The cache owns a process-lifetime cancellation event. `SnapshotManager.close()`
sets the event before joining the refresh executor. The production loader passes
the same event into `compute_report`. Uvicorn gets a 45-second graceful-shutdown
timeout; HTTPX already caps an individual request at 30 seconds.

The last-good snapshot remains authoritative after any refresh failure. Core
trace failures fail the refresh. Optional observation failures continue to
produce a snapshot with `enrichment_status: partial`.

## Proxy boundary hardening

Proxy mode still trusts exactly one allowlisted identity header, but a request
is authenticated only when:

- exactly one instance of the configured header is present;
- its value is 1 to 256 characters;
- it has no leading or trailing whitespace;
- it contains no comma, control character, or whitespace character.

The identity value is never persisted, returned, or logged. Health and readiness
remain unprotected. Root, API, and SPA assets remain protected.

This does not make direct service exposure safe. A production deployment must
strip client-supplied identity headers at the proxy and restrict service ingress
to that proxy. That work is deliberately deferred.

## Structured runtime logs

Runtime events are JSON objects written with the standard library only:

- `service_start`
- `service_stop`
- `snapshot_load_ignored`
- `refresh_start`
- `refresh_success`
- `refresh_failure`
- `refresh_cancelled`

Only allowlisted fields are emitted: fixed event name, fixed error code,
duration in milliseconds, booleans, schema version, and aggregate counts or
coverage values. Exception text and request context are forbidden.

Access logs remain disabled because their URLs can contain investigation
filters. The authenticated reverse proxy owns request/audit logging when
deployment resumes.

## Artifact safety

Artifact root, run, and `latest` paths must be real directories, never symlinks.
JSON and CSV output is written to a mode-0600 temporary file in the destination
directory, flushed, fsynced, and atomically replaced. A pre-existing symlink at
an artifact destination is rejected without modifying its target. Directory
mode stays 0700, file mode stays 0600, and retention stays 30 runs.

## Quality gates

- Python tests: all pass.
- Python line coverage: total at least 85%.
- Critical backend files: each at least 80%:
  `langfuse_client.py`, `report.py`, `dashboard_cache.py`, `dashboard_schema.py`,
  and `web.py`.
- Frontend typecheck, unit coverage, build, and browser tests: all pass.
- Wheel build and static-asset parity: pass.
- Dependency audits: pass under the repository's one documented, bounded pytest
  advisory exception.
- Python CI runtime: exact 3.11.15. The current local `.venv` is Python 3.9.6,
  so exact-runtime verification is CI-only unless a local 3.11.15 interpreter
  is discovered during final verification.
- Docker behavior cannot be claimed locally because Docker is unavailable; the
  existing GitHub Actions image smoke test remains the verification surface.

## Release classification

The final report must publish three separate top-level verdicts:
`backend_candidate=PASS|FAIL`, `p0_data=PASS|FAIL`, and
`go_live=PASS|BLOCKED`. Passing the implementation and local verification gates
can make the repository a **backend production candidate**, not a live
production release.

For the fixed 12-week plus WTD window ending
`2026-07-31T10:00:00+07:00`, the observed raw-only diagnostic evidence is:

```text
ticket_count = 6369
issue_category_present_count = 5393
coverage_issue_category = 0.8467577327680955
tpe_present_count = 5045
coverage_tpe = 0.7921180719108181
p0_issue_category_pass = false
p0_tpe_pass = false
p0_pass = false
```

This makes `p0_data=FAIL`. The exact expected exit for a current-source
`verify-dimensions --require-p0` run with the same fixed window is `1`; the
final current-source release rerun remains a separate verification step.

Go-live still requires:

1. the Langfuse-only raw all-ticket P0 coverage gate to pass;
2. deployment networking and proxy controls;
3. production secret provisioning or rotation;
4. successful remote CI, image smoke test, rollout, and rollback evidence.
