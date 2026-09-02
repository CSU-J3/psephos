import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

// Logic-only test setup: no jsdom and no UI libraries. The read layer's components are
// thin and their correctness is visible on the page; what is NOT visible is the
// derivation in lib/, which is where the campaign grid's chain traversal, cell-state
// classification and dormancy arithmetic live. Those are pure functions over
// constructed rows, so a plain node environment is all they need.
//
// ONE COMPONENT IS INCLUDED, AND THE EXCEPTION IS THE ORIGINAL RULE APPLIED RATHER THAN
// RELAXED. "Visible on the page" is a claim about what a render actually exercises, and
// StateMatrix's seventh column falsifies it: that column draws only when a bill carries
// a stage code the ramp does not know, and live data has never held one -- 484 rows, all
// of them 1-6. So the branch is dead code until the day something upstream changes, at
// which point it executes for the first time in production with nobody watching. Testing
// it is not a step toward component testing in general; it is the only branch here that
// no render can reach.
//
// It still needs no jsdom: renderToStaticMarkup ships in react-dom, already a dependency,
// and markup is all an assertion about which columns exist requires. Keep it that way --
// if a component test ever wants a DOM, it wants something this file is right to refuse.
//
// The alias mirrors tsconfig's `paths` ("@/*" -> "./*") because the modules under test
// import each other that way; without it every `@/lib/db` type import fails to resolve.
export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts", "components/**/*.test.ts"],
  },
  // VITEST'S TRANSFORM ONLY, and it must be set here rather than in tsconfig. tsconfig
  // says `jsx: "preserve"`, which is correct and must stay: it hands raw JSX to Next's
  // own compiler. But esbuild reads that as the CLASSIC runtime and emits
  // React.createElement into a module that never imports React, so a rendered component
  // dies with "React is not defined" -- at render, not at type-check, which is why tsc
  // stays clean either way. Overriding it here leaves the build untouched.
  esbuild: { jsx: "automatic" },
  resolve: {
    alias: { "@": resolve(import.meta.dirname, ".") },
  },
});
