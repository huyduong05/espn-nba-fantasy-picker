import { describe, expect, it } from "vitest";

import {
  PHASE10_SCENARIOS,
  boardForOverallPick,
} from "../src/benchmark-fixtures.js";
import type { PlayerIndex } from "../src/contracts.js";
import { deriveDraftState } from "../src/manual-board.js";

const index: PlayerIndex = {
  schema_version: "1.0.0",
  index_version: "phase_9_player_index_v1",
  generated_at: "2026-10-17T12:00:00Z",
  input_fingerprint: "phase10-fixture",
  players: Array.from({ length: 160 }, (_, value) => ({
    canonical_player_id: `plr_${String(value + 1).padStart(32, "0")}`,
    display_name: `Player ${value + 1}`,
    aliases: [],
    positions: ["PG"],
  })),
};

describe("Phase 10 benchmark fixtures", () => {
  it.each(PHASE10_SCENARIOS)(
    "derives a valid $name-round board",
    (scenario) => {
      const result = deriveDraftState(
        index,
        boardForOverallPick(index, scenario.overallPick),
      );

      expect(result.ok).toBe(true);
      if (result.ok) {
        expect(result.overallPick).toBe(scenario.overallPick);
        expect(result.draftState.remaining_players.length).toBe(
          161 - scenario.overallPick,
        );
      }
    },
  );
});
