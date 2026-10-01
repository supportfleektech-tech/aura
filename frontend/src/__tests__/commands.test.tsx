/* Settings → Commands cheat sheet + custom-command CRUD (AC-CMD-003, FR-CMD-004). */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { useStore, StoreProvider, VIEWS } from "../store";
import { CommandsView } from "../views2/commands";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const FULL_CATALOG = { commands: [
  { name: "/task", category: "Tasks", summary: "Create a task", example: "/task x", arg: "text" },
  { name: "/tasks", category: "Tasks", summary: "List inbox tasks", example: "/tasks", arg: "" },
  { name: "/health", category: "System", summary: "Health plus database size", example: "/health", arg: "" },
  { name: "/brief", category: "Custom", summary: "summarise my day", example: "/brief", arg: "text" },
]};

type Call = { url: string; method: string; body: unknown };

/** Stub the API surface and record every request the view makes. */
function stubApi(opts: { catalog?: unknown; customStatus?: number } = {}) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.includes("/api/slash/custom")) {
      const status = opts.customStatus ?? 200;
      return { ok: status < 400, status, json: async () => ({ ok: status < 400 }),
               text: async () => "{\"detail\":\"/task is a built-in command\"}" } as unknown as Response;
    }
    return { ok: true, status: 200, json: async () => opts.catalog ?? FULL_CATALOG,
             text: async () => "" } as unknown as Response;
  }));
  return calls;
}

let seen: unknown[] = [];
function ToastSpy() {
  seen = useStore().toasts;
  return null;
}

function renderView() {
  return render(
    <LangProvider><StoreProvider><ToastSpy /><CommandsView /></StoreProvider></LangProvider>,
  );
}

describe("CommandsView", () => {
  it("lists every command with its category, summary and example — AC-CMD-003", async () => {
    stubApi();
    renderView();
    await waitFor(() => expect(screen.getByText("/health")).toBeTruthy());
    expect(screen.getByText("Tasks")).toBeTruthy();
    expect(screen.getByText("System")).toBeTruthy();
    expect(screen.getByText("Custom")).toBeTruthy();
    expect(screen.getByText(/Health plus database size — e\.g\. \/health/)).toBeTruthy();
    expect(screen.getByText("4 commands")).toBeTruthy();
  });

  it("the search box narrows the list — FR-CMD-005", async () => {
    stubApi();
    renderView();
    await waitFor(() => expect(screen.getByText("/health")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Search commands"), { target: { value: "heal" } });
    expect(screen.queryByText("/task")).toBeNull();
    expect(screen.getByText("/health")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search commands"), { target: { value: "zzzz" } });
    expect(screen.getByText("No command matches")).toBeTruthy();
  });

  it("renders a Delete button for a custom command only", async () => {
    stubApi();
    renderView();
    await waitFor(() => expect(screen.getByText("/brief")).toBeTruthy());
    expect(screen.getAllByText("Delete")).toHaveLength(1);
    expect(screen.queryAllByText("no arg")).toHaveLength(2);
  });

  it("clicking Delete calls DELETE /api/slash/custom/<name> and reloads — FR-CMD-004", async () => {
    const calls = stubApi();
    renderView();
    await waitFor(() => expect(screen.getByText("/brief")).toBeTruthy());
    fireEvent.click(screen.getByText("Delete"));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    const del = calls.find((c) => c.method === "DELETE")!;
    expect(del.url).toContain("/api/slash/custom/%2Fbrief");
    // reload(): the catalog is re-fetched after the delete.
    await waitFor(() => expect(calls.filter((c) => c.method === "GET").length).toBeGreaterThanOrEqual(2));
  });

  it("saves a custom command with its prompt and target view — FR-CMD-004", async () => {
    const calls = stubApi();
    renderView();
    await waitFor(() => expect(screen.getByText("/health")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Command name"), { target: { value: "/daily" } });
    fireEvent.change(screen.getByLabelText("Command prompt"), { target: { value: "plan my day" } });
    fireEvent.change(screen.getByLabelText("Jump to view"), { target: { value: "analytics" } });
    fireEvent.click(screen.getByText("Save command"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toContain("/api/slash/custom");
    expect(post.body).toEqual({ name: "/daily", prompt: "plan my day", view: "analytics" });
    await waitFor(() => expect(seen.some((t) => (t as { text: string }).text.includes("saved"))).toBe(true));
  });

  it("offers only real views as a jump target — FR-CMD-004", () => {
    stubApi();
    renderView();
    const input = screen.getByLabelText("Jump to view") as HTMLInputElement;
    const offered = Array.from(
      (document.getElementById("slash-view-targets") as HTMLDataListElement).options)
      .map((o) => o.value);
    // Derived from `store.VIEWS`, the same array the `View` type comes from, so
    // it cannot go stale. The backend rejects anything else with a 400; this
    // makes the typo impossible rather than merely reported.
    expect(offered).toEqual([...VIEWS]);
    expect(offered).toContain("analytics");
    expect(input.getAttribute("list")).toBe("slash-view-targets");
  });

it("a rejected name surfaces the server error instead of pretending it saved", async () => {
    stubApi({ customStatus: 400 });
    renderView();
    await waitFor(() => expect(screen.getByText("/health")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Command name"), { target: { value: "/task" } });
    fireEvent.change(screen.getByLabelText("Command prompt"), { target: { value: "x" } });
    fireEvent.click(screen.getByText("Save command"));
    await waitFor(() => expect(seen.some((t) => (t as { text: string }).text.includes("built-in"))).toBe(true));
    // Not a success: the typed prompt is still there and nothing was cleared.
    expect((screen.getByLabelText("Command prompt") as HTMLTextAreaElement).value).toBe("x");
  });

  it("survives a failed catalog fetch with an empty list", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    renderView();
    await waitFor(() => expect(screen.getByText("No command matches")).toBeTruthy());
    expect(screen.getByText("0 commands")).toBeTruthy();
  });
});