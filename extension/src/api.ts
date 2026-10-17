import {
  SCHEMA_VERSION,
  type RecommendationResponse,
  type RecommendationResponseMessage,
  type MetadataResponseMessage,
} from "./contracts.js";

const CATEGORIES = new Set([
  "PTS",
  "REB",
  "AST",
  "STL",
  "BLK",
  "3PM",
  "FG%",
  "FT%",
  "TO",
]);
const POSITIONS = new Set(["PG", "SG", "SF", "PF", "C"]);

export function validateRecommendationResponse(
  value: unknown,
): RecommendationResponse | null {
  if (
    !isRecord(value) ||
    value.schema_version !== SCHEMA_VERSION ||
    !Array.isArray(value.recommendations)
  ) {
    return null;
  }
  if (
    typeof value.generated_at !== "string" ||
    typeof value.data_version !== "string" ||
    typeof value.model_version !== "string" ||
    typeof value.latency_ms !== "number" ||
    !Array.isArray(value.warnings) ||
    value.recommendations.length > 5
  ) {
    return null;
  }
  if (
    !value.recommendations.every(isRecommendation) ||
    !value.warnings.every(isString)
  ) {
    return null;
  }
  return value as unknown as RecommendationResponse;
}

export function serverMessage(value: unknown): RecommendationResponseMessage {
  if (!isRecord(value) || typeof value.ok !== "boolean") {
    return {
      ok: false,
      code: "INVALID_EXTENSION_RESPONSE",
      message: "The extension worker returned an invalid response.",
    };
  }
  if (value.ok === true && "response" in value) {
    return { ok: true, response: value.response };
  }
  if (
    value.ok === false &&
    typeof value.code === "string" &&
    typeof value.message === "string"
  ) {
    return { ok: false, code: value.code, message: value.message };
  }
  return {
    ok: false,
    code: "INVALID_EXTENSION_RESPONSE",
    message: "The extension worker returned an invalid response.",
  };
}

export function metadataMessage(value: unknown): MetadataResponseMessage {
  if (!isRecord(value) || typeof value.ok !== "boolean") {
    return {
      ok: false,
      code: "INVALID_EXTENSION_RESPONSE",
      message: "The extension worker returned invalid metadata.",
    };
  }
  if (value.ok === true && "metadata" in value) {
    return { ok: true, metadata: value.metadata };
  }
  if (
    value.ok === false &&
    typeof value.code === "string" &&
    typeof value.message === "string"
  ) {
    return { ok: false, code: value.code, message: value.message };
  }
  return {
    ok: false,
    code: "INVALID_EXTENSION_RESPONSE",
    message: "The extension worker returned invalid metadata.",
  };
}

function isRecommendation(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.rank === "number" &&
    typeof value.canonical_player_id === "string" &&
    typeof value.display_name === "string" &&
    typeof value.score === "number" &&
    value.rank >= 1 &&
    value.rank <= 5 &&
    value.score >= 0 &&
    value.score <= 10 &&
    Array.isArray(value.strong_categories) &&
    value.strong_categories.every(
      (category) => typeof category === "string" && CATEGORIES.has(category),
    ) &&
    typeof value.category_win_gain === "number" &&
    value.category_win_gain >= -9 &&
    value.category_win_gain <= 9 &&
    typeof value.injury_penalty_pct === "number" &&
    value.injury_penalty_pct >= 0 &&
    value.injury_penalty_pct <= 15 &&
    Array.isArray(value.positions) &&
    value.positions.every(
      (position) => typeof position === "string" && POSITIONS.has(position),
    ) &&
    Array.isArray(value.reason_codes) &&
    value.reason_codes.every(isString)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}
