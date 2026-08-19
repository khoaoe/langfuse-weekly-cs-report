/**
 * Derives the head-to-head comparison rows for the A/B section.
 *
 * Kept out of the component so the arithmetic — especially the small-sample
 * guards and the direction of "better" — is unit-testable on its own.
 */
import type { ArmMetrics } from "./ab-test-schema";

/** Which way is good. `neutral` rows are context, never scored. */
export type MetricDirection = "higher" | "lower" | "neutral";

/** `rate` deltas read in percentage points; the others read relative. */
export type MetricKind = "rate" | "number" | "seconds";

export interface MetricRow {
  readonly key: string;
  readonly label: string;
  readonly group: string;
  readonly kind: MetricKind;
  readonly direction: MetricDirection;
  /** Null when the metric has no denominator, or too small a one to assert. */
  readonly values: readonly (number | null)[];
  /** Per-arm denominator, surfaced so the reader can size the claim. */
  readonly denominators: readonly number[];
  readonly hint?: string;
}

/**
 * Below this many observations a rate is noise, so the row reports "—"
 * instead of a number that a single flipped ticket would move by points.
 * Matches `PERCENTAGE_SAMPLE_MINIMUM` in format.ts.
 */
export const RATE_SAMPLE_MINIMUM = 20;

function rate(numerator: number, denominator: number): number | null {
  return denominator >= RATE_SAMPLE_MINIMUM ? numerator / denominator : null;
}

function perTicket(total: number, tickets: number): number | null {
  return tickets > 0 ? total / tickets : null;
}

