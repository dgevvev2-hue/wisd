// wisd VLESS-over-WS relay via Cloudflare Worker.
//
// Purpose: bypass "whitelist" filters that drop traffic to arbitrary IPs.
// The client connects to *.workers.dev (Cloudflare anycast IP, normally
// allowed even under TSPU whitelisting) and the Worker proxies the
// WebSocket upgrade to nginx on the VPS:80 path /<WS_PATH>, which in
// turn passes it to the xray VLESS-WS inbound on 127.0.0.1:10443.
//
// Deploy:
//   1. https://dash.cloudflare.com/sign-up — make a free account.
//   2. npm install -g wrangler
//   3. wrangler login
//   4. mkdir wisd-relay && cd wisd-relay
//   5. Create wrangler.toml with the contents from cloudflare-worker.wrangler.toml.
//   6. mkdir src && cp ../cloudflare-worker.js src/index.js  (this file)
//   7. Edit the constants below: VPS_HOST and WS_PATH.
//   8. wrangler deploy
//
// After deploy you'll see something like:
//   Published wisd-relay
//      https://wisd-relay.<your-account>.workers.dev
//
// Plug that hostname into /var/lib/wisd/server.json as ".cfWorkerHost"
// on the VPS, then the panel's "Этот VPS" tab will show the CF-proxied URL.
//
// ────────────────────────────────────────────────────────────────────────
// EDIT THESE TO MATCH YOUR VPS
// ────────────────────────────────────────────────────────────────────────
const VPS_HOST = '194.33.61.218';
const WS_PATH  = '/150bc9329af8';

// nginx on VPS:80 listens on the wsPath and proxies WS upgrades to xray.
// We forward via standard fetch — Cloudflare supports WebSocket upgrade
// in fetch() to any HTTP/HTTPS hostname on standard ports.
export default {
    async fetch(request) {
        const url = new URL(request.url);

        // Friendly response on root so it doesn't 404 in browser checks.
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

        // Forward the WebSocket upgrade to nginx on the VPS.
        const backendUrl = `http://${VPS_HOST}${WS_PATH}`;
        try {
            return fetch(backendUrl, request);
        } catch (err) {
            return new Response('backend unreachable: ' + err.message, { status: 502 });
        }
    },
};
