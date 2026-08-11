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

write_secret /app/config/freshdesk_agents.v1.json "${FRESHDESK_AGENT_CONFIG_B64:-}"
write_secret /app/config/freshdesk_reconciliation_agents.v1.json "${FRESHDESK_RECONCILIATION_CONFIG_B64:-}"
write_secret /app/artifacts/freshdesk_discovery/human_agent_candidates.v1.json "${FRESHDESK_HUMAN_CANDIDATES_B64:-}"

exec "$@"
