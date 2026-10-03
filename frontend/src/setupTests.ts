import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// findBy* queries wait on testing-library's asyncUtilTimeout, whose own default
// is 1000ms. It is NOT vitest's testTimeout: setting `asyncUtilTimeout` in
// vitest.config.ts is silently ignored (verified — the effective value stayed
// 1000), so it has to be configured here.
//
// The onboarding walk chains seven findByText steps, so on a loaded CI runner one
// slow mount exceeded 1s and failed with "Unable to find an element with the
// text: Choose your domains" even though the component rendered fine. Same
// reasoning as the 20s testTimeout in vitest.config.ts: give slow renders room
// rather than loosening the assertion.
configure({ asyncUtilTimeout: 10000 });