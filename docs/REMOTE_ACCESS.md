# AURA OS — Remote access (fortress-local + Tailscale)

AURA has no login screen by design. So it never faces the public internet
directly. The supported away-from-home story is a private Tailnet: your
server and your phone join the same encrypted network, and only your
devices can reach AURA.

## 1. Always-on host (pick one)

- **Home mini-PC / old laptop / Raspberry Pi 4+**: install Python 3.12+,
  Node 20+, Tailscale; clone the repo; `pip install -r
  backend/requirements.txt` (+ `requirements-voice.txt` for STT/TTS/wake
  word); `cd frontend && npm install && npm run build`; run the backend
  (`python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000`) under
  systemd/supervisor so it survives reboots.
- **Cheap VPS** (only if you want bots reachable 24/7 from anywhere):
  same install, plus a firewall allowing 22 + 41641/udp (Tailscale) and
  nothing else. AURA still binds to the tailnet, not the public IP.

Production serving is built in: the backend serves `frontend/dist`
(`npm run build` first — the SPA routes only mount when `dist/` exists).

## 2. Tailscale setup (10 minutes)

1. Install Tailscale on the server and on your phone (tailscale.com/download).
2. `tailscale up` on the server; log in with the same account on both.
3. Note the server's tailnet name: `tailscale status` → e.g. `aura-server`.
4. Serve AURA over **HTTPS** (required for mic + PWA install — plain
   `http://100.x` is not a secure context, so `getUserMedia` refuses):
   `tailscale serve --bg 8000`
   then open `https://aura-server.<your-tailnet>.ts.net` on the phone.
5. On the phone: Add to Home Screen (see `MOBILE.md`), enable push.

Mic, live voice loop, uploads, and push all work over that URL. Nobody
outside your tailnet can open it — there is no public surface.

## 3. Bot webhooks from the internet (optional)

Telegram webhooks and the WhatsApp Cloud handshake need a **public** URL.
Two honest options:

- **Easiest — no public URL**: Telegram `getUpdates` polling (Multi-Platform
  → Telegram → Check messages, or poll on a schedule) needs nothing inbound.
- **Public URL via Funnel**: `tailscale funnel 8000` exposes
  `https://<machine>.<tailnet>.ts.net` to the internet. Then set the
  Telegram webhook to `…/api/gateway/telegram/webhook` (with
  `webhook_secret`) or give Meta `…/api/gateway/whatsapp/webhook` for the
  handshake. Funnel can be switched off when you don't need it
  (`tailscale funnel --off`, or `tailscale serve --off`).

## 4. Go-live checklists (your two inputs)

**Telegram bot**
1. Message `@BotFather` → `/newbot` → copy the token.
2. Multi-Platform → Telegram → Configure → paste `bot_token` (+
   `default_chat_id`: message `@userinfobot`, or read it from the first
   poll result) → mode `live` → Save → Test (expect `@yourbot`).
3. Say hi to the bot, then Check messages — your text lands on the event bus.
4. Optional: `auto_reply` text, or a Funnel webhook for instant delivery.

**WhatsApp Cloud API**
1. developers.facebook.com → create app → add WhatsApp product → copy the
   temporary token + `phone_number_id` (test number works immediately).
2. Multi-Platform → WhatsApp → Configure → paste `wa_token` +
   `phone_number_id` (+ `verify_token`: any secret you invent) → `live`.
3. In the Meta dashboard set the callback URL to your Funnel URL +
   `/api/gateway/whatsapp/webhook` and the same verify token → Verify.
4. Message the test number — inbound appears on the event bus.

**Home Assistant**
1. HA → your profile → Long-Lived Access Tokens → create one.
2. Smart Home view → paste base URL + token → `live` → Connect → Test
   (expect `API running`). Sandbox mode explores with demo entities first.

## 5. Operational notes

- Keep the server on your tailnet only: bind uvicorn to
  `--host 0.0.0.0` behind the Tailscale interface is fine on a home LAN;
  on a VPS, prefer `--host 127.0.0.1` + `tailscale serve`.
- Backups: Automations → backup action on a schedule; `data/` holds the
  SQLite DB — copy it off-machine periodically.
- If you ever want public access without Tailscale, that is the point to
  add authentication first — say the word and it becomes the next build.
