import type { DashboardSnapshot } from "./dashboard-schema";

/** Five-minute cache TTL plus the governed two-minute refresh allowance. */
export const DATA_QUALITY_FRESHNESS_WINDOW_MS = 7 * 60 * 1_000;
export const DATA_STALE_DISPLAY_MS = 15 * 60 * 1_000;
const MAX_CLOCK_SKEW_MS = 60 * 1_000;

export type DataQualityTone = "good" | "warning" | "critical";

export interface DataQualityScore {
  readonly score: number;
  readonly tone: DataQualityTone;
  readonly freshnessOk: boolean;
  readonly ageMs: number | null;
  readonly structuralValidRate: number;
}

function qualityTone(score: number): DataQualityTone {
  if (score >= 90) {
    return "good";
  }
  if (score >= 70) {
    return "warning";
  }
  return "critical";
}

/**
 * Implements SPEC-v2 §5.13 at the presentation boundary.
 *
 * The structural gate remains a separate backend safety decision. This score
 * combines structural validity, enrichment coverage and snapshot freshness so
 * the header cannot imply that structurally valid but incomplete data is good.
 */
export function calculateDataQualityScore(
  snapshot: DashboardSnapshot,
  nowMs = Date.now(),
): DataQualityScore {
  const generatedAtMs = Date.parse(snapshot.generated_at);
  const ageMs = Number.isFinite(generatedAtMs)
    ? nowMs - generatedAtMs
    : null;
  const freshnessOk =
    ageMs !== null &&
    ageMs >= -MAX_CLOCK_SKEW_MS &&
    ageMs <= DATA_QUALITY_FRESHNESS_WINDOW_MS;
  const structuralValidRate =
    1 - snapshot.gate_status.structural_invalid_rate;
  const weighted =
    0.4 * structuralValidRate +
    0.2 * snapshot.coverage.issue_category +
    0.2 * snapshot.coverage.tpe +
    0.1 * snapshot.coverage.skill +
    0.1 * (freshnessOk ? 1 : 0);
  const score = Math.max(0, Math.min(100, Math.round(100 * weighted)));

  return {
    score,
    tone: qualityTone(score),
    freshnessOk,
    ageMs,
    structuralValidRate,
  };
}

export function formatDataAge(ageMs: number | null): string {
  if (ageMs === null) {
    return "không xác định";
  }
  if (ageMs < 0) {
    return "đồng hồ thiết bị lệch";
  }
  const minutes = Math.floor(ageMs / 60_000);
  if (minutes < 1) {
    return "dưới 1 phút";
  }
  if (minutes < 60) {
    return `${minutes} phút`;
  }
  const hours = Math.floor(minutes / 60);
  return `${hours} giờ ${minutes % 60} phút`;
}
