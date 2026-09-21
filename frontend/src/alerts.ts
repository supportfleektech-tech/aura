import { getServer, loadUiPrefs, serverLoaded } from "./prefs";

export function inQuietHours(now = new Date()): boolean {
  const start = String(getServer("quiet_start", ""));
  const end = String(getServer("quiet_end", ""));
  if (!start || !end) return false;
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(start) || !/^([01]\d|2[0-3]):[0-5]\d$/.test(end)) return true;
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: String(getServer("timezone", "Africa/Nairobi")),
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).formatToParts(now);
    const current = `${parts.find((p) => p.type === "hour")!.value}:${parts.find((p) => p.type === "minute")!.value}`;
    return start > end ? current >= start || current < end : current >= start && current < end;
  } catch {
    return true;
  }
}

export async function playAlertSound(preview = false): Promise<boolean> {
  if ((!preview && !loadUiPrefs().alertSound) || !serverLoaded() || inQuietHours()) return false;
  let ctx: AudioContext | undefined;
  let oscillator: OscillatorNode | undefined;
  let gain: GainNode | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    clearTimeout(timer);
    if (oscillator) oscillator.onended = null;
    try { oscillator?.disconnect(); } catch {}
    try { gain?.disconnect(); } catch {}
    try { if (ctx && ctx.state !== "closed") void ctx.close().catch(() => undefined); } catch {}
  };
  try {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return false;
    ctx = new AC();
    const expired = new Promise<false>((resolve) => {
      timer = setTimeout(() => { cleanup(); resolve(false); }, 1500);
    });
    if (ctx.state === "suspended") {
      const resumed = await Promise.race([ctx.resume().then(() => true), expired]);
      if (!resumed || cleaned) { cleanup(); return false; }
    }
    if (ctx.state !== "running") { cleanup(); return false; }
    oscillator = ctx.createOscillator();
    gain = ctx.createGain();
    oscillator.frequency.value = 660;
    gain.gain.setValueAtTime(0.06, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.18);
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    oscillator.onended = cleanup;
    oscillator.start();
    oscillator.stop(ctx.currentTime + 0.2);
    return true;
  } catch {
    cleanup();
    return false;
  }
}

export function createApprovalAlerts(): (ids: number[]) => void {
  const seen = new Set<number>();
  return (ids) => {
    let fresh = false;
    for (const id of ids) {
      if (!Number.isSafeInteger(id) || id <= 0 || seen.has(id)) continue;
      seen.add(id);
      fresh = true;
    }
    if (!fresh || !serverLoaded() || inQuietHours()) return;
    void playAlertSound();
    try {
      if (!loadUiPrefs().desktopApprovalAlerts || !document.hidden || typeof Notification === "undefined" || Notification.permission !== "granted") return;
      new Notification("AURA approval needed", {
        body: "Open AURA to review pending approvals.", tag: "aura-approval", silent: true,
      });
    } catch {}
  };
}
