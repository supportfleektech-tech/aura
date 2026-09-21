import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, chatStream } from "../api";
import { StoreProvider, useStore } from "../store";
import { CallOverlay } from "../views4";
import { ChatThread } from "../ui";
import { LangProvider } from "../i18n";
import { setServerCache } from "../prefs";

vi.mock("../api", async (original) => ({ ...await original<typeof import("../api")>(), chatStream: vi.fn() }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

class AudioMock {
  static instances: AudioMock[] = [];
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  play = vi.fn().mockResolvedValue(undefined);
  pause = vi.fn();
  removeAttribute = vi.fn();
  load = vi.fn();
  constructor(public src: string) { AudioMock.instances.push(this); }
}
class Recognition {
  static instances: Recognition[] = [];
  onresult: ((e: unknown) => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn(() => this.onend?.());
  abort = vi.fn();
  constructor() { Recognition.instances.push(this); }
}
const synth = { speak: vi.fn(), cancel: vi.fn(), getVoices: () => [] };

beforeEach(() => {
  vi.clearAllMocks();
  AudioMock.instances = []; Recognition.instances = [];
  vi.stubGlobal("Audio", AudioMock);
  vi.stubGlobal("speechSynthesis", synth);
  vi.stubGlobal("SpeechSynthesisUtterance", class { constructor(public text: string) {} });
  vi.stubGlobal("SpeechRecognition", Recognition);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ services: [], approvals: [], values: {}, secrets: {}, sources: {} }) })));
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  setServerCache({ voice_engine: "edge" });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); setServerCache({}); });

async function store() {
  const hook = renderHook(() => useStore(), { wrapper: StoreProvider });
  await act(async () => { await hook.result.current.refresh(); });
  setServerCache({ voice_engine: "edge" });
  return hook;
}

describe("speech interruption", () => {
  it("offers an ordinary chat stop button while audio is still being prepared", async () => {
    const pending = deferred<string>();
    vi.spyOn(api.voice, "speakUrl").mockReturnValue(pending.promise);
    function Harness() {
      const { speak } = useStore();
      return <><button onClick={() => speak("Hello")}>Start speech</button><ChatThread /></>;
    }
    await act(async () => { render(<StoreProvider><Harness /></StoreProvider>); });
    setServerCache({ voice_engine: "kokoro" });
    fireEvent.click(screen.getByRole("button", { name: "Start speech" }));
    fireEvent.click(screen.getByRole("button", { name: "Stop speaking" }));
    await act(async () => pending.resolve("blob:cancelled-chat"));
    expect(AudioMock.instances).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Stop speaking" })).not.toBeInTheDocument();
  });
  it("routes Kokoro through server speech with its selected voice and completes once", async () => {
    const pending = deferred<string>();
    const request = vi.spyOn(api.voice, "speakUrl").mockReturnValue(pending.promise);
    const done = vi.fn();
    const { result } = await store();
    setServerCache({ voice_engine: "kokoro", voice_kokoro_id: "bf_emma" });
    act(() => result.current.speak("Hello", done));
    expect(result.current.speaking).toBe(true);
    expect(request).toHaveBeenCalledWith("Hello", expect.objectContaining({ engine: "kokoro", voice: "bf_emma" }), expect.any(AbortSignal));
    expect(synth.speak).not.toHaveBeenCalled();
    expect(done).not.toHaveBeenCalled();
    await act(async () => pending.resolve("blob:kokoro"));
    const ended = AudioMock.instances[0].onended!;
    act(() => { ended(); ended(); });
    expect(done).toHaveBeenCalledTimes(1);
    expect(result.current.speaking).toBe(false);
  });
  it("never completes cancelled speech even after a stale end event", async () => {
    vi.spyOn(api.voice, "speakUrl").mockResolvedValue("blob:first");
    const done = vi.fn();
    const { result } = await store();
    await act(async () => result.current.speak("Hello", done));
    const ended = AudioMock.instances[0].onended!;
    act(() => { result.current.stopSpeak(); ended(); });
    expect(done).not.toHaveBeenCalled();
  });
  it("completes failed synthesis and empty speech without getting stuck", async () => {
    vi.spyOn(api.voice, "speakUrl").mockRejectedValue(new Error("missing assets"));
    const done = vi.fn();
    const { result } = await store();
    await act(async () => result.current.speak("Hello", done));
    expect(done).toHaveBeenCalledTimes(1);
    expect(result.current.speaking).toBe(false);
    act(() => result.current.speak(" ", done));
    expect(done).toHaveBeenCalledTimes(2);
  });
  it("does not play a deferred TTS response after stop", async () => {
    const pending = deferred<string>();
    vi.spyOn(api.voice, "speakUrl").mockReturnValue(pending.promise);
    const { result } = await store();
    act(() => result.current.speak("first"));
    act(() => result.current.stopSpeak());
    await act(async () => pending.resolve("blob:late"));
    expect(AudioMock.instances).toHaveLength(0);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:late");
    expect(result.current.speaking).toBe(false);
  });
  it("only plays the latest out of order speech and ignores old failures", async () => {
    const first = deferred<string>(), second = deferred<string>();
    vi.spyOn(api.voice, "speakUrl").mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result } = await store();
    act(() => { result.current.speak("first"); result.current.speak("second"); });
    await act(async () => second.resolve("blob:second"));
    await act(async () => first.resolve("blob:first"));
    expect(AudioMock.instances.map((a) => a.src)).toEqual(["blob:second"]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:first");
    expect(result.current.speaking).toBe(true);
  });
  it("releases audio on stop and ignores a captured ended callback", async () => {
    vi.spyOn(api.voice, "speakUrl").mockResolvedValue("blob:first");
    const { result } = await store();
    await act(async () => result.current.speak("first"));
    const audio = AudioMock.instances[0], ended = audio.onended;
    act(() => result.current.stopSpeak());
    expect(audio.pause).toHaveBeenCalled();
    expect(audio.onended).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:first");
    await act(async () => result.current.speak("second"));
    act(() => ended?.());
    expect(result.current.speaking).toBe(true);
  });
  it("aborts pending speech on unmount and discards its result", async () => {
    const pending = deferred<string>();
    const speak = vi.spyOn(api.voice, "speakUrl").mockReturnValue(pending.promise);
    const { result, unmount } = await store();
    act(() => result.current.speak("first"));
    unmount();
    await act(async () => pending.resolve("blob:unmounted"));
    expect(AudioMock.instances).toHaveLength(0);
    expect(speak.mock.calls[0][2]?.aborted).toBe(true);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:unmounted");
  });
  it("releases a failed audio playback URL", async () => {
    vi.spyOn(api.voice, "speakUrl").mockResolvedValue("blob:failed");
    const { result } = await store();
    await act(async () => result.current.speak("first"));
    act(() => AudioMock.instances[0].onerror?.());
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:failed");
    expect(result.current.speaking).toBe(false);
  });
});

