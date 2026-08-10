import {
  formatCount,
  formatPoints,
  formatRate,
} from "./format";

export interface NarrativePeriod {
  readonly aiFirst: { readonly count: number | null; readonly rate: number | null };
  readonly reopenRate: number | null;
}

export interface NarrativeSignal {
  readonly label: string;
  readonly count: number;
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
  readonly transferSignals: readonly NarrativeSignal[];
  /** Transferred tickets the signals were observed on; 0 suppresses the line. */
  readonly transferDenominator: number;
  readonly gt4TurnWithoutCs: number;
  readonly enrichmentStatus: "complete" | "partial";
  readonly isWtd?: boolean;
  readonly samePeriod?: NarrativeSamePeriod;
}

/** Below this many percentage points a week-over-week move is not a trend. */
const FLAT_POINT_THRESHOLD = 0.5;
const MAX_TRANSFER_SIGNALS = 3;
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
 * called, and the transfer sentence stays observational because the payload
 * carries operational TPE signals rather than a proven cause.
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

  const signals = [...input.transferSignals]
    .sort((left, right) => right.count - left.count)
    .slice(0, MAX_TRANSFER_SIGNALS);
  // The reader is weighing these reasons against each other, so the comparable
  // quantity is each one's share of the transferred population. Without a
  // denominator no share exists, and the line is dropped rather than guessed.
  const transferLine =
    signals.length > 0 && input.transferDenominator > 0
      ? `Tín hiệu chuyển CS nổi bật: ${signals
          .map(
            (signal) =>
              `${signal.label} ${formatRate(
                signal.count / input.transferDenominator,
              )}`,
          )
          .join(", ")} — tính trên ${formatCount(
          input.transferDenominator,
        )} ticket đã chuyển CS.`
      : null;

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

  if (
    transferLine !== null &&
    lines.length + warnings.length < MAX_NARRATIVE_LINES
  ) {
    // Deliberately observational. The payload proves no causal link, so this
    // must never read as "nguyên nhân".
    lines.push(transferLine);
  }

  return [...lines, ...warnings].slice(0, MAX_NARRATIVE_LINES);
}
