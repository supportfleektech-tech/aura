# AURA OS — Mobile: PWA status + native-app scoping

## What ships today (v1.4.0, PWA)

- Installable: `manifest.webmanifest` + captured `beforeinstallprompt` with a
  TopBar install button (`frontend/src/install.ts`, `public/sw.js` v2).
- Offline-tolerant: service worker is cache-first for assets and falls back to
  `/` for navigations, so the shell loads without a network (data calls fail
  soft with toasts, same as desktop).
- Phone-friendly: safe-area bottom nav, 16px inputs (no iOS focus zoom),
  40–48px touch targets, sticky chat composer.
- Push: Web Push subscribe/test/unsubscribe flows work on Android/Chrome;
  **iOS Safari supports Web Push only for installed (added-to-Home-Screen)
  PWAs on 16.4+**, and there is no background sync on iOS.

This is the recommended mobile story for now: open the server URL on the
phone, Add to Home Screen, enable push. No app store, no build pipeline.

## Native-app scoping (not built — decision record)

**Option A — Capacitor wrapper (recommended if a store app is wanted).**
Wrap the existing Vite build with Capacitor (or Tauri Mobile). Reuse: 100% of
the UI, the API client, push (via FCM/APNs plugins instead of Web Push).
New work: native project shells + icons/splash (~1 day), push-plugin swap
(~1–2 days), native file-share/keychain hardening (~2–3 days), store
listings + review buffer (~1 week elapsed). Roughly **1–2 weeks** for
TestFlight/Play-internal builds. Risk: low; the web app is already the product.

**Option B — Full native (Swift/Kotlin).** Rewrite UI per platform against the
same `/api/*` contracts (SSE chat, same JSON shapes — the API is Flanders
clean). Effort: **6–10 weeks** for parity with Home/Chat plus one or two
workspaces; full parity (all 12+ views, EN/SW, voice) is a multi-month
project. Justified only if offline-first with on-device LLM (Core ML/NNAPI)
or rich widgets become requirements.

**Option C — React Native / Expo.** Middle ground (~3–5 weeks to a solid v1),
but it forks the UI codebase: every future web feature must be rebuilt for
mobile. Only pick this if the web UI is slated for replacement anyway.

**Recommendation:** stay on the PWA. If a store presence is required, do
Option A. Revisit Option B when/if on-device inference or OS-level widgets
(calendar, lock-screen brief) become must-haves — the `/api/briefings`,
`/api/calendar`, and `/api/sync` contracts are already shaped to feed them.
