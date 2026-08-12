#!/bin/sh
set -eu

write_secret() {
    target_path="$1"
    value="$2"
    if [ -n "$value" ]; then
        mkdir -p "$(dirname "$target_path")"
        printf '%s' "$value" | base64 -d > "$target_path"
        chmod 600 "$target_path"
    fi
}

# The Freshdesk cookie can be updated at runtime via POST /api/freshdesk-cookie
# (spec 2026-08-12-freshdesk-cookie-crawl-design.md SS5) once the dialog has
# been used. Unlike the static approved-roster secrets above, seeding it here
# must only bootstrap an EMPTY persistent volume -- overwriting on every
# restart would silently revert whatever cookie the operator last submitted.
seed_secret_if_missing() {
    target_path="$1"
    value="$2"
    if [ -n "$value" ] && [ ! -f "$target_path" ]; then
        mkdir -p "$(dirname "$target_path")"
        printf '%s' "$value" | base64 -d > "$target_path"
        chmod 600 "$target_path"
    fi
}

write_secret /app/config/freshdesk_agents.v1.json "${FRESHDESK_AGENT_CONFIG_B64:-}"
write_secret /app/config/freshdesk_reconciliation_agents.v1.json "${FRESHDESK_RECONCILIATION_CONFIG_B64:-}"
write_secret /app/artifacts/freshdesk_discovery/human_agent_candidates.v1.json "${FRESHDESK_HUMAN_CANDIDATES_B64:-}"
seed_secret_if_missing /app/runtime/freshdesk_cookie "${FRESHDESK_COOKIE_B64:-}"

exec "$@"
