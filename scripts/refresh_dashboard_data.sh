#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dashboard_port="${DASHBOARD_LOCAL_PORT:-8765}"

case "$dashboard_port" in
  ""|*[!0-9]*)
    echo "DASHBOARD_LOCAL_PORT must be an integer between 1 and 65535" >&2
    exit 2
    ;;
esac
if (( dashboard_port < 1 || dashboard_port > 65535 )); then
  echo "DASHBOARD_LOCAL_PORT must be an integer between 1 and 65535" >&2
  exit 2
fi

dashboard_url="http://127.0.0.1:${dashboard_port}"
cd "$project_root"

ready=false
for (( attempt = 1; attempt <= 180; attempt += 1 )); do
  if curl -fsS --max-time 5 "${dashboard_url}/api/dashboard" \
    | jq -e '.snapshot != null' >/dev/null; then
    ready=true
    break
  fi
  sleep 1
done
if [[ "$ready" != "true" ]]; then
  echo "Dashboard did not become ready within 180 seconds" >&2
  exit 1
fi

before_generated_at="$(
  curl -fsS --max-time 5 "${dashboard_url}/api/dashboard" \
    | jq -r '.snapshot.generated_at'
)"

entry_coverage_result="$(
  uv run --isolated --locked weekly-cs-report fetch-freshdesk-entry-coverage \
    --weeks 13 --max-workers 1 --max-duration 7200 \
    --runtime-dir "$project_root/runtime"
)"
printf '%s\n' "$entry_coverage_result"
if ! jq -e '.status == "complete"' <<<"$entry_coverage_result" >/dev/null; then
  echo "Freshdesk entry coverage refresh did not complete; dashboard refresh cancelled" >&2
  exit 1
fi

csat_result="$(
  uv run --isolated --locked weekly-cs-report fetch-csat \
    --weeks 13 --max-workers 1 --max-duration 7200 \
    --runtime-dir "$project_root/runtime"
)"
printf '%s\n' "$csat_result"
if ! jq -e '.status == "complete"' <<<"$csat_result" >/dev/null; then
  echo "Freshdesk CSAT refresh did not complete; dashboard refresh cancelled" >&2
  exit 1
fi

reconciliation_result="$(
  uv run --isolated --locked weekly-cs-report reconcile-freshdesk-outcomes \
    --weeks 13 --max-workers 1 --max-duration 7200 \
    --runtime-dir "$project_root/runtime"
)"
printf '%s\n' "$reconciliation_result"
if ! jq -e '.status == "complete"' <<<"$reconciliation_result" >/dev/null; then
  echo "Freshdesk outcome reconciliation did not complete; dashboard refresh cancelled" >&2
  exit 1
fi

curl -fsS --max-time 10 -X POST \
  -H 'X-Dashboard-Action: refresh' \
  "${dashboard_url}/api/refresh" >/dev/null

refreshed=false
for (( attempt = 1; attempt <= 180; attempt += 1 )); do
  after_generated_at="$(
    curl -fsS --max-time 5 "${dashboard_url}/api/dashboard" \
      | jq -r '.snapshot.generated_at // empty'
  )"
  if [[ -n "$after_generated_at" && "$after_generated_at" != "$before_generated_at" ]]; then
    refreshed=true
    break
  fi
  sleep 1
done
if [[ "$refreshed" != "true" ]]; then
  echo "Dashboard refresh did not publish a new snapshot within 180 seconds" >&2
  exit 1
fi

echo "Freshdesk caches and dashboard snapshot refreshed."
