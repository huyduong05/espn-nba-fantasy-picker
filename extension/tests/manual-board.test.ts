import { describe, expect, it } from "vitest";

import type { PlayerIndex } from "../src/contracts.js";
import {
  addPlayer,
  deriveDraftState,
  emptyBoard,
  searchPlayers,
  setDraftSlot,
} from "../src/manual-board.js";

const index: PlayerIndex = {
  schema_version: "1.0.0",
  index_version: "phase_9_player_index_v1",
  generated_at: "2026-10-17T12:00:00Z",
  input_fingerprint: "phase9-fixture",
  players: Array.from({ length: 30 }, (_, value) => ({
    canonical_player_id: `plr_${String(value + 1).padStart(32, "0")}`,
    display_name: value === 0 ? "José Player" : `Player ${value + 1}`,
    aliases: value === 0 ? ["Jose Player"] : [],
    positions: ["PG"],
  })),
};

describe("manual draft board", () => {
  it("requires explicit available players and prevents duplicates", () => {
    const player = index.players[0]!;
    expect(searchPlayers(index, "jose")).toEqual([player]);
    const board = addPlayer(
      emptyBoard(),
      player.canonical_player_id,
      "roster",
      index,
    );

    expect(() =>
      addPlayer(board, player.canonical_player_id, "taken", index),
    ).toThrow("already");
    expect(() => addPlayer(board, "plr_missing", "taken", index)).toThrow(
      "unavailable",
    );
  });

  it("derives a valid opening-pick request from the selected draft slot", () => {
    const result = deriveDraftState(index, setDraftSlot(emptyBoard(), 1));

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.overallPick).toBe(1);
      expect(result.draftState.round).toBe(1);
      expect(result.draftState.direction).toBe("FORWARD");
      expect(result.draftState.remaining_players).toHaveLength(30);
    }
  });

  it("blocks a board when it is not the user's pick", () => {
    const board = addPlayer(
      emptyBoard(),
      index.players[0]!.canonical_player_id,
      "taken",
      index,
    );
    const result = deriveDraftState(index, setDraftSlot(board, 1));

    expect(result).toEqual({
      ok: false,
      message: "The manual board does not place you at the current pick yet.",
    });
  });

  it("derives the reverse direction on a later round", () => {
    let board = emptyBoard();
    for (const player of index.players.slice(0, 23)) {
      board = addPlayer(board, player.canonical_player_id, "taken", index);
    }
    const result = deriveDraftState(index, setDraftSlot(board, 1));

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.overallPick).toBe(24);
      expect(result.draftState.round).toBe(2);
      expect(result.draftState.direction).toBe("REVERSE");
    }
  });
});
