import { afterEach, describe, expect, it } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { SlashPalette } from "../CommandPalette";
import { SlashCommand } from "../slash";

// No `globals: true` in vitest.config.ts, so RTL's auto-cleanup never registers.
afterEach(cleanup);

const CAT: SlashCommand[] = [
  { name: "/task", category: "Tasks", summary: "Create a task", example: "/task Review the PR", arg: "text" },
  { name: "/tasks", category: "Tasks", summary: "List inbox tasks", example: "/tasks", arg: "" },
  { name: "/remember", category: "Memory", summary: "Store a fact", example: "/remember x", arg: "text" },
];

describe("SlashPalette", () => {
  it("filters as you type and shows the arg hint — FR-CMD-003", () => {
    render(<SlashPalette catalog={CAT} query="/tas" onClose={() => {}} onPick={() => {}} />);
    expect(screen.getByText("/task")).toBeTruthy();
    expect(screen.getByText("/tasks")).toBeTruthy();
    expect(screen.queryByText("/remember")).toBeNull();
    expect(screen.getByText("text")).toBeTruthy();
  });

  it("arrow keys move the selection and Enter picks it — FR-CMD-002", () => {
    const picks: string[] = [];
    render(<SlashPalette catalog={CAT} query="" onClose={() => {}} onPick={(c) => picks.push(c.name)} />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(picks).toEqual(["/tasks"]);
  });

  it("ArrowUp does not wrap past the first item", () => {
    const picks: string[] = [];
    render(<SlashPalette catalog={CAT} query="" onClose={() => {}} onPick={(c) => picks.push(c.name)} />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(picks).toEqual(["/task"]);
  });

  it("typing narrows the selection back to the first match", () => {
    const picks: string[] = [];
    render(<SlashPalette catalog={CAT} query="" onClose={() => {}} onPick={(c) => picks.push(c.name)} />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.change(input, { target: { value: "/remem" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(picks).toEqual(["/remember"]);
  });

  it("Escape closes", () => {
    let closed = 0;
    render(<SlashPalette catalog={CAT} query="" onClose={() => { closed += 1; }} onPick={() => {}} />);
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(closed).toBe(1);
  });

  it("says so when nothing matches", () => {
    render(<SlashPalette catalog={CAT} query="/zzzz" onClose={() => {}} onPick={() => {}} />);
    expect(screen.getByText(/No command matches/)).toBeTruthy();
  });

  it("Enter picks nothing when the list is empty", () => {
    const picks: string[] = [];
    render(<SlashPalette catalog={CAT} query="/zzzz" onClose={() => {}} onPick={(c) => picks.push(c.name)} />);
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
    expect(picks).toEqual([]);
  });

  it("clicking an item selects it and reports the selection", () => {
    const picks: string[] = [];
    render(<SlashPalette catalog={CAT} query="" onClose={() => {}} onPick={(c) => picks.push(c.name)} />);
    fireEvent.click(screen.getByText("/remember"));
    expect(picks).toEqual(["/remember"]);
  });

  it("hovering moves the selection — the aria-selected row follows the pointer", () => {
    render(<SlashPalette catalog={CAT} query="" onClose={() => {}} onPick={() => {}} />);
    const items = screen.getAllByRole("option");
    expect(items[0].getAttribute("aria-selected")).toBe("true");
    fireEvent.mouseEnter(items[2]);
    expect(items[2].getAttribute("aria-selected")).toBe("true");
    expect(items[0].getAttribute("aria-selected")).toBe("false");
  });

  it("a shrinking list clamps the selection instead of dangling", () => {
    const picks: string[] = [];
    render(<SlashPalette catalog={CAT} query="" onClose={() => {}} onPick={(c) => picks.push(c.name)} />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" }); // sel = 2 (/remember)
    fireEvent.change(input, { target: { value: "/task" } }); // one exact match
    fireEvent.keyDown(input, { key: "Enter" });
    expect(picks).toEqual(["/task"]);
  });
});