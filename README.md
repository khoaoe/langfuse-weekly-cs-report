# Langfuse Weekly CS Report

Deterministic weekly customer-service reporting for the approved Langfuse
project. The default command is a read-only dry run.

## Setup

For local use, create a project-root `.env`, keep it at mode `600`, and supply
the three required variables `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and
`LANGFUSE_BASE_URL`. Credential values belong only in that protected local file
or an approved secret store; they are intentionally not shown in this
documentation.

Install and run the offline tests:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -v
```

## Commands

```bash
# Defaults to dry-run, 12 completed weeks, no current WTD.
.venv/bin/weekly-cs-report

.venv/bin/weekly-cs-report dry-run \
  --weeks 12 \
  --include-current-wtd \
  --as-of 2026-07-29T12:00:00+07:00

.venv/bin/weekly-cs-report inspect-session SESSION_ID

# Read-only P0 coverage check against taxonomy v2. No observations or artifacts.
.venv/bin/weekly-cs-report verify-dimensions \
  --weeks 12 \
  --include-current-wtd \
  --as-of 2026-07-29T12:00:00+07:00
```

The host and project ID are fixed to the approved target. CLI errors never
print credential values. The CLI exposes read-only reporting commands only.
`verify-dimensions` prints one aggregate JSON object and does not read
observations or write artifacts. Unmapped TPE status text is emitted only when
it exactly matches the source-backed allowlist (`Thất bại`, `Đang xử lý`, or
`Bị từ chối`); every other value is grouped under `status: null`. TPE coverage
and unmapped-code output accept only signed ASCII numeric TPE tokens of one to
six digits. A reconstructed code/status value matching a formatted Vietnamese
phone is excluded from both coverage and unmapped output; phone detection
applies NFKC and retains only Unicode decimal digits before matching.

Each `dry-run` or `inspect-session` run writes only redacted analytical fields
beneath `artifacts/`:

- `summary.json`
- `weekly_summary.csv`
- `investigation.csv`
- `score_manifest.json`

Artifact directories use mode `700`, files use mode `600`, `latest/` is a copy
of the newest run, and only the 30 newest run directories are retained. Raw
trace and observation payloads are never serialized.

## Live dashboard

Start the loopback-only development service with:

```bash
.venv/bin/weekly-cs-dashboard --local --port 8765
```

The local URL is for the person running that process. It is not a coworker-shareable deployment.

On every open, the service serves the protected last-good snapshot immediately
and checks whether another read is due. The 5 phút interval is measured from a
successful cache commit, not from the report timestamp. `generated_at` is
captured near refresh start, and the upstream read itself can take several
minutes. Effective source-data age therefore includes both the interval and the
refresh duration, and can grow further while a failed refresh retains the
last-good data. This interval is not a source-data freshness SLA.

An older snapshot remains visible while one background read refreshes it; a
failed read keeps the last-good data and exposes only a fixed error code. The
production service must run with exactly one worker so the refresh lock and
cooldown remain effective.

The analytical denominator includes only traces whose root input has
`source == "ticket"` exactly. Direct chat sessions are excluded before
deduplication and cannot enter the aggregate or Ticket Explorer.

The dedicated runtime directory must have mode `700`; the protected snapshot
inside it has mode `600`. Neither location may sit below the static web
directory.

### Browser data boundary

Ticket ID is an approved browser field. User ID, Trans ID, phone, names/emails,
conversation text, prompts/responses, raw payloads, and Langfuse internal IDs
are not browser fields. Credentials and raw Langfuse records remain server-side.

## Production operating contract

Production receives configuration from the runtime and approved secret storage.
Its environment contract consists of these names:

- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_BASE_URL`
- `DASHBOARD_AUTH_MODE=proxy`
- `DASHBOARD_IDENTITY_HEADER`
- `DASHBOARD_RUNTIME_DIR`

`DASHBOARD_IDENTITY_HEADER` is restricted to `X-Forwarded-User` (the
default), `X-Auth-Request-User`, `X-Authenticated-User`, or `Remote-User`.
Choose the one the authenticated proxy owns and strips from every client
request before setting it.

The Langfuse target is fixed and validated as
`https://langfuse.zalopay.vn`. The image deliberately does not set
`DASHBOARD_AUTH_MODE`; startup therefore fails closed unless the deployment
provides proxy mode. The container command has no local-auth bypass and the
application starts one worker on port `8080`.

The authenticated reverse proxy is the identity trust boundary. It must
terminate TLS/SSO, strip any client-supplied identity header, and only then set
the trusted identity header from the authenticated principal before forwarding
the request. The service must remain behind the company VPN and the proxy's
access policy.

### Replica and rollout boundary

Run exactly one active replica. The refresh lock, manual-refresh cooldown, and
snapshot writer are process-local, so scaling this image horizontally can issue
duplicate Langfuse reads and race the shared snapshot. Configure one replica and
a `Recreate` deployment strategy, not `RollingUpdate`, so there is no surge and
never an old and new application pod active together. A highly available or
multi-replica deployment requires a separate distributed lock and shared cache;
this release does not provide either.

The image uses the fixed numeric identity `10001:10001`. Set the pod security
context explicitly:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
```

Mount a dedicated persistent-volume subdirectory at `DASHBOARD_RUNTIME_DIR`;
do not reuse a directory that contains any other application data. A volume
mount replaces the ownership baked into the image, so an init container must
run `chown 10001:10001` and `chmod 0700` on that dedicated directory before the
application starts. If `dashboard_snapshot.json` already exists, the init step
must also set its owner to `10001:10001` and run `chmod 0600`. Use a dedicated
`subPath` (or an equivalently isolated volume) so this correction cannot touch
unrelated files.

### Network and probes

Do not expose the application Service directly. Enforce a `NetworkPolicy` with
ingress only from the authenticated reverse proxy and the required platform
probe source. Restrict egress to DNS and the approved Langfuse destination.
The reverse proxy must remove the configured identity header from the client
request before injecting the authenticated value.

Use `/healthz` for liveness. It reports only that the process can answer and
stays `200` while the first snapshot is loading. Use `/readyz` for readiness:
it returns `503` until a last-good snapshot exists, then `200` while that
snapshot can be served, including during a background refresh.

DevOps must provide all of the following before this can become a shared
internal deployment:

- an internal registry for the image;
- the approved container runtime;
- the internal domain;
- the VPN/SSO access policy;
- approved secret storage for Langfuse credentials;
- egress from that runtime to `https://langfuse.zalopay.vn`.

The Docker build uses only `pyproject.toml`, `README.md`, `src/`, and `config/`.
It installs the project editably inside the immutable image so
`PROJECT_ROOT/config/taxonomy.v1.json` remains available. Local `.env`,
artifacts, protected runtime data, tests, and workspace metadata are excluded
from the build context.

Docker is unavailable in this workspace, so no image build has been executed
here. The automated checks validate the Dockerfile and deployment contract, not
the behavior of a built image.
