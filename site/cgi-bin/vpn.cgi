#!/bin/bash
# vpn.cgi -- control the Xray tunnel.
#
# Actions:
#   status                         -- return JSON state
#   up&mode=direct                 -- start xray with freedom outbound
#   up&mode=tunnel&id=<nodeid>     -- start xray tunneling via a chosen node
#   down                           -- stop xray (only the outbound side; the
#                                     VLESS-server inbound on :443 is also
#                                     stopped because xray is a single process,
#                                     but install.sh re-enables it on next start)
#   restart                        -- regen config and restart
#   clearlogs                      -- truncate xray log
DIR=$(dirname "$0")
. "$DIR/lib.sh"
require_jq

parse_query
ACTION=${QPARAM[action]:-status}

status_json() {
    local mode="direct" sel="" started=0 elapsed=0 running=false
    [[ -f "$WISD_MODE_FILE" ]] && mode=$(cat "$WISD_MODE_FILE")
    [[ -f "$WISD_NODE_FILE" ]] && sel=$(cat "$WISD_NODE_FILE")
    [[ -f "$WISD_STARTED_FILE" ]] && started=$(cat "$WISD_STARTED_FILE")
    xray_running && running=true
    if [[ "$running" == "true" && "$started" -gt 0 ]]; then
        local now
        now=$(date -u +%s)
        elapsed=$(( now - started ))
        (( elapsed < 0 )) && elapsed=0
    fi
    local enabled=false
    [[ "$running" == "true" ]] && enabled=true
    # extract selected node info
    local node_name="" node_host=""
    if [[ -n "$sel" && -f "$WISD_NODES_FILE" ]]; then
        node_name=$(jq -r --argjson id "$sel" '.[] | select(.id==$id) | .name // ""' "$WISD_NODES_FILE" 2>/dev/null)
        node_host=$(jq -r --argjson id "$sel" '.[] | select(.id==$id) | .host // ""' "$WISD_NODES_FILE" 2>/dev/null)
    fi
    json_header
    cat <<JSON
{
  "ok": true,
  "enabled": $enabled,
  "running": $running,
  "mode": "$(json_escape "$mode")",
  "selectedId": "$(json_escape "$sel")",
  "selectedName": "$(json_escape "$node_name")",
  "selectedHost": "$(json_escape "$node_host")",
  "started": $started,
  "elapsed": $elapsed
}
JSON
}

