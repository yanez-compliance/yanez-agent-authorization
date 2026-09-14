#!/usr/bin/env bash
# Minimal raw-HTTP integration: create a request, long-poll until decided.
# Needs: YANEZ_BASE_URL, YANEZ_AGENT_API_KEY. Uses curl, jq, and uuidgen.
set -euo pipefail

terms=$(cat <<'JSON'
{"schema_version":1,
 "action":"purchase",
 "approval_title":"Purchase running shoes",
 "summary":"Buy running shoes for $180.00 at Example Store",
 "merchant":"Example Store",
 "currency":"USD",
 "amount":{"minor_units":18000,"currency":"USD"},
 "details":[{"label":"Merchant","value":"Example Store","emphasized":false},
            {"label":"Item","value":"Running shoes, model X, size 10","emphasized":false},
            {"label":"Amount","value":"$180.00","emphasized":true}]}
JSON
)
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

# --- The relying party's half, which is NOT the agent's ---
#
# Everything above runs as the agent. Everything below belongs to the action executor,
# in its own service, holding no agent key. It is sketched here rather than implemented
# because the part that matters cannot be done in shell: verifying the approver's own
# BLS signature over `yanez_signed_message`. `jq` can decode the claims; it cannot
# check a BLS12-381 signature, and decoded-but-unverified claims are not authorization.
#
# Use an SDK, or implement the steps in
# https://yanez-compliance.github.io/yanez-agent-authorization/user-signed-approvals/
#
# Consumption, for single-use actions, is plain HTTP — note the consumer_token, which
# is yours, durable, and reused verbatim on every retry:
#
#   curl -sf -X POST "$YANEZ_BASE_URL/api/authz/introspect" \
#     -H "Content-Type: application/json" \
#     -d "{\"artifact\": \"$artifact\", \"consume\": true,
#          \"consumer_token\": \"$YOUR_DURABLE_TOKEN\"}"
#
# Act only on consumed_now: true. On reason "reservation_held" your own earlier attempt
# already won, so reconcile downstream with your original idempotency key instead of
# requesting a new approval. On "already_consumed", someone else holds it: never act.
