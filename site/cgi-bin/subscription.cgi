#!/bin/bash
# subscription.cgi -- manage VLESS subscriptions.
# Stored in $WISD_STATE_DIR/subscriptions/:
#   index.json            -- list of subscriptions
#   <sub_id>/raw.txt      -- last fetched body
#   <sub_id>/nodes.json   -- parsed nodes
#
# Subscriptions are NEVER auto-refreshed. The user must call action=fetch
# explicitly to re-pull a subscription.
DIR=$(dirname "$0")
. "$DIR/lib.sh"
require_jq

parse_query
read_post_body

ACTION=${QPARAM[action]:-list}

INDEX_FILE=$WISD_SUB_DIR/index.json
[[ -f "$INDEX_FILE" ]] || echo '{"subscriptions":[]}' > "$INDEX_FILE"

# parse_vless_lines <path-to-raw-body>
# Reads a VLESS subscription body file (possibly base64-encoded) and prints a
# JSON array of node objects to stdout.
#   {"name": "...", "host": "...", "port": 443, "uuid": "...",
#    "type": "tcp"|"grpc"|"ws"|"http", "security": "reality"|"tls"|"none",
#    "sni": "...", "publicKey": "...", "shortId": "...", "flow": "...",
#    "serviceName": "...", "path": "...", "headerHost": "...",
#    "raw": "vless://..."}
parse_vless_lines() {
WISD_RAW_PATH=$1 python3 - <<'PY'
import os, sys, base64, re, json
from urllib.parse import urlparse, parse_qs, unquote

body = open(os.environ['WISD_RAW_PATH'], 'r', encoding='utf-8', errors='ignore').read().strip()
if not body:
    print('[]'); sys.exit(0)

# Try base64 decode if the body looks like base64.
if re.fullmatch(r'[A-Za-z0-9+/=\s\-_]+', body) and 'vless://' not in body:
    pad = '=' * (-len(re.sub(r'\s+', '', body)) % 4)
    try:
        body = base64.urlsafe_b64decode(re.sub(r'\s+', '', body) + pad).decode('utf-8', 'ignore')
    except Exception:
        try:
            body = base64.b64decode(re.sub(r'\s+', '', body) + pad).decode('utf-8', 'ignore')
        except Exception:
            pass

nodes = []
for line in body.splitlines():
    line = line.strip()
    if not line.startswith('vless://'):
        continue
    try:
        u = urlparse(line)
        name = unquote(u.fragment) if u.fragment else f'{u.hostname}:{u.port or 443}'
        params = {k: (v[0] if v else '') for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        node = {
            'name': name,
            'host': u.hostname or '',
            'port': u.port or 443,
            'uuid': u.username or '',
            'type': params.get('type', 'tcp'),
            'security': params.get('security', 'none'),
            'sni': params.get('sni', ''),
            'publicKey': params.get('pbk', ''),
            'shortId': params.get('sid', ''),
            'fingerprint': params.get('fp', 'chrome'),
            'flow': params.get('flow', ''),
            'serviceName': params.get('serviceName', ''),
            'path': params.get('path', ''),
            'headerHost': params.get('host', ''),
            'mode': params.get('mode', ''),
            'encryption': params.get('encryption', 'none'),
            'raw': line,
        }
        nodes.append(node)
    except Exception as e:
        sys.stderr.write(f'skip line: {e}\n')

print(json.dumps(nodes, ensure_ascii=False))
PY
}

write_nodes_combined() {
    # Merge per-subscription nodes into a single $WISD_NODES_FILE.
    local combined='[]'
    local sub_id
    while IFS= read -r sub_id; do
        local file=$WISD_SUB_DIR/$sub_id/nodes.json
        [[ -f "$file" ]] || continue
        combined=$(jq --slurpfile sub "$file" --arg sid "$sub_id" '
            . + ($sub[0] | map(. + {subscription: $sid}))
        ' <<<"$combined")
    done < <(jq -r '.subscriptions[].id' "$INDEX_FILE")
    # Re-id nodes 0..N-1 for stable selection.
    jq '[. as $arr | range(0; length) as $i | $arr[$i] + {id: $i}]' <<<"$combined" \
        > "$WISD_NODES_FILE.tmp" && mv "$WISD_NODES_FILE.tmp" "$WISD_NODES_FILE"
}

case "$ACTION" in
    list)
        json_header
        # Return both subscriptions metadata and merged nodes list.
        if [[ -f "$WISD_NODES_FILE" ]]; then
            nodes=$(cat "$WISD_NODES_FILE")
        else
            nodes='[]'
        fi
        subs=$(cat "$INDEX_FILE")
        printf '{"ok":true,"subscriptions":%s,"nodes":%s}\n' \
            "$(jq '.subscriptions' <<<"$subs")" "$nodes"
        ;;

    add)
        # add by URL: subscription.cgi?action=add&name=...&url=...
        # add by raw paste: POST raw body, no url
        name=${QPARAM[name]:-Subscription}
        url=${QPARAM[url]:-}
        body=""
        if [[ -n "$url" ]]; then
            body=$(curl -fsSL --max-time 30 "$url" 2>/dev/null) || \
                json_error 11 "fetch failed"
        else
            body=$POST_BODY
        fi
        if [[ -z "$body" ]]; then
            json_error 12 "empty subscription body"
        fi
        sub_id=$(random_hex 6)
        mkdir -p "$WISD_SUB_DIR/$sub_id"
        printf '%s' "$body" > "$WISD_SUB_DIR/$sub_id/raw.txt"
        if ! parse_vless_lines "$WISD_SUB_DIR/$sub_id/raw.txt" > "$WISD_SUB_DIR/$sub_id/nodes.json"; then
            rm -rf "$WISD_SUB_DIR/$sub_id"
            json_error 13 "parse failed"
        fi
        count=$(jq 'length' "$WISD_SUB_DIR/$sub_id/nodes.json")
        if (( count == 0 )); then
            rm -rf "$WISD_SUB_DIR/$sub_id"
            json_error 14 "no VLESS nodes found in body"
        fi
        added=$(date -u +%s)
        jq --arg id "$sub_id" \
           --arg name "$name" \
           --arg url "$url" \
           --argjson count "$count" \
           --argjson added "$added" '
            .subscriptions += [{
                id: $id, name: $name, url: $url,
                count: $count, addedAt: $added, fetchedAt: $added
            }]' "$INDEX_FILE" > "$INDEX_FILE.tmp" && mv "$INDEX_FILE.tmp" "$INDEX_FILE"
        write_nodes_combined
        json_ok "\"id\":\"$sub_id\",\"count\":$count"
        ;;

    fetch)
        sub_id=${QPARAM[id]:-}
        [[ -n "$sub_id" ]] || json_error 20 "missing id"
        url=$(jq -r --arg id "$sub_id" '.subscriptions[] | select(.id==$id) | .url' "$INDEX_FILE")
        [[ -n "$url" && "$url" != "null" ]] || json_error 21 "subscription has no URL (manual paste)"
        body=$(curl -fsSL --max-time 30 "$url" 2>/dev/null) || json_error 22 "fetch failed"
        printf '%s' "$body" > "$WISD_SUB_DIR/$sub_id/raw.txt"
        parse_vless_lines "$WISD_SUB_DIR/$sub_id/raw.txt" > "$WISD_SUB_DIR/$sub_id/nodes.json" \
            || json_error 23 "parse failed"
        count=$(jq 'length' "$WISD_SUB_DIR/$sub_id/nodes.json")
        fetched=$(date -u +%s)
        jq --arg id "$sub_id" --argjson count "$count" --argjson fetched "$fetched" '
            .subscriptions = (.subscriptions | map(
                if .id == $id then .count=$count | .fetchedAt=$fetched else . end
            ))' "$INDEX_FILE" > "$INDEX_FILE.tmp" && mv "$INDEX_FILE.tmp" "$INDEX_FILE"
        write_nodes_combined
        json_ok "\"count\":$count"
        ;;

    rename)
        sub_id=${QPARAM[id]:-}
        new_name=${QPARAM[name]:-}
        [[ -n "$sub_id" && -n "$new_name" ]] || json_error 30 "missing id or name"
        jq --arg id "$sub_id" --arg name "$new_name" '
            .subscriptions = (.subscriptions | map(
                if .id == $id then .name = $name else . end
            ))' "$INDEX_FILE" > "$INDEX_FILE.tmp" && mv "$INDEX_FILE.tmp" "$INDEX_FILE"
        json_ok ""
        ;;

    remove)
        sub_id=${QPARAM[id]:-}
        [[ -n "$sub_id" ]] || json_error 40 "missing id"
        rm -rf "$WISD_SUB_DIR/$sub_id"
        jq --arg id "$sub_id" '
            .subscriptions = (.subscriptions | map(select(.id != $id)))
        ' "$INDEX_FILE" > "$INDEX_FILE.tmp" && mv "$INDEX_FILE.tmp" "$INDEX_FILE"
        write_nodes_combined
        json_ok ""
        ;;

    nodes)
        # raw merged nodes list
        json_header
        if [[ -f "$WISD_NODES_FILE" ]]; then
            cat "$WISD_NODES_FILE"
        else
            echo '[]'
        fi
        ;;

    *)
        json_error 99 "unknown action: $ACTION"
        ;;
esac
