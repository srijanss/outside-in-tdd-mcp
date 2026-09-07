import { test } from "vitest";
import "this-module-does-not-exist-at-all-xyz";

test("never runs", () => {});
