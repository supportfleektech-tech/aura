import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LangProvider, STRINGS, useLang } from "../i18n";
import { greetWord } from "../store";

describe("dictionaries", () => {
  it("en and sw have identical key sets", () => {
    expect(Object.keys(STRINGS.sw).sort()).toEqual(Object.keys(STRINGS.en).sort());
  });
  it("no empty translations", () => {
    for (const [k, v] of Object.entries(STRINGS.sw)) expect(v.trim().length, k).toBeGreaterThan(0);
  });
  it("sw differs from en almost everywhere", () => {
    const same = Object.keys(STRINGS.en).filter((k) => STRINGS.sw[k as keyof typeof STRINGS.en] === STRINGS.en[k as keyof typeof STRINGS.en]);
    expect(same.length).toBeLessThan(8); // proper nouns like "Files"/"Faili" differ; a few shared words ok
  });
});

function Probe() {
  const { lang, setLang, t } = useLang();
  return (
    <div>
      <span>{lang}</span>
      <span>{t("nav.home")}</span>
      <button onClick={() => setLang(lang === "en" ? "sw" : "en")}>toggle</button>
    </div>
  );
}

describe("LangProvider", () => {
  it("switches language and persists", async () => {
    localStorage.removeItem("aura-lang");
    render(<LangProvider><Probe /></LangProvider>);
    expect(screen.getByText("Home")).toBeInTheDocument();
    await userEvent.click(screen.getByText("toggle"));
    expect(screen.getByText("Nyumbani")).toBeInTheDocument();
    expect(localStorage.getItem("aura-lang")).toBe("sw");
    expect(document.documentElement.lang).toBe("sw");
  });
});

describe("greetWord", () => {
  it("greets in Kiswahili when asked", () =>
    expect(["Habari za asubuhi", "Amka salama", "Habari za mchana", "Habari za jioni"]).toContain(greetWord("sw")));
});
