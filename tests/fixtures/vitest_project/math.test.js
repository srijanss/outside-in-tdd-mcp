import { test, expect } from "vitest";
import { add } from "./math.js";

test("add imported from math.js", () => {
  expect(add(1, 2)).toBe(3);
});
