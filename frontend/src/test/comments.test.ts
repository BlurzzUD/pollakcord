import { describe, expect, it } from "vitest";

import { findComments } from "../../scripts/check-no-comments.mjs";

describe("source hygiene", () => {
  it("contains no comments in any source, style or markup file", () => {
    expect(findComments()).toEqual([]);
  });
});
