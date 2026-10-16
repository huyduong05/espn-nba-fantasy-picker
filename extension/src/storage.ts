import type { ManualBoardState } from "./contracts.js";
import { emptyBoard } from "./manual-board.js";

const STORAGE_KEY = "fantasy_picker_manual_board";

export interface SessionStore {
  get: (key: string) => Promise<Record<string, unknown>>;
  set: (value: Record<string, ManualBoardState>) => Promise<void>;
}

export async function loadBoard(
  store: SessionStore,
): Promise<ManualBoardState> {
  const value: unknown = (await store.get(STORAGE_KEY))[STORAGE_KEY];
  return isBoard(value) ? value : emptyBoard();
}

export async function saveBoard(
  store: SessionStore,
  board: ManualBoardState,
): Promise<void> {
  await store.set({ [STORAGE_KEY]: board });
}

function isBoard(value: unknown): value is ManualBoardState {
  return (
    typeof value === "object" &&
    value !== null &&
    "draft_slot" in value &&
    "roster_ids" in value &&
    "taken_ids" in value &&
    Array.isArray((value as ManualBoardState).roster_ids) &&
    Array.isArray((value as ManualBoardState).taken_ids)
  );
}
