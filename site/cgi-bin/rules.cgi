#!/bin/bash
# rules.cgi -- per-domain / per-IP routing overrides.
DIR=$(dirname "$0")
. "$DIR/lib.sh"
require_jq

parse_query
read_post_body

ACTION=${QPARAM[action]:-get}

[[ -f "$WISD_RULES_FILE" ]] || echo '{"direct":[],"tunnel":[]}' > "$WISD_RULES_FILE"

case "$ACTION" in
    get)
        json_header
        cat "$WISD_RULES_FILE"
        ;;
    set)
        # POST body: JSON object {direct:[...], tunnel:[...]}
        if [[ -z "$POST_BODY" ]]; then
            json_error 10 "empty body"
        fi
        if ! jq -e '.' >/dev/null 2>&1 <<<"$POST_BODY"; then
            json_error 11 "invalid JSON"
        fi
        jq '{direct: (.direct // [] | map(tostring)),
             tunnel: (.tunnel // [] | map(tostring))}' \
            <<<"$POST_BODY" > "$WISD_RULES_FILE.tmp" && \
            mv "$WISD_RULES_FILE.tmp" "$WISD_RULES_FILE"
        json_ok ""
        ;;
    *)
        json_error 99 "unknown action: $ACTION"
        ;;
esac
