import { describe, expect, it } from "vitest";

import type { PlayerIndex, PlayerIndexPlayer } from "../src/contracts.js";
import {
  addPlayer,
  deriveDraftState,
  emptyBoard,
  searchPlayers,
} from "../src/manual-board.js";

const index: PlayerIndex = {
  schema_version: "1.0.0",
  index_version: "phase_9_player_index_v1",
  generated_at: "2026-10-17T12:00:00Z",
  input_fingerprint: "phase9-fixture",
  players: [
    player(1, "José Player", ["Jose Player"]),
    player(2, "Player One"),
    player(3, "Player Two"),
    player(4, "Player Three"),
    player(5, "Player Four"),
    player(6, "Player Five"),
    player(7, "Player Six"),
    player(8, "Chris Paul", ["CP3"]),
    player(9, "Paul George"),
  ],
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

  it("ranks exact, prefix, alias, and partial name matches in prepared order", () => {
    expect(
      searchPlayers(index, "paul").map((player) => player.display_name),
    ).toEqual(["Paul George", "Chris Paul"]);
    expect(
      searchPlayers(index, "cp3").map((player) => player.display_name),
    ).toEqual(["Chris Paul"]);
    expect(searchPlayers(index, "player").slice(0, 3)).toEqual(
      index.players.slice(1, 4),
    );
  });

  it("derives a recommendation request without a draft slot", () => {
    const result = deriveDraftState(index, emptyBoard());

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.overallPick).toBe(1);
      expect(result.draftState.round).toBe(1);
      expect(result.draftState.remaining_players).toHaveLength(9);
      expect(result.draftState).not.toHaveProperty("draft_slot");
      expect(result.draftState).not.toHaveProperty("direction");
    }
  });

  it("allows a board update and recommendation request at any pick", () => {
    const board = addPlayer(
      emptyBoard(),
      index.players[0]!.canonical_player_id,
      "taken",
      index,
    );
    const result = deriveDraftState(index, board);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.overallPick).toBe(2);
      expect(result.draftState.round).toBe(1);
      expect(result.draftState.user_roster).toEqual([]);
    }
  });
});

function player(
  indexValue: number,
  display_name: string,
  aliases: string[] = [],
): PlayerIndexPlayer {
  return {
    canonical_player_id: `plr_${String(indexValue).padStart(32, "0")}`,
    display_name,
    aliases,
    positions: ["PG"],
  };
}
