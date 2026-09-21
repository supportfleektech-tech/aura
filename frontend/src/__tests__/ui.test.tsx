import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalCard, Btn, ChatThread, CommandPalette, Composer, Empty, Panel, Pill, PlanSteps, Row, Seg, Sidebar, Toasts } from "../ui";
import { useStore } from "../store";

vi.mock("../store", () => ({ useStore: vi.fn() }));
vi.mock("../i18n", () => ({ useLang: () => ({ t: (k: string) => k, lang: "en" }) }));
const { resolveApproval } = vi.hoisted(() => ({ resolveApproval: vi.fn() }));
vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, api: { ...original.api, approvals: { ...original.api.approvals, resolve: resolveApproval } } };
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const base = (over: Record<string, unknown> = {}) => ({ msgs: [], sending: false, speak: vi.fn(), toast: vi.fn(), refresh: vi.fn(), setOrb: vi.fn(), ...over } as unknown as ReturnType<typeof useStore>);

describe("ChatThread", () => {
  it("shows a chat placeholder before the first message", () => {
    vi.mocked(useStore).mockReturnValue(base());
    render(<ChatThread />);
    expect(screen.getByText("Start a conversation")).toBeInTheDocument();
    expect(screen.getByText("Type a message below to chat with AURA.")).toBeInTheDocument();
  });
});

describe("Composer focus request", () => {
  it("focuses the textarea when composerFocus increments", async () => {
    vi.mocked(useStore).mockReturnValue(base({
      send: vi.fn(), listening: false, toggleListen: vi.fn(), transcript: "", newChat: vi.fn(), composerFocus: 1,
    }));
    render(<Composer />);
    const ta = screen.getByLabelText("Message AURA");
    expect(document.activeElement).toBe(ta);
  });
});

describe("Toasts accessibility", () => {
  it("announces toasts to assistive technology", () => {
    vi.mocked(useStore).mockReturnValue(base({
      toasts: [{ id: "1", text: "Saved to memory", kind: "success" }],
    } as unknown as Record<string, unknown>));
    render(<Toasts />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Saved to memory")).toBeInTheDocument();
  });
});

describe("ApprovalCard honest outcomes", () => {
  it("reports failed delivery instead of claiming everything was sent", async () => {
    const approval = { id: 7, title: "Follow up", risk: "R2", drafts: [{ to: "jane@example.com", subject: "Hi", body: "Following up" }] };
    resolveApproval.mockResolvedValue({ decision: "approved", sent: [], errors: ["SMTP auth failed"] });
    vi.mocked(useStore).mockReturnValue(base());
    render(<ApprovalCard approval={approval} />);
    await userEvent.click(screen.getByText("Approve and Send"));
    expect(await screen.findByText("1 of 1 message(s) failed to send")).toBeInTheDocument();
  });
});

describe("primitives", () => {
  it("renders Panel with title and children", () => {
    render(<Panel icon="zap" title="Hello" sub="sub"><span>body</span></Panel>);
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });
  it("renders Pill color class", () => {
    render(<Pill c="green">ok</Pill>);
    expect(screen.getByText("ok")).toHaveClass("pill");
  });
  it("renders Empty and Row", () => {
    render(<Empty title="Nothing here" sub="go make some" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    render(<Row icon="task" title="T1" sub="detail" />);
    expect(screen.getByText("T1")).toBeInTheDocument();
  });
  it("Btn fires onClick", async () => {
    const fn = vi.fn();
    render(<Btn small onClick={fn}>Go</Btn>);
    await userEvent.click(screen.getByText("Go"));
    expect(fn).toHaveBeenCalledTimes(1);
  });
  it("Btn respects disabled", async () => {
    const fn = vi.fn();
    render(<Btn small disabled onClick={fn}>No</Btn>);
    await userEvent.click(screen.getByText("No"));
    expect(fn).not.toHaveBeenCalled();
  });
});

describe("shell accessibility", () => {
  it("names collapsed navigation and exposes the current page", async () => {
    localStorage.setItem("aura_nav", "c");
    const setView = vi.fn();
    vi.mocked(useStore).mockReturnValue(base({ view: "home", setView, pendingApprovals: 0 }));
    render(<Sidebar />);
    expect(screen.getByRole("button", { name: "nav.home" })).toHaveAttribute("aria-current", "page");
    screen.getByRole("button", { name: "AURA OS home" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(setView).toHaveBeenCalledWith("home");
    localStorage.removeItem("aura_nav");
  });

  it("exposes segmented selection without changing its callback contract", () => {
    render(<Seg options={[{ v: "one", label: "One" }, { v: "two", label: "Two" }]} value="one" onPick={vi.fn()} />);
    expect(screen.getByRole("button", { name: "One" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Two" })).toHaveAttribute("aria-pressed", "false");
  });

  it("contains palette focus, closes from action buttons, and restores focus", async () => {
    const setPalette = vi.fn();
    vi.spyOn((await import("../api")).api.sessions, "list").mockResolvedValue({ sessions: [] });
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();
    vi.mocked(useStore).mockReturnValue(base({ palette: true, setPalette }));
    const { unmount } = render(<CommandPalette />);
    const input = screen.getByRole("textbox", { name: "pal.placeholder" });
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    expect(input).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(screen.getByRole("button", { name: "pal.call" })).toHaveFocus();
    await userEvent.tab();
    expect(input).toHaveFocus();
    await userEvent.tab();
    await userEvent.keyboard("{Escape}");
    expect(setPalette).toHaveBeenCalledWith(false);
    unmount();
    expect(trigger).toHaveFocus();
    trigger.remove();
    vi.restoreAllMocks();
  });
});

describe("PlanSteps", () => {
  it("renders nothing when empty", () => {
    const { container } = render(<PlanSteps steps={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
  it("renders step labels and statuses", () => {
    render(<PlanSteps steps={[
      { id: "s1", label: "Fetch tasks", status: "done" },
      { id: "s2", label: "Draft brief", status: "running" },
    ]} />);
    expect(screen.getByText("AURA PLAN")).toBeInTheDocument();
    expect(screen.getByText("Fetch tasks")).toBeInTheDocument();
    expect(screen.getByText("Draft brief")).toBeInTheDocument();
  });
});
