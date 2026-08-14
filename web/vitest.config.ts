import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

// Logic-only test setup: no jsdom, no component rendering, no UI libraries. The read
// layer's components are thin and their correctness is visible on the page; what is
// NOT visible is the derivation in lib/, which is where the campaign grid's chain
// traversal, cell-state classification and dormancy arithmetic live. Those are pure
// functions over constructed rows, so a plain node environment is all they need.
//
// The alias mirrors tsconfig's `paths` ("@/*" -> "./*") because the modules under test
// import each other that way; without it every `@/lib/db` type import fails to resolve.
export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
  resolve: {
    alias: { "@": resolve(import.meta.dirname, ".") },
  },
});
