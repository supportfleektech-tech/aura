import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import * as prefs from "../prefs";

vi.mock("../ui", () => ({
  Panel: ({ children, title }: { children: React.ReactNode; title: string }) => <section aria-label={title}>{children}</section>,
  SetRow: ({ control }: { control: React.ReactNode }) => <div>{control}</div>,
}));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("maps each engine to its own voice preference without changing legacy defaults", () => {
  expect("voicePreferenceKey" in prefs).toBe(true);
  const key = (prefs as unknown as { voicePreferenceKey: (engine: string) => string }).voicePreferenceKey;
  expect(key("kokoro")).toBe("voice_kokoro_id");
  expect(key("piper")).toBe("voice_piper_id");
  expect(key("edge")).toBe("voice_edge_id");
  expect(key("browser")).toBe("voice_browser_name");
});

it("renders accessible personality controls and saves the selected preference", async () => {
  const { PersonalitySettings } = await import("../PersonalitySettings");
  const save = vi.fn().mockResolvedValue(undefined);
  render(<PersonalitySettings draft={{}} save={save} />);
  expect(screen.getByRole("combobox", { name: "Warmth" })).toHaveValue("warm");
  expect(screen.getByRole("combobox", { name: "Humour" })).toHaveValue("off");
  expect(screen.getByRole("combobox", { name: "Style" })).toHaveValue("conversational");
  expect(screen.getByRole("combobox", { name: "Pacing" })).toHaveValue("balanced");
  fireEvent.change(screen.getByRole("combobox", { name: "Humour" }), { target: { value: "light" } });
  await waitFor(() => expect(save).toHaveBeenCalledWith({ ai_humour: "light" }, "Personality saved"));
  expect(screen.getByText(/not feelings or consciousness/)).toBeInTheDocument();
});
