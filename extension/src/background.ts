import type {
  ExtensionRequestMessage,
  MetadataResponseMessage,
  RecommendationRequestMessage,
  RecommendationResponseMessage,
} from "./contracts.js";

const API_ROOT = "http://127.0.0.1:8765/api/v1";
const REQUEST_TIMEOUT_MS = 5_000;

if (typeof chrome !== "undefined") {
  chrome.runtime.onMessage.addListener(
    (
      message: ExtensionRequestMessage,
      _sender,
      sendResponse: (
        response: RecommendationResponseMessage | MetadataResponseMessage,
      ) => void,
    ) => {
      if (message.type !== "recommend" && message.type !== "metadata") {
        return false;
      }
      const request =
        message.type === "recommend"
          ? requestRecommendations(message)
          : requestMetadata();
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
