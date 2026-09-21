export type MediaKind = "audio" | "video";
export type RepeatMode = "off" | "one" | "all";
export interface MediaItem {
  id: string;
  name: string;
  kind: MediaKind;
  source: "local" | "stream";
  size?: number;
  modified?: number;
  mime?: string;
  file?: File;
  url?: string;
}

const KEY = "aura-media-playlist-v1";
const LIMIT = 100;
const MAX_FILE = 2 * 1024 ** 3;
const TYPES: Record<string, string> = {
  mp3: "audio/mpeg", wav: "audio/wav", ogg: "audio/ogg", oga: "audio/ogg", flac: "audio/flac", m4a: "audio/mp4", aac: "audio/aac", opus: "audio/ogg",
  mp4: "video/mp4", m4v: "video/mp4", webm: "video/webm", ogv: "video/ogg", mov: "video/quicktime",
};

export function publicStreamUrl(input: string): string {
  const url = new URL(input.trim());
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  const ipv4 = /^\d+\.\d+\.\d+\.\d+$/.test(host);
  if (input.length > 2048 || url.protocol !== "https:" || url.username || url.password || !host.includes(".") || host.includes(":") || ipv4 || /(^|\.)(localhost|local|internal|lan|home|test|invalid)$/.test(host)) {
    throw new Error("Use a public HTTPS media URL without credentials, local hostnames or IP literals.");
  }
  return url.href;
}

export function streamItem(input: string, kind: MediaKind): MediaItem {
  const url = publicStreamUrl(input);
  return { id: crypto.randomUUID(), name: new URL(url).hostname + new URL(url).pathname, source: "stream", kind, url };
}

export function importFiles(queue: MediaItem[], files: File[]): { items: MediaItem[]; errors: string[] } {
  const items = [...queue];
  const errors: string[] = [];
  for (const file of files) {
    const mime = file.type || TYPES[file.name.split(".").pop()?.toLowerCase() || ""] || "";
    if (!/^(audio|video)\//.test(mime) || !file.size || file.size > MAX_FILE) {
      errors.push(`${file.name}: choose a non-empty audio/video file up to 2 GiB.`);
      continue;
    }
    const index = items.findIndex((item) => item.source === "local" && item.name === file.name && item.size === file.size && item.modified === file.lastModified);
    if (index < 0 && items.length >= LIMIT) {
      errors.push("Queue limit is 100 items. Remove items before importing more.");
      break;
    }
    const item: MediaItem = { id: index < 0 ? crypto.randomUUID() : items[index].id, name: file.name, source: "local", kind: mime.startsWith("video/") ? "video" : "audio", size: file.size, modified: file.lastModified, mime, file };
    if (index < 0) items.push(item);
    else items[index] = item;
  }
  return { items, errors };
}

export function savePlaylist(items: MediaItem[]): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(items.slice(0, LIMIT).map(({ id, name, kind, source, size, modified, mime, url }) =>
      source === "local" ? { id, name, kind, source, size, modified, mime } : { id, name, kind, source, url })));
    return true;
  } catch {
    return false;
  }
}

export function loadPlaylist(): { items: MediaItem[]; warning: string } {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { items: [], warning: "" };
    if (raw.length > 500000) throw new Error();
    const data: unknown = JSON.parse(raw);
    if (!Array.isArray(data) || data.length > LIMIT) throw new Error();
    const ids = new Set<string>();
    const items: MediaItem[] = data.map((value: unknown): MediaItem => {
      if (!value || typeof value !== "object") throw new Error();
      const item = value as Record<string, unknown>;
      if (typeof item.id !== "string" || item.id.length > 100 || ids.has(item.id) || typeof item.name !== "string" || item.name.length > 2300 || (item.kind !== "audio" && item.kind !== "video")) throw new Error();
      ids.add(item.id);
      const base = { id: item.id, name: item.name, kind: item.kind };
      if (item.source === "stream" && typeof item.url === "string") return { ...base, source: "stream", url: publicStreamUrl(item.url) } as MediaItem;
      if (item.source !== "local" || typeof item.size !== "number" || !Number.isFinite(item.size) || item.size <= 0 || item.size > MAX_FILE || typeof item.modified !== "number" || !Number.isFinite(item.modified)) throw new Error();
      return { ...base, source: "local", size: item.size, modified: item.modified, mime: typeof item.mime === "string" ? item.mime.slice(0, 200) : "" } as MediaItem;
    });
    return { items, warning: "" };
  } catch {
    return { items: [], warning: "Saved playlist could not be read. Import files again; no media was uploaded." };
  }
}

export function moveItem(items: MediaItem[], id: string, direction: -1 | 1): MediaItem[] {
  const index = items.findIndex((item) => item.id === id);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= items.length) return items;
  const result = [...items];
  [result[index], result[target]] = [result[target], result[index]];
  return result;
}

export function nextItem(items: MediaItem[], id: string | null, direction: -1 | 1, repeat: RepeatMode, shuffle: boolean, random = Math.random): MediaItem | undefined {
  const playable = items.filter((item) => item.source === "stream" || item.file);
  const index = playable.findIndex((item) => item.id === id);
  if (!playable.length) return undefined;
  if (index < 0) return direction === 1 ? playable[0] : playable[playable.length - 1];
  if (repeat === "one") return playable[index];
  if (shuffle && playable.length > 1) {
    const others = playable.filter((item) => item.id !== id);
    return others[Math.min(others.length - 1, Math.max(0, Math.floor(random() * others.length)))];
  }
  const target = index + direction;
  return repeat === "all" ? playable[(target + playable.length) % playable.length] : playable[target];
}
