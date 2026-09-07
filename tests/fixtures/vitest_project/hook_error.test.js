import { test, beforeEach } from "vitest";

beforeEach(() => {
  throw new Error("boom in beforeEach");
});

test("never actually runs", () => {});
