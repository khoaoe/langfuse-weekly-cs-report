import { formatAverage, formatCount, formatRate, formatWeekRange } from "./format";
import type { WeekDefinition } from "./dashboard-schema";
import { csvCell, tsvCell } from "./spreadsheet";

/**
 * The Weekly Report export contract: exactly these fourteen columns, in this
 * order, in the clipboard TSV and CSV download. The screen can group the same
 * values by ticket flow without changing this downstream hand-off.
 */
export const WEEKLY_EXPORT_COLUMNS = [
  "Tuần",
  "Tổng ticket",
  "AI First",
  "Tỷ lệ AI First",
  "AI xử lý trọn",
  "AI trả lời rồi chuyển CS",
  "Chuyển CS ngay từ đầu",
  "Tổng chuyển CS",
  "Reopen sau AI First",
  "Tỷ lệ reopen",
  "AI phản hồi/ticket TB",
  ">3 lượt xử lý + CS",
  ">3 lượt xử lý chưa chuyển",
  "Chưa phân loại",
] as const;

export type WeeklyExportColumn = (typeof WEEKLY_EXPORT_COLUMNS)[number];

export interface WeeklyExportRow {
  readonly cohort_week: string;
  readonly cohort_status: "complete" | "wtd";
  readonly total_tickets: number;
  readonly ai_first_count: number;
  readonly ai_first_rate: number | null;
  readonly ai_end_to_end_count: number;
  readonly ai_then_cs_count: number;
  readonly direct_cs_count: number;
  readonly unclassified_count: number;
  readonly reopen_lifetime_numerator: number;
  readonly reopen_lifetime_rate: number | null;
  readonly ai_reply_mean_ai_first: number | null;
  readonly gt4_turn_with_cs: number;
  readonly gt4_turn_without_cs: number;
}

export interface WeeklyExportOptions {
  readonly cohortLabel: string;
  readonly updatedAt: string;
  readonly weekDefinition?: WeekDefinition;
  /** Day-range mode: honest truncated-week label per `cohort_week`, overriding the full week span. */
  readonly weekLabels?: Readonly<Record<string, string>>;
}

/** A week with no tickets is reported as absent, never as a row of zeros. */
export const EMPTY_WEEK_LABEL = "Không có dữ liệu";
const UNAVAILABLE = "—";
const BOM = "﻿";

export function weekLabel(
  row: Pick<WeeklyExportRow, "cohort_week" | "cohort_status">,
  weekDefinition: WeekDefinition,
  labelOverride?: string,
): string {
  if (labelOverride !== undefined) {
    return row.cohort_status === "wtd" ? `${labelOverride} (WTD)` : labelOverride;
  }
  const range = formatWeekRange(row.cohort_week, weekDefinition);
  return row.cohort_status === "wtd" ? `${range} (WTD)` : range;
}

/**
 * Renders one weekly row as the fourteen contract cells.
 *
 * Weeks without tickets carry the explicit empty label instead of zeros, so a
 * gap in Langfuse coverage cannot be misread as a week of perfect silence.
 * `labelOverride` swaps in the honest first/last-touched-day label for a week
 * truncated by a day-range selection, instead of the full Monday-start span.
 */
export function weeklyExportCells(
  row: WeeklyExportRow,
  weekDefinition: WeekDefinition = "mon_sun",
  labelOverride?: string,
): string[] {
  const label = weekLabel(row, weekDefinition, labelOverride);
  if (row.total_tickets === 0) {
    return [
      label,
      EMPTY_WEEK_LABEL,
      ...Array.from({ length: WEEKLY_EXPORT_COLUMNS.length - 2 }, () => UNAVAILABLE),
    ];
  }

  return [
    label,
    formatCount(row.total_tickets),
    formatCount(row.ai_first_count),
    formatRate(row.ai_first_rate),
    formatCount(row.ai_end_to_end_count),
    formatCount(row.ai_then_cs_count),
    formatCount(row.direct_cs_count),
    formatCount(row.ai_then_cs_count + row.direct_cs_count),
    formatCount(row.reopen_lifetime_numerator),
    formatRate(row.reopen_lifetime_rate),
    formatAverage(row.ai_reply_mean_ai_first),
    formatCount(row.gt4_turn_with_cs),
    formatCount(row.gt4_turn_without_cs),
    formatCount(row.unclassified_count),
  ];
}

/**
 * Canonical report-export order.
 *
 * The screen starts newest-first but can be sorted interactively. TSV and CSV
 * deliberately keep this governed chronological order so a transient UI sort
 * cannot silently change the weekly hand-off.
 */
export function newestFirstWeeklyRows(
  rows: readonly WeeklyExportRow[],
): WeeklyExportRow[] {
  return [...rows].sort((left, right) =>
    right.cohort_week.localeCompare(left.cohort_week),
  );
}

function csvMetadataCells(options: WeeklyExportOptions): string[] {
  const metadata = ["# Cohort", options.cohortLabel, "Cập nhật", options.updatedAt];
  return WEEKLY_EXPORT_COLUMNS.map((_, index) => metadata[index] ?? "");
}

export function buildWeeklyTsv(
  rows: readonly WeeklyExportRow[],
  options: WeeklyExportOptions,
): string {
  const weekDefinition = options.weekDefinition ?? "mon_sun";
  return [
    WEEKLY_EXPORT_COLUMNS.map(tsvCell).join("\t"),
    ...newestFirstWeeklyRows(rows).map((row) =>
      weeklyExportCells(row, weekDefinition, options.weekLabels?.[row.cohort_week])
        .map(tsvCell)
        .join("\t"),
    ),
  ].join("\n");
}

export function buildWeeklyCsv(
  rows: readonly WeeklyExportRow[],
  options: WeeklyExportOptions,
): string {
  const weekDefinition = options.weekDefinition ?? "mon_sun";
  const body = [
    csvMetadataCells(options).map(csvCell).join(","),
    WEEKLY_EXPORT_COLUMNS.map(csvCell).join(","),
    ...newestFirstWeeklyRows(rows).map((row) =>
      weeklyExportCells(row, weekDefinition, options.weekLabels?.[row.cohort_week])
        .map(csvCell)
        .join(","),
    ),
  ].join("\r\n");
  // Excel on Windows only detects UTF-8 from the byte-order mark.
  return `${BOM}${body}`;
}
