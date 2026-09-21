import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { importFiles, loadPlaylist, savePlaylist, streamItem, nextItem, moveItem } from "../mediaLibrary";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

const file = (name = "song.mp3", type = "audio/mpeg") => new File(["audio"], name, { type, lastModified: 42 });

describe("local media library", () => {
  it("imports supported files without object URLs and rejects empty or unknown files", () => {
    const result = importFiles([], [file(), file("bad.txt", "text/plain"), new File([], "empty.mp3", { type: "audio/mpeg" })]);
    expect(result.items).toHaveLength(1);
    expect(result.items[0]).toMatchObject({ name: "song.mp3", kind: "audio", source: "local", file: expect.any(File) });
    expect(result.errors).toHaveLength(2);
    expect(importFiles(result.items, []).items).toEqual(result.items);
  });

  it("persists only metadata and reattaches reselected files to their original queue position", () => {
    const items = importFiles([], [file(), file("movie.webm", "video/webm")]).items;
    expect(savePlaylist(items)).toBe(true);
    expect(localStorage.getItem("aura-media-playlist-v1")).not.toContain("blob:");
    const loaded = loadPlaylist();
    expect(loaded.items).toHaveLength(2);
    expect(loaded.items[0].file).toBeUndefined();
    const restored = importFiles(loaded.items, [file()]).items;
    expect(restored).toHaveLength(2);
    expect(restored[0].id).toBe(items[0].id);
    expect(restored[0].file).toBeInstanceOf(File);
  });

  it("contains malformed storage and quota errors and enforces queue limits", () => {
    localStorage.setItem("aura-media-playlist-v1", "broken");
    expect(loadPlaylist().warning).toBeTruthy();
    expect(importFiles([], Array.from({ length: 101 }, (_, i) => file(`${i}.mp3`))).items).toHaveLength(100);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    expect(savePlaylist([])).toBe(false);
  });

  it("never restores injected blob URLs or arbitrary properties", () => {
    const items = importFiles([], [file()]).items;
    localStorage.setItem("aura-media-playlist-v1", JSON.stringify([{ ...items[0], file: {}, url: "blob:stale" }]));
    expect(loadPlaylist().items[0]).not.toHaveProperty("file");
    expect(loadPlaylist().items[0]).not.toHaveProperty("url");
  });
});

describe("stream and queue controls", () => {
  it.each(["http://example.org/a.mp3", "file:///a.mp3", "https://localhost/a", "https://127.0.0.1/a", "https://[::1]/a", "https://user:pass@example.org/a", "https://intranet/a", "https://host.local/a"])("rejects non-public or non-HTTPS input %s", (url) => {
    expect(() => streamItem(url, "audio")).toThrow();
  });

  it("accepts a direct HTTPS URL without fetching or claiming codec support", () => {
    expect(streamItem(" https://example.org/audio.mp3 ", "audio")).toMatchObject({ source: "stream", kind: "audio", url: "https://example.org/audio.mp3" });
  });

  it("moves by buttons and handles repeat, shuffle and missing files", () => {
    const items = importFiles([], [file("a.mp3"), file("b.mp3"), file("c.mp3")]).items;
    expect(moveItem(items, items[1].id, -1).map((item) => item.name)).toEqual(["b.mp3", "a.mp3", "c.mp3"]);
    expect(nextItem(items, items[2].id, 1, "off", false)).toBeUndefined();
    expect(nextItem(items, items[2].id, 1, "all", false)?.id).toBe(items[0].id);
    expect(nextItem(items, items[0].id, 1, "one", false)?.id).toBe(items[0].id);
    expect(nextItem(items, items[0].id, 1, "off", true, () => 0)?.id).toBe(items[1].id);
    expect(nextItem([{ ...items[1], file: undefined }, items[2]], items[0].id, 1, "off", false)?.id).toBe(items[2].id);
  });
});
