const STALE_AFTER_MS = 7 * 24 * 60 * 60 * 1000;
const REQUIRED_ARTIFACTS = new Set([
  "projections",
  "reference",
  "injury_assessments",
]);

export type Freshness =
  | { status: "fresh" }
  | { status: "stale"; ageDays: number }
  | { status: "unknown"; message: string };

export function assessFreshness(value: unknown, now = Date.now()): Freshness {
  if (!isRecord(value) || !Array.isArray(value.artifacts)) {
    return {
      status: "unknown",
      message: "Data freshness could not be determined.",
    };
  }
  const timestamps = value.artifacts
    .filter(
      (artifact): artifact is Record<string, unknown> =>
        isRecord(artifact) && REQUIRED_ARTIFACTS.has(artifact.name as string),
    )
    .map((artifact) => artifact.modified_at)
    .map((modifiedAt) =>
      typeof modifiedAt === "string" ? Date.parse(modifiedAt) : Number.NaN,
    );
  if (
    timestamps.length !== REQUIRED_ARTIFACTS.size ||
    timestamps.some(Number.isNaN)
  ) {
    return {
      status: "unknown",
      message: "Data freshness could not be determined.",
    };
  }
  const oldest = Math.min(...timestamps);
  const ageMs = Math.max(0, now - oldest);
  if (ageMs >= STALE_AFTER_MS) {
    return {
      status: "stale",
      ageDays: Math.floor(ageMs / (24 * 60 * 60 * 1000)),
    };
  }
  return { status: "fresh" };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
