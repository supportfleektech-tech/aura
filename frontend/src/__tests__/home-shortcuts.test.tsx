import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { HomeView } from "../home";
import { useStore } from "../store";
import { api } from "../api";

vi.mock("../Orb", () => ({ default: () => null }));
vi.mock("../store", async (importOriginal) => ({
  ...await importOriginal<typeof import("../store")>(),
  useStore: vi.fn(),
}));
vi.mock("../i18n", () => ({ useLang: () => ({ lang: "en", t: (key: string) => key }) }));

let store: ReturnType<typeof useStore>;

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Unexpected network request"); }));
  vi.spyOn(api.proactive, "list").mockResolvedValue({ opportunities: [] });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  store = {
    me: null, dash: null, online: true, orb: "idle", micLevel: { current: 0 },
    msgs: [], sending: false, listening: false, transcript: "", composerFocus: 0,
    setView: vi.fn(), send: vi.fn(), setCall: vi.fn(), toast: vi.fn(),
    refresh: vi.fn(), newChat: vi.fn(), toggleListen: vi.fn(), speak: vi.fn(),
    requestComposerFocus: vi.fn(() => { store.composerFocus += 1; }),
  } as unknown as ReturnType<typeof useStore>;
  vi.mocked(useStore).mockImplementation(() => store);
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function renderHome() {
  const result = render(<HomeView />);
  const shortcuts = within(result.container.querySelector(".orbstage") as HTMLElement);
  return { ...result, shortcuts };
}

describe("Home shortcuts", () => {
  it("places one chat thread and composer below the greeting and above the dashboard", () => {
    const { container } = renderHome();
    const chat = screen.getByRole("region", { name: "Text chat" });
    expect(within(chat).getByRole("textbox", { name: "Message AURA" })).toBeInTheDocument();
    expect(within(chat).getByText("Start a conversation")).toBeInTheDocument();
    expect(within(chat).getByText("Type a message below to chat with AURA.")).toBeInTheDocument();
    expect(container.querySelectorAll(".thread")).toHaveLength(1);
    expect(container.querySelectorAll(".composer")).toHaveLength(1);
    expect(container.querySelector(".greetrow")!.compareDocumentPosition(chat) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(chat.compareDocumentPosition(container.querySelector(".homegrid")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("requests Text focus through the store and focuses the existing composer", () => {
    const { shortcuts, rerender } = renderHome();
    const textbox = screen.getByRole("textbox", { name: "Message AURA" });
    fireEvent.click(shortcuts.getByRole("button", { name: "Text" }));
    expect(store.requestComposerFocus).toHaveBeenCalledTimes(1);
    rerender(<HomeView />);
    expect(textbox).toHaveFocus();
    expect(store.setView).not.toHaveBeenCalled();
  });

  it.each([
    ["Image", 'input[type="file"][accept="image/*"]'],
    ["File", 'input[type="file"]:not([accept="image/*"])'],
  ])("opens the local %s picker synchronously during the shortcut gesture", (name, selector) => {
    const foreign = render(<div><input type="file" accept="image/*" /><input type="file" /></div>);
    const foreignClicks = Array.from(foreign.container.querySelectorAll("input"), (input) => vi.spyOn(input, "click"));
    const { container, shortcuts } = renderHome();
    const input = container.querySelector(`.composer ${selector}`) as HTMLInputElement;
    const other = Array.from(container.querySelectorAll<HTMLInputElement>('.composer input[type="file"]')).find((item) => item !== input)!;
    const otherClick = vi.spyOn(other, "click");
    const click = vi.spyOn(input, "click").mockImplementation(() => undefined);
    const button = shortcuts.getByRole("button", { name });
    let callsDuringGesture = 0;
    container.addEventListener("click", () => { callsDuringGesture = click.mock.calls.length; });
    fireEvent.click(button);
    expect(callsDuringGesture).toBe(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(otherClick).not.toHaveBeenCalled();
    foreignClicks.forEach((spy) => expect(spy).not.toHaveBeenCalled());
    expect(store.setView).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { files: [new File(["content"], "attachment.txt")] } });
    expect(container.querySelector(".composer .attchips")).toHaveTextContent("attachment.txt");
  });

  it("opens the existing files view for Camera/screen", () => {
    const { shortcuts } = renderHome();
    fireEvent.click(shortcuts.getByRole("button", { name: "Camera/screen" }));
    expect(store.setView).toHaveBeenCalledWith("files");
  });

  it.each([["Voice", "voice"], ["More", "settings"]])("preserves the %s shortcut", (name, view) => {
    const { shortcuts } = renderHome();
    fireEvent.click(shortcuts.getByRole("button", { name }));
    expect(store.setView).toHaveBeenCalledWith(view);
  });
});
