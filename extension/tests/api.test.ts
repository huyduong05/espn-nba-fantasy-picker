import { describe, expect, it } from "vitest";

import { validateRecommendationResponse } from "../src/api.js";

const response = {
  schema_version: "1.0.0",
  generated_at: "2026-10-17T12:00:00Z",
  data_version: "phase9-fixture",
  model_version: "fixture-model",
  latency_ms: 12,
  recommendations: [
    {
      rank: 1,
      canonical_player_id: "plr_00000000000000000000000000000001",
      display_name: "Player",
      score: 8.5,
      strong_categories: ["PTS"],
      category_win_gain: 1,
      injury_penalty_pct: 0,
      positions: ["PG"],
      reason_codes: ["ROSTER_FIT"],
    },
  ],
  warnings: [],
};

describe("recommendation response validation", () => {
  it("accepts the public response shape", () => {
    expect(validateRecommendationResponse(response)).not.toBeNull();
  });

  it("rejects an invalid server response before rendering", () => {
    expect(
      validateRecommendationResponse({
        ...response,
        recommendations: [{ ...response.recommendations[0], score: 11 }],
      }),
    ).toBeNull();
  });
});
