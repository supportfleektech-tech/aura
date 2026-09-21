import { describe, expect, it } from "vitest";
import { ago, md } from "../api";
import { daypart, greetWord } from "../store";

describe("ago", () => {
  it("handles null", () => expect(ago(null)).toBe("—"));
  it("says just now for fresh timestamps", () =>
    expect(ago(new Date().toISOString())).toBe("just now"));
  it("formats minutes/hours/days", () => {
    const m = (n: number) => ago(new Date(Date.now() - n * 60000).toISOString());
    expect(m(5)).toBe("5m ago");
    expect(m(130)).toBe("2h ago");
    expect(m(60 * 25)).toBe("1d ago");
  });
});

describe("md", () => {
  it("renders bold, code, headings", () => {
    expect(md("**hi**")).toContain("<strong>hi</strong>");
    expect(md("`x()`")).toContain("<code>x()</code>");
    expect(md("# Title")).toContain("mdh");
  });
  it("renders lists and quotes", () => {
    expect(md("- a\n- b")).toContain("<ul>");
    expect(md("1. a")).toContain("<ol>");
    expect(md("> q")).toContain("<blockquote>");
  });
  it("escapes HTML", () => {
    expect(md("<script>alert(1)</script>")).not.toContain("<script>");
    expect(md("<b>x</b>")).toContain("&lt;b&gt;");
  });
  it("renders italic and paragraphs", () => {
    expect(md("*soft*")).toContain("<em>soft</em>");
    expect(md("plain")).toContain("<p>plain</p>");
  });
});

describe("daypart/greetWord", () => {
  it("returns a Nairobi daypart", () =>
    expect(["morning", "afternoon", "evening"]).toContain(daypart()));
  it("greets from the right list", () =>
    expect(["Good morning", "Top of the morning", "Good afternoon", "Good evening"]).toContain(greetWord()));
});
