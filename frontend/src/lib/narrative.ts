import {
  formatCount,
  formatPoints,
} from "./format";

export interface NarrativePeriod {
  readonly aiFirst: { readonly count: number | null; readonly rate: number | null };
  readonly reopenRate: number | null;
}

export interface NarrativeSamePeriod {
  readonly cutoffWeekday: number;
  readonly weeksUsed: number;
  readonly aiFirstRate: number;
  readonly reopenRate: number | null;
}

export interface NarrativeInput {
  readonly current: NarrativePeriod;
  readonly previous: NarrativePeriod | null;
  readonly gt4TurnWithoutCs: number;
  readonly enrichmentStatus: "complete" | "partial";
  readonly isWtd?: boolean;
  readonly samePeriod?: NarrativeSamePeriod;
}

/** Below this many percentage points a week-over-week move is not a trend. */
const FLAT_POINT_THRESHOLD = 0.5;
const MAX_NARRATIVE_LINES = 4;

/**
 * Describes only the change that the KPI cells below do not already state.
 */
function comparison(
  label: string,
  current: number | null,
  previous: number | null,
  baselineLabel: string,
): string | null {
  if (previous === null || current === null) {
    return null;
  }

  const delta = current - previous;
  const points = Math.abs(delta) * 100;
  if (points < FLAT_POINT_THRESHOLD) {
    return `${label} gần như không đổi so với ${baselineLabel}.`;
  }
  return `${label} ${delta > 0 ? "tăng" : "giảm"} ${formatPoints(
    points,
  )} điểm so với ${baselineLabel}.`;
}

/**
 * Builds the narrative shown under the dynamic title.
 *
 * Every sentence is derived arithmetically from the snapshot: no model is
 * called.
 */
export function buildDeterministicNarrative(input: NarrativeInput): string[] {
  const isWtd = input.isWtd === true;
  const previousAiRate = input.previous?.aiFirst.rate ?? null;
  const previousReopenRate = input.previous?.reopenRate ?? null;

  let lines: string[] = [];
  if (
    isWtd &&
    input.samePeriod !== undefined &&
    input.current.aiFirst.rate !== null
  ) {
    const samePeriod = input.samePeriod;
    const baselineLabel = `trung bình cùng kỳ ${formatCount(
      samePeriod.weeksUsed,
    )} tuần trước`;
    lines = [
      comparison(
        "AI First",
        input.current.aiFirst.rate,
        samePeriod.aiFirstRate,
        baselineLabel,
      ),
      comparison(
        "Reopen sau AI First",
        input.current.reopenRate,
        samePeriod.reopenRate,
        baselineLabel,
      ),
    ].filter((line): line is string => line !== null);
  } else if (!isWtd) {
    lines = [
      comparison(
        "AI First",
        input.current.aiFirst.rate,
        previousAiRate,
        "tuần trước",
      ),
      comparison(
        "Reopen sau AI First",
        input.current.reopenRate,
        previousReopenRate,
        "tuần trước",
      ),
    ].filter((line): line is string => line !== null);
  }

  const warnings: string[] = [];
  if (input.gt4TurnWithoutCs > 0) {
    warnings.push(
      `${formatCount(
        input.gt4TurnWithoutCs,
      )} ticket có hơn 3 lượt xử lý mà chưa chuyển CS — khách nhiều khả năng đang mắc kẹt.`,
    );
  }

  if (input.enrichmentStatus === "partial") {
    warnings.push(
      "Lần đọc này chưa lấy đủ dữ liệu phụ từ Langfuse, nên Intent, Skill, Transstatus và Step result còn thiếu.",
    );
  }

  return [...lines, ...warnings].slice(0, MAX_NARRATIVE_LINES);
}
