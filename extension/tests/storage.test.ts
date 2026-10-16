import { describe, expect, it } from "vitest";

import { emptyBoard, setDraftSlot } from "../src/manual-board.js";
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
    const board = setDraftSlot(emptyBoard(), 5);

    await saveBoard(store, board);
    expect(await loadBoard(store)).toEqual(board);
  });
});
