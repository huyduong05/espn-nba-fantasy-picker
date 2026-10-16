import { serverMessage, validateRecommendationResponse } from "./api.js";
import type {
  ManualBoardState,
  PlayerIndex,
  RecommendationResponse,
} from "./contracts.js";
import { deriveDraftState } from "./manual-board.js";
import { mountPanel } from "./panel.js";
import { loadBoard, saveBoard } from "./storage.js";

void bootstrap();

async function bootstrap(): Promise<void> {
  const index = await loadIndex();
  mountPanel(document, index, {
    loadBoard: () => loadBoard(chrome.storage.session),
    saveBoard: (board) => saveBoard(chrome.storage.session, board),
    suggest: (board) => suggest(index, board),
  });
}

async function loadIndex(): Promise<PlayerIndex> {
  const response = await fetch(chrome.runtime.getURL("player-index.json"));
  const value: unknown = await response.json();
  if (!response.ok || !isPlayerIndex(value)) {
    throw new Error(
      "The bundled player index is missing or invalid. Rebuild the extension.",
    );
  }
  return value;
}

async function suggest(
  index: PlayerIndex,
  board: ManualBoardState,
): Promise<RecommendationResponse> {
  const state = deriveDraftState(index, board);
  if (!state.ok) {
    throw new Error(state.message);
  }
  const workerResponse = serverMessage(
    await chrome.runtime.sendMessage({
      type: "recommend",
      draft_state: state.draftState,
    }),
  );
  if (!workerResponse.ok) {
    throw new Error(workerResponse.message);
  }
  const response = validateRecommendationResponse(workerResponse.response);
  if (!response) {
    throw new Error(
      "The local service returned an invalid recommendation response.",
    );
  }
  return response;
}

function isPlayerIndex(value: unknown): value is PlayerIndex {
  return (
    typeof value === "object" &&
    value !== null &&
    "index_version" in value &&
    "players" in value &&
    (value as PlayerIndex).index_version === "phase_9_player_index_v1" &&
    Array.isArray((value as PlayerIndex).players)
  );
}
