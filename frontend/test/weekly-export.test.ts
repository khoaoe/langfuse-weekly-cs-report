import { describe, expect, it } from "vitest";

import { WEEKLY_EXPORT_COLUMNS, buildWeeklyCsv, buildWeeklyTsv } from "../src/lib/weekly-export";

const newestRow = {
  cohort_week: "2026-07-20",
  cohort_status: "complete" as const,
  total_tickets: 10,
  ai_first_count: 8,
  ai_first_rate: 0.8,
  ai_end_to_end_count: 6,
  ai_then_cs_count: 2,
  direct_cs_count: 1,
  unclassified_count: 1,
  reopen_lifetime_numerator: 2,
  reopen_lifetime_rate: 0.25,
  ai_reply_mean_ai_first: 1.2,
  gt4_turn_with_cs: 1,
  gt4_turn_without_cs: 2,
};

const oldestRow = {
  ...newestRow,
  cohort_week: "2026-07-13",
  total_tickets: 7,
};

const exportOptions = {
  cohortLabel: "T2–CN",
  updatedAt: "2026-07-29 18:27",
} as const;

function quotedCsvCells(line: string): string[] {
  return line.match(/"(?:[^"]|"")*"/g) ?? [];
}

describe("weekly report exports", () => {
  it("emits a header-first rectangular TSV in newest-first screen order", () => {
    const lines = buildWeeklyTsv([oldestRow, newestRow], exportOptions).split("\n");

    expect(WEEKLY_EXPORT_COLUMNS).toEqual([
      "Tuần", "Tổng ticket", "AI First", "Tỷ lệ AI First", "AI xử lý trọn",
      "AI trả lời rồi chuyển CS", "Chuyển CS ngay từ đầu", "Tổng chuyển CS",
      "Reopen sau AI First", "Tỷ lệ reopen", "AI phản hồi/ticket TB", ">3 lượt xử lý + CS",
      ">3 lượt xử lý chưa chuyển", "Chưa phân loại",
    ]);
    expect(lines[0]?.split("\t")).toEqual([...WEEKLY_EXPORT_COLUMNS]);
    expect(lines.every((line) => line.split("\t").length === 14)).toBe(true);
    expect(lines.slice(1).map((line) => line.split("\t")[0])).toEqual([
      "20/07–26/07",
      "13/07–19/07",
    ]);
  });

  it("emits a rectangular metadata-bearing BOM CSV in newest-first screen order", () => {
    const csv = buildWeeklyCsv([oldestRow, newestRow], exportOptions);
    const lines = csv.slice(1).split("\r\n");
    const metadataCells = [
      "# Cohort",
      "T2–CN",
      "Cập nhật",
      "2026-07-29 18:27",
      ...Array.from({ length: 10 }, () => ""),
    ].map((value) => `"${value}"`);

    expect(csv.startsWith("\ufeff")).toBe(true);
    expect(quotedCsvCells(lines[0] ?? "")).toEqual(metadataCells);
    expect(quotedCsvCells(lines[1] ?? "")).toEqual(
      WEEKLY_EXPORT_COLUMNS.map((value) => `"${value}"`),
    );
    expect(lines.every((line) => quotedCsvCells(line).length === 14)).toBe(true);
    expect(lines.slice(2).map((line) => quotedCsvCells(line)[0])).toEqual([
      '"20/07–26/07"',
      '"13/07–19/07"',
    ]);
  });
});
