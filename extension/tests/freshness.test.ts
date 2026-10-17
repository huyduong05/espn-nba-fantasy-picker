import { describe, expect, it } from "vitest";

import { assessFreshness } from "../src/freshness.js";

const now = Date.parse("2026-10-17T12:00:00Z");

function metadata(modifiedAt: string): object {
  return {
    artifacts: [
      { name: "projections", modified_at: modifiedAt },
      { name: "reference", modified_at: modifiedAt },
      { name: "injury_assessments", modified_at: modifiedAt },
      { name: "recommender_config", modified_at: "2000-01-01T00:00:00Z" },
    ],
  };
}

describe("prepared data freshness", () => {
  it("warns when the oldest required artifact is seven days old", () => {
    expect(assessFreshness(metadata("2026-10-10T12:00:00Z"), now)).toEqual({
      status: "stale",
      ageDays: 7,
    });
  });

  it("does not treat the recommender configuration age as data staleness", () => {
    expect(assessFreshness(metadata("2026-10-17T11:59:59Z"), now)).toEqual({
      status: "fresh",
    });
  });

  it("reports unknown freshness for malformed metadata", () => {
    expect(assessFreshness({ artifacts: [] }, now)).toEqual({
      status: "unknown",
      message: "Data freshness could not be determined.",
    });
  });
});
