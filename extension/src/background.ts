import type {
  RecommendationRequestMessage,
  RecommendationResponseMessage,
} from "./contracts.js";

const RECOMMENDATIONS_URL = "http://127.0.0.1:8765/api/v1/recommendations";

chrome.runtime.onMessage.addListener(
  (
    message: RecommendationRequestMessage,
    _sender,
    sendResponse: (response: RecommendationResponseMessage) => void,
  ) => {
    if (message.type !== "recommend") {
      return false;
    }
    void requestRecommendations(message)
      .then(sendResponse)
      .catch(() =>
        sendResponse({
          ok: false,
          code: "SERVICE_UNAVAILABLE",
          message: "The local recommendation service is unavailable.",
        }),
      );
    return true;
  },
);

export async function requestRecommendations(
  message: RecommendationRequestMessage,
): Promise<RecommendationResponseMessage> {
  const response = await fetch(RECOMMENDATIONS_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(message.draft_state),
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
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
