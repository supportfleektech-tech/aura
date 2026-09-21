import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import Orb from "../Orb";

const { loadThree } = vi.hoisted(() => ({ loadThree: vi.fn() }));
vi.mock("three", () => { loadThree(); return { WebGLRenderer: class { constructor() { throw new Error("3D unavailable"); } } }; });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("keeps reduced-motion status accessible without loading Three", () => {
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  const { rerender } = render(<Orb state="idle" size={180} />);
  expect(screen.getByRole("img", { name: "AURA state: idle" })).toBeInTheDocument();
  rerender(<Orb state="offline" size={180} />);
  expect(screen.getByRole("img", { name: "AURA state: offline" })).toBeInTheDocument();
  expect(loadThree).not.toHaveBeenCalled();
});

it("retains the accessible 2D fallback when the 3D chunk fails", async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  await act(async () => { render(<Orb state="warning" />); });
  expect(screen.getByRole("img", { name: "AURA state: warning" }).querySelector(".orb2d")).toBeInTheDocument();
});