async function call() {
  const view = render(<LangProvider><StoreProvider><CallOverlay /></StoreProvider></LangProvider>);
  await act(async () => {});
  return view;
}
function heard() {
  Recognition.instances[Recognition.instances.length - 1].onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: "hello" } }] });
}
describe("call interruption", () => {
  it.each(["Stop speaking", "mute", "hang up"])("cancels pending Kokoro audio with %s", async (control) => {
    const pending = deferred<string>();
    const request = vi.spyOn(api.voice, "speakUrl").mockReturnValue(pending.promise);
    vi.mocked(chatStream).mockImplementation(async (_text, _sid, events) => { events.onToken?.("hello back"); });
    await call();
    setServerCache({ voice_engine: "kokoro", voice_kokoro_id: "af_heart" });
    await act(async () => heard());
    expect(request).toHaveBeenCalledWith("hello back", expect.objectContaining({ engine: "kokoro", voice: "af_heart" }), expect.any(AbortSignal));
    fireEvent.click(screen.getByRole("button", { name: control }));
    expect(request.mock.calls[0][2]?.aborted).toBe(true);
    await act(async () => pending.resolve("blob:late-call"));
    expect(AudioMock.instances).toHaveLength(0);
    expect(synth.speak).not.toHaveBeenCalled();
  });
  it("returns to listening on server audio completion and allows barge-in", async () => {
    vi.spyOn(api.voice, "speakUrl").mockResolvedValue("blob:call");
    vi.mocked(chatStream).mockImplementation(async (_text, _sid, events) => { events.onToken?.("hello back"); });
    await call();
    setServerCache({ voice_engine: "kokoro" });
    await act(async () => heard());
    expect(screen.getByTestId("call-orb")).toHaveClass("speaking");
    const first = AudioMock.instances[0];
    expect(first).toBeDefined();
    await act(async () => heard());
    expect(first.pause).toHaveBeenCalled();
    expect(AudioMock.instances).toHaveLength(2);
    act(() => AudioMock.instances[1].onended?.());
    expect(screen.getByTestId("call-orb")).toHaveClass("listening");
  });
  it("does not revive a muted pending chat turn", async () => {
    const pending = deferred<void>();
    vi.mocked(chatStream).mockImplementation((_text, _sid, events) => { events.onToken?.("late answer"); return pending.promise; });
    await call();
    act(heard);
    fireEvent.click(screen.getByRole("button", { name: "mute" }));
    await act(async () => pending.resolve());
    expect(synth.speak).not.toHaveBeenCalled();
    expect(screen.getByTestId("call-orb")).toHaveClass("ready");
  });
  it("never speaks a pending chat reply after hangup", async () => {
    const pending = deferred<void>();
    vi.mocked(chatStream).mockImplementation((_text, _sid, events) => { events.onToken?.("late answer"); return pending.promise; });
    await call();
    act(heard);
    fireEvent.click(screen.getByRole("button", { name: "hang up" }));
    await act(async () => pending.resolve());
    expect(synth.speak).not.toHaveBeenCalled();
  });
  it("does not restart recognition from onend while muted", async () => {
    await call();
    const rec = Recognition.instances[Recognition.instances.length - 1];
    fireEvent.click(screen.getByRole("button", { name: "mute" }));
    expect(rec.start).toHaveBeenCalledTimes(1);
    act(() => rec.onend?.());
    expect(rec.start).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "mute" }));
    expect(rec.start).toHaveBeenCalledTimes(2);
  });
  it("never speaks pending chat after unmount", async () => {
    const pending = deferred<void>();
    vi.mocked(chatStream).mockImplementation((_text, _sid, events) => { events.onToken?.("late answer"); return pending.promise; });
    const view = await call();
    act(heard);
    view.unmount();
    await act(async () => pending.resolve());
    expect(synth.speak).not.toHaveBeenCalled();
  });
});
