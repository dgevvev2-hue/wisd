// wisd VLESS-WS relay via Cloudflare Worker.
//
// Bypasses whitelist filters that drop traffic to arbitrary IPs by
// terminating the client's WSS connection at a Cloudflare anycast IP
// (*.workers.dev) and forwarding the WebSocket upgrade to nginx on the
// VPS, which proxies it to xray's VLESS-WS inbound on 127.0.0.1:10443.
//
// Chain:
//   client (wss://*.workers.dev:443)
//       -> CF edge -> this Worker
//          -> fetch() upgrades a WebSocket to http://<VPS>:80/<WS_PATH>
//             -> nginx :80 (proxies the upgrade)
//                -> xray VLESS-WS inbound on 127.0.0.1:10443
//
// Deploy:
//   1. https://dash.cloudflare.com/sign-up — free account.
//   2. npm install -g wrangler && wrangler login
//   3. mkdir wisd-relay && cd wisd-relay && mkdir src
//   4. Copy deploy/cloudflare-worker.wrangler.toml -> wrangler.toml
//   5. Copy this file -> src/index.js
//   6. Edit the VPS_HOST / WS_PATH constants below if your install differs.
//   7. wrangler deploy
//
// wrangler prints the *.workers.dev URL. Plug that hostname into
// /var/lib/wisd/server.json as ".cfWorkerHost" on the VPS, then the
// panel's "Этот VPS" tab will show the CF-proxied vless://… URL.
//
// IMPORTANT — sslip.io dance:
//   Cloudflare's egress refuses fetch() requests to bare-IP HTTP servers
//   with the error "Direct IP access not allowed" (CF code 1003), so we
//   resolve the VPS through sslip.io's magic DNS service. The hostname
//   <dashed-ip>.sslip.io always resolves to that IP, so it requires no
//   DNS setup of your own.
//
// ────────────────────────────────────────────────────────────────────────
// EDIT THESE TO MATCH YOUR VPS
// ────────────────────────────────────────────────────────────────────────
const VPS_HOST = '194-33-61-218.sslip.io';
const VPS_PORT = 80;
const WS_PATH  = '/150bc9329af8';

export default {
    async fetch(request) {
        const url = new URL(request.url);
        const upgrade = request.headers.get('Upgrade');

        if (!upgrade || upgrade.toLowerCase() !== 'websocket') {
            return new Response('wisd-relay: online', {
                status: 200,
                headers: { 'content-type': 'text/plain' },
            });
        }
        if (url.pathname !== WS_PATH) {
            return new Response('not found', { status: 404 });
        }

        const backendUrl = `http://${VPS_HOST}:${VPS_PORT}${WS_PATH}`;
        let backendResp;
        try {
            // Reuse the original request so the WS upgrade headers
            // (Sec-WebSocket-*, Upgrade, Connection) reach the backend
            // unchanged. CF runtime then exposes the upgraded connection
            // via response.webSocket.
            backendResp = await fetch(backendUrl, request);
        } catch (err) {
            return new Response('backend unreachable: ' + err.message, { status: 502 });
        }

        if (backendResp.status !== 101 || !backendResp.webSocket) {
            return new Response(
                'backend did not upgrade: status=' + backendResp.status,
                { status: 502 }
            );
        }
        return backendResp;
    },
};
