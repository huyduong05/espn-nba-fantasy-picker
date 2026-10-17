import type {
  ExtensionResponseMessage,
  ExtensionRequestMessage,
  MetadataResponseMessage,
  RecommendationRequestMessage,
  RecommendationResponseMessage,
} from "./contracts.js";
import { loadBoard, saveBoard } from "./storage.js";

const API_ROOT = "http://127.0.0.1:8765/api/v1";
const REQUEST_TIMEOUT_MS = 5_000;

if (typeof chrome !== "undefined") {
  chrome.runtime.onMessage.addListener(
    (
      message: ExtensionRequestMessage,
      _sender,
      sendResponse: (response: ExtensionResponseMessage) => void,
    ) => {
      let request: Promise<ExtensionResponseMessage>;
      if (message.type === "recommend") {
        request = requestRecommendations(message);
      } else if (message.type === "metadata") {
        request = requestMetadata();
      } else if (message.type === "load_board") {
        request = loadManualBoard();
      } else {
        request = saveManualBoard(message.board);
      }
      void request.then(sendResponse).catch(() =>
        sendResponse({
          ok: false,
          code: "SERVICE_UNAVAILABLE",
          message: "The local recommendation service is unavailable.",
        }),
      );
      return true;
    },
  );
}

export async function loadManualBoard(): Promise<
  import("./contracts.js").LoadBoardResponseMessage
> {
  try {
    return { ok: true, board: await loadBoard(chrome.storage.session) };
  } catch {
    return {
      ok: false,
      code: "STORAGE_UNAVAILABLE",
      message: "The manual draft board could not be loaded.",
    };
  }
}

export async function saveManualBoard(
  board: import("./contracts.js").ManualBoardState,
): Promise<import("./contracts.js").SaveBoardResponseMessage> {
  try {
    await saveBoard(chrome.storage.session, board);
    return { ok: true };
  } catch {
    return {
      ok: false,
      code: "STORAGE_UNAVAILABLE",
      message: "The manual draft board could not be saved.",
    };
  }
}

export async function requestRecommendations(
  message: RecommendationRequestMessage,
): Promise<RecommendationResponseMessage> {
  return requestApi("/recommendations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(message.draft_state),
  });
}

export async function requestMetadata(): Promise<MetadataResponseMessage> {
  const result = await requestApi("/metadata", { method: "GET" });
  if (result.ok) {
    return { ok: true, metadata: result.response };
  }
  return result;
}

async function requestApi(
  path: string,
  options: RequestInit,
): Promise<RecommendationResponseMessage> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_ROOT}${path}`, {
      ...options,
      signal: controller.signal,
    });
    const payload: unknown = await response.json().catch(() => null);
    if (response.ok) {
      return { ok: true, response: payload };
    }
    if (
      isRecord(payload) &&
      isRecord(payload.error) &&
      typeof payload.error.message === "string"
    ) {
      return {
        ok: false,
        code:
          typeof payload.error.code === "string"
            ? payload.error.code
            : "API_ERROR",
        message: payload.error.message,
      };
    }
    return {
      ok: false,
      code: "API_ERROR",
      message: "The local service rejected the request.",
    };
  } catch (error) {
    if (isAbortError(error)) {
      return {
        ok: false,
        code: "SERVICE_TIMEOUT",
        message: "The local recommendation service took more than 5 seconds.",
      };
    }
    return {
      ok: false,
      code: "SERVICE_UNAVAILABLE",
      message: "The local recommendation service is unavailable.",
    };
  } finally {
    clearTimeout(timeout);
  }
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
