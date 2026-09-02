#!/usr/bin/env bash
# Minimal raw-HTTP integration: create a request, long-poll until decided.
# Needs: YANEZ_BASE_URL, YANEZ_AGENT_API_KEY. Uses curl, jq, and uuidgen.
set -euo pipefail

terms='{"action":"purchase","summary":"Buy running shoes for $180 at Example Store","merchant":"Example Store","amount":"180.00","currency":"USD"}'
idem=$(uuidgen)

created=$(curl -sf -X POST "$YANEZ_BASE_URL/api/agent/authorizations" \
  -H "Authorization: Bearer $YANEZ_AGENT_API_KEY" \
  -H "Idempotency-Key: $idem" \
  -H "Content-Type: application/json" \
  -d "{\"terms\": $terms}")
request_id=$(echo "$created" | jq -r .request_id)
echo "created $request_id; approve or reject it in the YID app" >&2

while true; do
  result=$(curl -sf "$YANEZ_BASE_URL/api/agent/authorizations/$request_id?wait=25" \
    -H "Authorization: Bearer $YANEZ_AGENT_API_KEY")
  status=$(echo "$result" | jq -r .status)
  [ "$status" = "pending" ] && continue
  echo "$result" | jq .
  break
done
