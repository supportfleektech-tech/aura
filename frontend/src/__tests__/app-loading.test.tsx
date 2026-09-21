import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import App from "../App";

const state = vi.hoisted(() => ({ view: "home", call: false }));
const deferred = vi.hoisted(() => ({ loaded: vi.fn() }));
vi.mock("../store", () => ({ StoreProvider: ({ children }: { children: ReactNode }) => children, useStore: () => state }));
vi.mock("../i18n", () => ({ LangProvider: ({ children }: { children: ReactNode }) => children }));
vi.mock("../home", () => ({ HomeView: () => <p>Home fixture</p>, RightRail: () => <p>Rail fixture</p> }));
vi.mock("../Onboarding", () => ({ OnboardingGate: () => null }));
vi.mock("../views1", () => ({ CareerView: () => null, ClientsView: () => null, PersonalView: () => null }));
vi.mock("../views2", () => { deferred.loaded(); return { MemoryView: () => <p>Memory fixture</p>, SettingsView: () => { throw new Error("Chunk unavailable"); } }; });
vi.mock("../views3", () => ({}));
vi.mock("../views4", () => ({}));
vi.mock("../ui", async (original) => {
  const ui = await original<typeof import("../ui")>();
  return { ...ui, Sidebar: () => <button>Navigation fixture</button>, TopBar: () => null, CommandPalette: () => null, Toasts: () => null };
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("loads secondary views only on navigation and contains their failures", async () => {
  const { rerender } = render(<App />);
  expect(screen.getByText("Home fixture")).toBeInTheDocument();
  expect(deferred.loaded).not.toHaveBeenCalled();
  expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute("href", "#main-content");
  state.view = "memory";
  rerender(<App />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading view");
  expect(screen.getByRole("button", { name: "Navigation fixture" })).toBeInTheDocument();
  expect(await screen.findByText("Memory fixture")).toBeInTheDocument();
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  state.view = "settings";
  rerender(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Chunk unavailable");
  expect(screen.getByRole("button", { name: "Reload Aura" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Navigation fixture" })).toBeInTheDocument();
  state.view = "home";
  rerender(<App />);
  expect(screen.getByText("Home fixture")).toBeInTheDocument();
});
