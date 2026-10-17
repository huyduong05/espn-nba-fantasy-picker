import {
  metadataMessage,
  serverMessage,
  validateRecommendationResponse,
} from "./api.js";
import type {
  ManualBoardState,
  PlayerIndex,
  RecommendationResponse,
} from "./contracts.js";
import { assessFreshness, type Freshness } from "./freshness.js";
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
): Promise<{ response: RecommendationResponse; freshness: Freshness }> {
  const state = deriveDraftState(index, board);
  if (!state.ok) {
    throw new Error(state.message);
  }
  const [recommendationValue, metadataValue] = await Promise.all([
    chrome.runtime.sendMessage({
      type: "recommend",
      draft_state: state.draftState,
    }),
    chrome.runtime.sendMessage({ type: "metadata" }),
  ]);
  const workerResponse = serverMessage(recommendationValue);
  if (!workerResponse.ok) {
    throw new Error(
      recoveryMessage(workerResponse.code, workerResponse.message),
    );
  }
  const response = validateRecommendationResponse(workerResponse.response);
  if (!response) {
    throw new Error(
      "The local service returned an invalid recommendation response.",
    );
  }
  const metadata = metadataMessage(metadataValue);
  const freshness =
    metadata.ok === true
      ? assessFreshness(metadata.metadata)
      : assessFreshness(null);
  return { response, freshness };
}

function recoveryMessage(code: string, message: string): string {
  if (code === "SERVICE_TIMEOUT") {
    return `${message} Verify the local service is running, then retry.`;
  }
  if (code === "SERVICE_UNAVAILABLE") {
    return `${message} Start fantasy-picker serve, then retry.`;
  }
  return message;
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
