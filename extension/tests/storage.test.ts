import { describe, expect, it } from "vitest";

import { emptyBoard } from "../src/manual-board.js";
import { loadBoard, saveBoard, type SessionStore } from "../src/storage.js";

describe("session board storage", () => {
  it("restores the manual board from session storage", async () => {
    let value: Record<string, unknown> = {};
    const store: SessionStore = {
      get: async () => value,
      set: async (next) => {
        value = next;
      },
    };
    const board = emptyBoard();

    await saveBoard(store, board);
    expect(await loadBoard(store)).toEqual(board);
  });

  it("normalizes legacy boards by dropping the old draft-slot field", async () => {
    const store: SessionStore = {
      get: async () => ({
        fantasy_picker_manual_board: {
          draft_slot: 5,
          roster_ids: ["plr_00000000000000000000000000000001"],
          taken_ids: [],
        },
      }),
      set: async () => undefined,
    };

    await expect(loadBoard(store)).resolves.toEqual({
      roster_ids: ["plr_00000000000000000000000000000001"],
      taken_ids: [],
    });
  });
});
