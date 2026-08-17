import type { WeekDefinition } from "./dashboard-schema";

const countFormatter = new Intl.NumberFormat("vi-VN", {
  maximumFractionDigits: 0,
});

const rateFormatter = new Intl.NumberFormat("vi-VN", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const averageFormatter = new Intl.NumberFormat("vi-VN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function isAvailableNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function formatCount(value: number | null | undefined): string {
  return isAvailableNumber(value) ? countFormatter.format(value) : "—";
}

const wholeRateFormatter = new Intl.NumberFormat("vi-VN", {
  maximumFractionDigits: 0,
});

/**
 * Renders a rate, keeping the decimal only where it carries information.
 *
 * Exactly none and exactly all are counted facts rather than measurements that
 * happened to round, so "0,0%" invites the reader to look for a fraction that
 * does not exist. Every value between keeps one decimal, because half a point
 * of week-over-week movement is what the narrative reports on.
 */
export function formatRate(value: number | null | undefined): string {
  if (!isAvailableNumber(value)) {
    return "—";
  }
  if (value === 0 || value === 1) {
    return `${wholeRateFormatter.format(value * 100)}%`;
  }
  return `${rateFormatter.format(value * 100)}%`;
}

/** Formats a chart axis tick, which is a scale rather than a measurement. */
export function formatRateAxis(value: number): string {
  return `${wholeRateFormatter.format(value * 100)}%`;
}

/**
 * Below this many samples, a percentage implies more precision than the data
 * supports — a single flipped rating can swing it by several points. Callers
 * fall back to the raw count instead of asserting a rate.
 */
export const PERCENTAGE_SAMPLE_MINIMUM = 20;

/**
 * Renders "count · rate" when the denominator clears the small-sample
 * threshold, or just the raw count when it doesn't.
 */
export function shareWithSampleGuard(count: number, denominator: number): string {
  return denominator >= PERCENTAGE_SAMPLE_MINIMUM
    ? `${formatCount(count)} · ${formatRate(count / denominator)}`
    : formatCount(count);
}

export function formatAverage(value: number | null | undefined): string {
  return isAvailableNumber(value) ? averageFormatter.format(value) : "—";
}

/** Formats an already-computed percentage-point magnitude, e.g. `3.2` to `3,2`. */
export function formatPoints(points: number): string {
  return rateFormatter.format(points);
}

export function formatPointDelta(value: number): string {
  const percentagePoints = Math.abs(value * 100);
  const sign = value < 0 ? "−" : value > 0 ? "+" : "";
  return `${sign}${rateFormatter.format(percentagePoints)} điểm`;
}

const WEEKDAY_NAMES = [
  "",
  "thứ Hai",
  "thứ Ba",
  "thứ Tư",
  "thứ Năm",
  "thứ Sáu",
  "thứ Bảy",
  "Chủ nhật",
] as const;

const WEEKDAY_CODES = ["", "T2", "T3", "T4", "T5", "T6", "T7", "CN"] as const;

export function formatWeekdayName(value: number): string {
  return WEEKDAY_NAMES[value] ?? "ngày đã chọn";
}

export function formatWeekdayCode(value: number): string {
  return WEEKDAY_CODES[value] ?? "cùng kỳ";
}

function parseIsoDate(value: string | null | undefined): Date | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return null;
  }

  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year ?? 0, (month ?? 1) - 1, day ?? 1));
  if (
    !Number.isFinite(parsed.getTime()) ||
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== (month ?? 1) - 1 ||
    parsed.getUTCDate() !== day
  ) {
    return null;
  }
  return parsed;
}

function compactDate(date: Date): string {
  return `${String(date.getUTCDate()).padStart(2, "0")}/${String(
    date.getUTCMonth() + 1,
  ).padStart(2, "0")}`;
}

export function formatWeekStart(value: string | null | undefined): string {
  const parsed = parseIsoDate(value);
  return parsed === null ? "—" : compactDate(parsed);
}

export function formatWeekRange(
  cohortWeek: string | null | undefined,
  weekDefinition: WeekDefinition,
): string {
  const start = parseIsoDate(cohortWeek);
  if (start === null) {
    return "—";
  }

  const end = new Date(start);
  end.setUTCDate(start.getUTCDate() + (weekDefinition === "mon_fri" ? 4 : 6));

  return `${compactDate(start)}–${compactDate(end)}`;
}

export function formatUpdatedAt(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }

  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) {
    return "—";
  }

  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Asia/Ho_Chi_Minh",
  }).format(parsed);
}
