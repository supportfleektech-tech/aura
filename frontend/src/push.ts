/* Web Push client helpers. */
import { api } from "./api";

export const urlBase64ToUint8Array = (b64: string) => {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
};

export const pushSupported = () =>
  typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window;

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

export async function subscribePush(): Promise<{ endpoint: string }> {
  const { key, configured } = await api.push.vapidKey();
  if (!configured || !key) throw new Error("Server push not configured (missing VAPID keys)");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Notification permission denied");
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(key),
  });
  const raw = sub.toJSON();
  await api.push.subscribe({
    endpoint: raw.endpoint,
    keys: { p256dh: raw.keys?.p256dh, auth: raw.keys?.auth },
  });
  return { endpoint: raw.endpoint || "" };
}

export async function unsubscribePush(): Promise<void> {
  const sub = await currentSubscription();
  const endpoint = sub?.endpoint;
  if (sub) await sub.unsubscribe();
  if (endpoint) await api.push.unsubscribe(endpoint).catch(() => undefined);
}