export function buildMetricRows(arms: readonly ArmMetrics[]): MetricRow[] {
  const map = <T,>(select: (arm: ArmMetrics) => T): T[] => arms.map(select);

  return [
    {
      key: "ticket_count",
      label: "Số ticket",
      group: "Mẫu",
      kind: "number",
      direction: "neutral",
      values: map((arm) => arm.ticket_count),
      denominators: map((arm) => arm.ticket_count),
    },
    {
      key: "share",
      label: "Tỉ lệ chia mẫu",
      group: "Mẫu",
      kind: "rate",
      direction: "neutral",
      values: map((arm) => arm.share),
      denominators: map((arm) => arm.ticket_count),
      hint: "Lệch nhiều so với tỉ lệ rollout dự kiến là dấu hiệu chia mẫu sai.",
    },
    {
      key: "ai_end_to_end",
      label: "AI xử lý trọn",
      group: "Kết quả xử lý",
      kind: "rate",
      direction: "higher",
      values: map((arm) => rate(arm.ai_end_to_end, arm.ticket_count)),
      denominators: map((arm) => arm.ticket_count),
      hint: "Ticket AI trả lời và không phải chuyển CS. Metric chính.",
    },
    {
      key: "ai_first",
      label: "AI First",
      group: "Kết quả xử lý",
      kind: "rate",
      direction: "higher",
      values: map((arm) => rate(arm.ai_first_count, arm.ticket_count)),
      denominators: map((arm) => arm.ticket_count),
    },
    {
      key: "transferred",
      label: "Chuyển CS",
      group: "Kết quả xử lý",
      kind: "rate",
      direction: "lower",
      values: map((arm) => rate(arm.transferred_count, arm.ticket_count)),
      denominators: map((arm) => arm.ticket_count),
    },
    {
      key: "direct_cs",
      label: "Vào thẳng CS",
      group: "Kết quả xử lý",
      kind: "rate",
      direction: "lower",
      values: map((arm) => rate(arm.direct_cs, arm.ticket_count)),
      denominators: map((arm) => arm.ticket_count),
    },
    {
      key: "reopen",
      label: "Reopen",
      group: "Kết quả xử lý",
      kind: "rate",
      direction: "lower",
      values: map((arm) => rate(arm.reopen_count, arm.reopen_denominator)),
      denominators: map((arm) => arm.reopen_denominator),
      hint: "Mẫu số là ticket AI First. Cửa sổ ngắn bị cắt cụt: ticket cuối kỳ chưa đủ thời gian để reopen.",
    },
    {
      key: "csat_positive",
      label: "CSAT hài lòng",
      group: "Kết quả xử lý",
      kind: "rate",
      direction: "higher",
      values: map((arm) =>
        rate(arm.csat_positive_count, arm.csat_response_count),
      ),
      denominators: map((arm) => arm.csat_response_count),
      hint: "Mẫu số là số phản hồi khảo sát, không phải số ticket. Cache CSAT chạy job riêng nên thường trễ hơn cửa sổ đang xem.",
    },
    {
      key: "latency_p50",
      label: "Thời gian xử lý p50",
      group: "Tốc độ",
      kind: "seconds",
      direction: "lower",
      values: map((arm) => arm.latency_p50),
      denominators: map((arm) => arm.ticket_count),
      hint: "Tổng thời gian mọi lượt trong 1 ticket.",
    },
    {
      key: "latency_p95",
      label: "Thời gian xử lý p95",
      group: "Tốc độ",
      kind: "seconds",
      direction: "lower",
      values: map((arm) => arm.latency_p95),
      denominators: map((arm) => arm.ticket_count),
    },
    {
      key: "llm_latency_p95",
      label: "Latency 1 LLM call p95",
      group: "Tốc độ",
      kind: "seconds",
      direction: "lower",
      values: map((arm) => arm.llm_latency_p95),
      denominators: map((arm) => arm.llm_call_count),
    },
    {
      key: "llm_calls_per_ticket",
      label: "LLM call / ticket",
      group: "Chi phí",
      kind: "number",
      direction: "lower",
      values: map((arm) => perTicket(arm.llm_call_count, arm.ticket_count)),
      denominators: map((arm) => arm.ticket_count),
    },
    {
      key: "tokens_per_ticket",
      label: "Token / ticket",
      group: "Chi phí",
      kind: "number",
      direction: "lower",
      values: map((arm) => perTicket(arm.total_tokens, arm.ticket_count)),
      denominators: map((arm) => arm.ticket_count),
    },
    {
      key: "output_tokens_per_ticket",
      label: "Token output / ticket",
      group: "Chi phí",
      kind: "number",
      direction: "lower",
      values: map((arm) => perTicket(arm.output_tokens, arm.ticket_count)),
      denominators: map((arm) => arm.ticket_count),
      hint: "Token output thường đắt hơn input nhiều lần.",
    },
    {
      key: "turns_per_ticket",
      label: "Lượt / ticket",
      group: "Chi phí",
      kind: "number",
      direction: "lower",
      values: map((arm) => perTicket(arm.turn_total, arm.ticket_count)),
      denominators: map((arm) => arm.ticket_count),
    },
  ];
}

export interface MetricDelta {
  /** Percentage points for `rate`, relative share for the others. */
  readonly value: number;
  /** True when the movement is in the direction the metric wants. */
  readonly better: boolean | null;
}

function directionVerdict(
  direction: MetricDirection,
  value: number,
): boolean | null {
  if (direction === "neutral" || value === 0) {
    return null;
  }
  return direction === "higher" ? value > 0 : value < 0;
}

/**
 * Compares the second arm against the first. Returns null whenever either
 * side is missing, so a suppressed small-sample value never produces a delta
 * that looks authoritative.
 */
export function metricDelta(row: MetricRow): MetricDelta | null {
  if (row.values.length !== 2) {
    return null;
  }
  const first = row.values[0];
  const second = row.values[1];
  if (
    first === null ||
    second === null ||
    first === undefined ||
    second === undefined
  ) {
    return null;
  }
  if (row.kind === "rate") {
    const value = second - first;
    return { value, better: directionVerdict(row.direction, value) };
  }
  if (first === 0) {
    return null;
  }
  const value = (second - first) / first;
  return { value, better: directionVerdict(row.direction, value) };
}
