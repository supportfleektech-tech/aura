/* End-to-end: a custom command's prompt must reach POST /api/chat/stream.
 *
 * FR-CMD-004 says executing a custom command "returns its prompt so the client
 * sends it as a normal message". Asserting `execute()` returns the text proves
 * nothing — the defect was entirely on the client, which rendered the prompt as
 * if AURA had said it. So these tests drive the real `StoreProvider.send`,
 * through the real `chatStream` SSE reader, over a stubbed `fetch`, and read the
 * actual request bodies.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider, useStore } from "../store";
import type { ChatMsg } from "../api";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

type Call = { url: string; body: { message?: string } | null };

/** One SSE frame. `chatStream` parses on "\n\n", exactly as the server emits. */
function frame(event: string, data: unknown) {
  return new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

function stream(chunks: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({
    start(c) { chunks.forEach((x) => c.enqueue(x)); c.close(); },
  });
}

const SLASH_RESULT = {
  handled: true, ok: true, command: "/brief",
  result: { prompt: "summarise my day", view: "" },
  text: "summarise my day", view: null,
};

/** Serve a slash reply only to a real `/`-prefixed turn, as the server does. */
function stub(slashPayload: unknown = SLASH_RESULT, alwaysSlash = false) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ url, body });
    if (url.includes("/chat/stream")) {
      const isCommand = alwaysSlash || String(body?.message || "").startsWith("/");
      const chunks = isCommand
        ? [frame("slash", slashPayload), frame("done", { session_id: "s1" })]
        : [frame("result", { text: "You had three meetings and a dentist slot.",
                             model: "m", memories_used: [] }),
           frame("done", { session_id: "s1" })];
      return { ok: true, status: 200, body: stream(chunks), json: async () => ({}), text: async () => "" };
    }
    return { ok: true, status: 200, json: async () => ({}), text: async () => "" };
  }));
  return calls;
}

let msgs: ChatMsg[] = [];
let view = "";
function Probe() {
  const s = useStore();
  msgs = s.msgs;
  view = s.view;
  return (
    <div>
      <button onClick={() => { void s.send("/brief"); }}>run</button>
      <button onClick={() => { void s.send("/task Ship it"); }}>runTask</button>
    </div>
  );
}

function renderStore() {
  return render(<LangProvider><StoreProvider><Probe /></StoreProvider></LangProvider>);
}

const chats = (calls: Call[]) => calls.filter((c) => c.url.includes("/chat/stream"));

describe("custom command prompt reaches the model — FR-CMD-004", () => {
  it("sends the command's prompt to /api/chat/stream instead of rendering it", async () => {
    const calls = stub();
    renderStore();
    fireEvent.click(screen.getByText("run"));
    await waitFor(() => expect(chats(calls).length).toBe(2));

    // The load-bearing assertion: two real turns, and the *second* one carries
    // the prompt as an ordinary user message.
    expect(chats(calls).map((c) => c.body!.message))
      .toEqual(["/brief", "summarise my day"]);

    // It must be the user who asked, so it is a user bubble — not AURA echoing.
    const prompts = msgs.filter((m) => m.text === "summarise my day");
    expect(prompts).toHaveLength(1);
    expect(prompts[0].role).toBe("user");
    expect(msgs.some((m) => m.role !== "user" && m.text === "summarise my day"))
      .toBe(false);
    // And it really was answered: the follow-up turn got a model reply.
    await waitFor(() => expect(msgs.some((m) => m.text.includes("dentist slot"))).toBe(true));
  });

  it("does not render the prompt as AURA's reply", async () => {
    const calls = stub();
    renderStore();
    fireEvent.click(screen.getByText("run"));
    await waitFor(() => expect(chats(calls).length).toBe(2));
    // The placeholder bubble for the command turn shows what was invoked.
    const assistant = msgs.filter((m) => m.role === "assistant" || m.role === "error");
    expect(assistant.map((m) => m.text)).toContain("→ /brief");
    expect(assistant.every((m) => m.text !== "summarise my day")).toBe(true);
  });

  it("navigates and sends when the command also names a view", async () => {
    const calls = stub({ ...SLASH_RESULT, view: "analytics",
                         result: { prompt: "summarise my day", view: "analytics" } });
    renderStore();
    fireEvent.click(screen.getByText("run"));
    await waitFor(() => expect(chats(calls).length).toBe(2));
    // Ordering: navigate-then-send. The destination is set before the follow-up
    // turn starts, so the turn lands in the view the command asked for.
    expect(view).toBe("analytics");
    expect(chats(calls)[1].body!.message).toBe("summarise my day");
  });

  it("a built-in command still renders its output and is not re-sent", async () => {
    const calls = stub({ handled: true, ok: true, command: "/task",
                         result: { task: { id: 7, title: "Ship it", status: "inbox" } },
                         text: '{"id": 7, "title": "Ship it"}', view: null });
    renderStore();
    fireEvent.click(screen.getByText("runTask"));
    // A deterministic command renders its own output — there is no prompt to send.
    await waitFor(() => expect(msgs.some(
      (m) => m.role === "assistant" && m.text.includes('"id": 7'))).toBe(true));
    // Exactly one turn: a deterministic command is never fed back to the model.
    expect(chats(calls)).toHaveLength(1);
    expect(chats(calls)[0].body!.message).toBe("/task Ship it");
  });

  it("an unrenderable view degrades to visible text, not a blank app", async () => {
    // App.tsx is a `view === x` chain with no default branch, so `setView` on a
    // name it cannot render yields an empty main pane and no error. Rows saved
    // before the server-side guard are the only way to get here.
    const calls = stub({ handled: true, ok: true, command: "/old",
                         result: { task: { id: 3 }, view: "analytic" },
                         text: "could not jump", view: "analytic" });
    renderStore();
    fireEvent.click(screen.getByText("runTask"));
    await waitFor(() => expect(chats(calls).length).toBe(1));
    expect(view).toBe("home");  // did not navigate anywhere unrenderable
    // …and the user sees why, instead of an empty pane.
    expect(msgs.some((m) => m.text === "could not jump")).toBe(true);
  });

  it("a custom-command chain is bounded, so /a → /b → /a cannot loop", async () => {
    // Every turn is a command whose prompt is another command name. Without a
    // bound this is an unbounded request loop against the user's own backend.
    const calls = stub(SLASH_RESULT, true);
    renderStore();
    fireEvent.click(screen.getByText("run"));
    // One user action, at most MAX_COMMAND_CHAIN + 1 turns.
    await waitFor(() => expect(chats(calls).length).toBe(5));
    expect(chats(calls).map((c) => c.body!.message))
      .toEqual(["/brief", "summarise my day", "summarise my day",
                "summarise my day", "summarise my day"]);
  });
});
