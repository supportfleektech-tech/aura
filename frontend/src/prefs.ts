/* AURA OS preferences — local UI prefs (instant, per-browser) + cached server settings. */
import { api } from "./api";

export type Theme = "dark" | "darker" | "light";
export type Accent = "violet" | "blue" | "green" | "amber" | "rose";
export type Density = "comfortable" | "compact";

export interface UiPrefs {
  theme: Theme;
  accent: Accent;
  density: Density;
  fontScale: number;
  alertSound: boolean;
  desktopApprovalAlerts: boolean;
}

const UI_KEY = "aura-ui-prefs";
const DEFAULT_UI: UiPrefs = { theme: "dark", accent: "violet", density: "comfortable", fontScale: 1, alertSound: false, desktopApprovalAlerts: false };

export function loadUiPrefs(): UiPrefs {
  try {
    const raw = localStorage.getItem(UI_KEY);
    if (!raw) return { ...DEFAULT_UI };
    const p = { ...DEFAULT_UI, ...JSON.parse(raw) };
    if (!["dark", "darker", "light"].includes(p.theme)) p.theme = "dark";
    if (!["violet", "blue", "green", "amber", "rose"].includes(p.accent)) p.accent = "violet";
    if (!["comfortable", "compact"].includes(p.density)) p.density = "comfortable";
    p.fontScale = Math.min(1.2, Math.max(0.85, Number(p.fontScale) || 1));
    p.alertSound = p.alertSound === true;
    p.desktopApprovalAlerts = p.desktopApprovalAlerts === true;
    return p;
  } catch {
    return { ...DEFAULT_UI };
  }
}

export function saveUiPrefs(p: UiPrefs) {
  try { localStorage.setItem(UI_KEY, JSON.stringify(p)); } catch { /* private mode */ }
  applyUiPrefs(p);
}

export function applyUiPrefs(p: UiPrefs = loadUiPrefs()) {
  const el = document.documentElement;
  el.dataset.theme = p.theme;
  el.dataset.accent = p.accent;
  el.dataset.density = p.density;
  document.body.style.fontSize = `${13.5 * p.fontScale}px`;
}

/* ---------------- server settings cache (sync reads for hot paths) ---------------- */
let cache: Record<string, unknown> = {};
let loaded = false;

export async function loadServerSettings(): Promise<Record<string, unknown>> {
  try {
    const r = await api.settings.get();
    cache = { ...r.values };
    loaded = true;
  } catch {
    /* offline — fall back to defaults */
  }
  return cache;
}

export function setServerCache(values: Record<string, unknown>) {
  cache = { ...cache, ...values };
  loaded = true;
}

export function getServer<T>(key: string, fallback: T): T {
  const v = cache[key];
  return (v === undefined || v === null ? fallback : v) as T;
}

export type VoiceEngine = "browser" | "piper" | "edge" | "kokoro";

export function voicePreferenceKey(engine: string): string {
  return engine === "kokoro" ? "voice_kokoro_id" : engine === "piper" ? "voice_piper_id" : engine === "edge" ? "voice_edge_id" : "voice_browser_name";
}

export const PERSONALITY_FIELDS = [
  { key: "ai_warmth", label: "Warmth", fallback: "warm", options: ["neutral", "warm", "supportive"] },
  { key: "ai_humour", label: "Humour", fallback: "off", options: ["off", "light", "playful"] },
  { key: "ai_style", label: "Style", fallback: "conversational", options: ["conversational", "professional", "direct"] },
  { key: "ai_pacing", label: "Pacing", fallback: "balanced", options: ["concise", "balanced", "unhurried"] },
] as const;

export function serverLoaded() {
  return loaded;
}
