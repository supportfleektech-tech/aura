import { describe, expect, it } from "vitest";
import { matchCommands, catalogFrom, SlashCommand } from "../slash";

const CAT: SlashCommand[] = [
  { name: "/task", category: "Tasks", summary: "Create a task", example: "/task Review the PR", arg: "text" },
  { name: "/tasks", category: "Tasks", summary: "List inbox tasks", example: "/tasks", arg: "" },
  { name: "/remember", category: "Memory", summary: "Store a fact", example: "/remember x", arg: "text" },
  { name: "/search", category: "Memory", summary: "Hybrid search", example: "/search x", arg: "text" },
];

describe("matchCommands", () => {
  it("ranks a prefix match first — AC-CMD-001", () => {
    expect(matchCommands(CAT, "/tas")[0].name).toBe("/task");
  });

  it("ranks an exact name first", () => {
    expect(matchCommands(CAT, "/tasks")[0].name).toBe("/tasks");
  });

  it("matches a substring of the name", () => {
    expect(matchCommands(CAT, "/remem")[0].name).toBe("/remember");
  });

  it("matches on summary text", () => {
    expect(matchCommands(CAT, "/Hybrid").map((c) => c.name)).toContain("/search");
  });

  it("returns everything for a bare slash", () => {
    expect(matchCommands(CAT, "/").length).toBe(CAT.length);
  });

  it("returns nothing when there is no match", () => {
    expect(matchCommands(CAT, "/zzzz")).toEqual([]);
  });

  it("works with or without the leading slash", () => {
    expect(matchCommands(CAT, "task")[0].name).toBe("/task");
  });

  it("is stable — equal scores sort by name", () => {
    const r = matchCommands(CAT, "/task");
    expect(r.map((c) => c.name)).toEqual(["/task", "/tasks"]);
  });

  it("is case-insensitive and trims", () => {
    expect(matchCommands(CAT, "  /TASK  ")[0].name).toBe("/task");
  });

  it("ranks a name that starts with the query above one that merely contains it", () => {
    // Discriminating test. A prefix hit must use a higher band than a substring
    // hit; if both fell into one `200 - length` bucket, "/career" (6 chars) would
    // beat "/remember" (8 chars) purely on length and AC-CMD-001's top slot would
    // be the wrong command.
    const C: SlashCommand[] = [
      { name: "/remember", category: "Memory", summary: "Store a fact", example: "", arg: "text" },
      { name: "/career", category: "Navigation", summary: "Open career", example: "", arg: "" },
      { name: "/search", category: "Memory", summary: "Hybrid search", example: "", arg: "text" },
    ];
    expect(matchCommands(C, "/re").map((c) => c.name)).toEqual(["/remember", "/career"]);
  });

  it("an exact name beats a longer name that starts with it", () => {
    const C: SlashCommand[] = [
      { name: "/tasks", category: "Tasks", summary: "List inbox tasks", example: "", arg: "" },
      { name: "/task", category: "Tasks", summary: "Create a task", example: "", arg: "text" },
    ];
    expect(matchCommands(C, "/tasks")[0].name).toBe("/tasks");
  });

  it("ranks a name match above a summary match — AC-CMD-001", () => {
    // "/search" is in the *summary* of /search, but "task" also appears there.
    // A name hit must always outrank a prose hit or the top slot is noise.
    expect(matchCommands(CAT, "/search")[0].name).toBe("/search");
    expect(matchCommands(CAT, "/tas")[0].name).not.toBe("/tasks");
  });

  it("stays under the 20ms fuzzy-search budget for 100 commands", () => {
    const big: SlashCommand[] = Array.from({ length: 100 }, (_, i) => ({
      name: `/cmd${i}`, category: "Tasks", summary: `command number ${i}`, example: "", arg: "",
    }));
    const t0 = performance.now();
    for (let i = 0; i < 50; i += 1) matchCommands(big, `/cmd${i}`);
    expect(performance.now() - t0).toBeLessThan(1000);
  });
});

describe("catalogFrom", () => {
  it("drops the python handler and keeps every rendered field", () => {
    const c = catalogFrom({ commands: [{ name: "/task", category: "Tasks", summary: "s", example: "e", arg: "text", handler: "x" }] });
    expect(c).toEqual([{ name: "/task", category: "Tasks", summary: "s", example: "e", arg: "text" }]);
  });

  it("survives junk input", () => {
    expect(catalogFrom(null)).toEqual([]);
    expect(catalogFrom({})).toEqual([]);
    expect(catalogFrom({ commands: [null, 3, {}] })).toEqual([]);
    expect(catalogFrom({ commands: "nope" })).toEqual([]);
  });

  it("fills missing optional fields with safe defaults", () => {
    expect(catalogFrom({ commands: [{ name: "/x" }] }))
      .toEqual([{ name: "/x", category: "Other", summary: "", example: "", arg: "" }]);
  });
});