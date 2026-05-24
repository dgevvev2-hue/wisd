# wisd Cloudflare Worker relay (whitelist bypass)

A Cloudflare Worker that proxies WebSocket traffic from a free `*.workers.dev`
hostname to the wisd VPS. This lets clients connect via a Cloudflare IP
(which is normally allowed even under TSPU "white-list" filtering) instead of
hitting the VPS IP directly.

## Architecture

```
[client] --wss--> [<name>.workers.dev:443]  -- (Cloudflare network) -->  [Worker]  --ws--> [VPS:10443]
                       Cloudflare IP                                                       VLESS-WS inbound (xray)
                       (whitelisted)                                                       (already deployed)
```

The Worker only forwards WebSocket frames. VLESS auth (UUID) is end-to-end —
Cloudflare never sees plaintext traffic.

## Deploy

You need:
- A Cloudflare account (free): https://dash.cloudflare.com/sign-up
- Node.js + npm on your local machine.

```bash
# 1) Install Wrangler
npm install -g wrangler

# 2) Log in (opens a browser)
wrangler login

# 3) Create an empty Worker project
wrangler init wisd-relay --no-deploy
cd wisd-relay

# 4) Overwrite src/index.js with the contents of cloudflare-worker.js
#    from this directory. Adjust VPS_HOST/VPS_PORT/WS_PATH at the top
#    if your VPS doesn't match the defaults.

# 5) Deploy
wrangler deploy
```

Wrangler prints something like:
```
Published wisd-relay
   https://wisd-relay.<account>.workers.dev
```

That hostname goes into your client URL below.

## Client URL

The wisd panel ("Этот VPS" tab) generates the full client URL after you
plug the Worker hostname into `server.json` — or build it manually:

```
vless://<UUID>@<worker-host>:443?encryption=none&security=tls&type=ws&path=<wsPath>&host=<worker-host>&sni=<worker-host>&fp=chrome#wisd-cf-ws
```

- `<UUID>` = `server.json` → `.uuid`
- `<worker-host>` = `wisd-relay.<account>.workers.dev`
- `<wsPath>` = `server.json` → `.wsPath`

Paste into Hiddify Next / NekoBox / v2rayN. The client connects to
Cloudflare's network on TCP:443/TLS, the Worker upgrades to WebSocket, and
the WS frames are forwarded to your VPS on port 10443.

## Why this defeats whitelisting

Under "whitelist" filtering (e.g. during regional alerts in RU), traffic to
arbitrary VPS IPs is dropped at the network edge. But:

- `*.workers.dev` resolves to Cloudflare's anycast IPs.
- Cloudflare IPs are used by госуслуги, банки, СМИ — they cannot be
  blocked without breaking large portions of "approved" traffic.
- Inside Cloudflare's network, the Worker reaches the VPS via the public
  internet — but this leg is invisible from the client's ISP.

Limitations:
- A worker is rate-limited on the free tier (100k requests/day, 10ms CPU
  per request — plenty for VPN forwarding, since per-request CPU is tiny).
- Cloudflare can revoke the Worker if it's used for clearly abusive
  traffic. Keep your Worker private; don't share the URL publicly.