# Generate $WISD_XRAY_CONFIG based on mode + selected node.
#   $1 = mode (direct|tunnel)
#   $2 = node id (when tunnel)
build_config() {
    local mode=$1
    local nid=${2:-}

    # Load server-side params (the VLESS inbound on :443).
    local s_uuid s_pubkey s_privkey s_shortid s_sni s_flow s_port
    s_uuid=$(jq -r '.uuid // ""' "$WISD_SERVER_FILE")
    s_pubkey=$(jq -r '.publicKey // ""' "$WISD_SERVER_FILE")
    s_privkey=$(jq -r '.privateKey // ""' "$WISD_SERVER_FILE")
    s_shortid=$(jq -r '.shortId // ""' "$WISD_SERVER_FILE")
    s_sni=$(jq -r '.serverName // "www.cloudflare.com"' "$WISD_SERVER_FILE")
    s_flow=$(jq -r '.flow // "xtls-rprx-vision"' "$WISD_SERVER_FILE")
    s_port=$(jq -r '.port // 443' "$WISD_SERVER_FILE")

    local out_node='{}'
    if [[ "$mode" == "tunnel" ]]; then
        out_node=$(jq --argjson id "${nid:-0}" '.[] | select(.id==$id)' "$WISD_NODES_FILE")
        if [[ -z "$out_node" || "$out_node" == "null" ]]; then
            return 2
        fi
    fi

    # Build with a single jq call for atomicity.
    jq -n --arg log "$WISD_LOG_DIR/xray.log" \
          --arg access "$WISD_LOG_DIR/access.log" \
          --arg sUuid "$s_uuid" \
          --arg sPriv "$s_privkey" \
          --arg sShort "$s_shortid" \
          --arg sSni "$s_sni" \
          --arg sFlow "$s_flow" \
          --argjson sPort "$s_port" \
          --arg mode "$mode" \
          --argjson node "$out_node" '
    def server_inbound:
      {
        tag: "vless-in",
        listen: "0.0.0.0",
        port: $sPort,
        protocol: "vless",
        settings: {
          clients: [{ id: $sUuid, flow: $sFlow }],
          decryption: "none"
        },
        streamSettings: {
          network: "tcp",
          security: "reality",
          realitySettings: {
            show: false,
            dest: ($sSni + ":443"),
            xver: 0,
            serverNames: [$sSni],
            privateKey: $sPriv,
            shortIds: [$sShort]
          }
        },
        sniffing: { enabled: true, destOverride: ["http","tls","quic"] }
      };
    def local_socks:
      { tag: "socks-in", listen: "127.0.0.1", port: 1080,
        protocol: "socks", settings: { auth: "noauth", udp: true } };
    def local_http:
      { tag: "http-in", listen: "127.0.0.1", port: 1081,
        protocol: "http", settings: {} };
    def freedom_out:
      { tag: "direct", protocol: "freedom", settings: {} };
    def blocked_out:
      { tag: "blocked", protocol: "blackhole", settings: {} };
    def vless_outbound($n):
      {
        tag: "tunnel",
        protocol: "vless",
        settings: {
          vnext: [{
            address: $n.host,
            port: ($n.port // 443),
            users: [{
              id: $n.uuid,
              encryption: ($n.encryption // "none"),
              flow: ($n.flow // "")
            }]
          }]
        },
        streamSettings: ({
          network: ($n.type // "tcp"),
          security: ($n.security // "none")
        }
        + ( if ($n.security // "none") == "reality" then
              { realitySettings: {
                  show: false,
                  fingerprint: ($n.fingerprint // "chrome"),
                  serverName: ($n.sni // ""),
                  publicKey: $n.publicKey,
                  shortId: $n.shortId,
                  spiderX: "/"
                } }
            elif ($n.security // "none") == "tls" then
              { tlsSettings: {
                  serverName: ($n.sni // $n.host),
                  fingerprint: ($n.fingerprint // "chrome"),
                  allowInsecure: false
                } }
            else {} end )
        + ( if ($n.type // "tcp") == "grpc" then
              { grpcSettings: { serviceName: ($n.serviceName // "grpc"),
                                 multiMode: false } }
            elif ($n.type // "tcp") == "ws" then
              { wsSettings: { path: ($n.path // "/"),
                              headers: { Host: ($n.headerHost // $n.host) } } }
            else {} end )
        )
      };
    {
      log: { loglevel: "warning", error: $log, access: $access },
      inbounds: [ server_inbound, local_socks, local_http ],
      outbounds: (
        if $mode == "tunnel" then
          [ vless_outbound($node), freedom_out, blocked_out ]
        else
          [ freedom_out, blocked_out ]
        end
      ),
      routing: {
        domainStrategy: "IPIfNonMatch",
        rules: (
          if $mode == "tunnel" then
            [
              { type: "field", inboundTag: ["vless-in"], outboundTag: "tunnel" },
              { type: "field", inboundTag: ["socks-in","http-in"], outboundTag: "tunnel" }
            ]
          else
            [
              { type: "field", inboundTag: ["vless-in","socks-in","http-in"], outboundTag: "direct" }
            ]
          end
        )
      }
    }' > "$WISD_XRAY_CONFIG.new" || return 1
    mv "$WISD_XRAY_CONFIG.new" "$WISD_XRAY_CONFIG"
    return 0
}

apply_state() {
    local mode=$1 nid=${2:-}
    build_config "$mode" "$nid"
    case $? in
        2) json_error 21 "selected node not found" ;;
        0) ;;
        *) json_error 22 "config build failed" ;;
    esac
    echo "$mode" > "$WISD_MODE_FILE"
    if [[ "$mode" == "tunnel" && -n "$nid" ]]; then
        echo "$nid" > "$WISD_NODE_FILE"
    else
        rm -f "$WISD_NODE_FILE"
    fi
    date -u +%s > "$WISD_STARTED_FILE"
    if ! service_call restart; then
        json_error 23 "service restart failed"
    fi
}

case "$ACTION" in
    status)
        status_json
        ;;
    up)
        mode=${QPARAM[mode]:-direct}
        [[ "$mode" == "direct" || "$mode" == "tunnel" ]] || json_error 10 "invalid mode"
        nid=${QPARAM[id]:-}
        if [[ "$mode" == "tunnel" && -z "$nid" ]]; then
            json_error 11 "tunnel mode needs id"
        fi
        apply_state "$mode" "$nid"
        echo up > "$WISD_STATE_FILE"
        status_json
        ;;
    down)
        echo down > "$WISD_STATE_FILE"
        rm -f "$WISD_STARTED_FILE"
        if ! service_call stop; then
            json_error 30 "service stop failed"
        fi
        status_json
        ;;
    restart)
        mode=${QPARAM[mode]:-}
        nid=${QPARAM[id]:-}
        [[ -z "$mode" && -f "$WISD_MODE_FILE" ]] && mode=$(cat "$WISD_MODE_FILE")
        [[ -z "$mode" ]] && mode=direct
        [[ -z "$nid" && -f "$WISD_NODE_FILE" ]] && nid=$(cat "$WISD_NODE_FILE")
        apply_state "$mode" "$nid"
        status_json
        ;;
    clearlogs)
        : > "$WISD_LOG_DIR/xray.log" 2>/dev/null || true
        : > "$WISD_LOG_DIR/access.log" 2>/dev/null || true
        json_ok "\"message\":\"logs cleared\""
        ;;
    *)
        status_json
        ;;
esac
