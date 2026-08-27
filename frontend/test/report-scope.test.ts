import { describe, expect, it } from "vitest";

import { resolveDateRangeToWeeks } from "../src/lib/report-scope";
import type { WeeklyReportRow } from "../src/lib/dashboard-schema";

function week(cohortWeek: string, hasData = true): WeeklyReportRow {
  return { cohort_week: cohortWeek, has_data: hasData } as WeeklyReportRow;
}

describe("resolveDateRangeToWeeks", () => {
  it("includes a week touched only at its left edge", () => {
    // mon_fri week 2026-07-20 spans Mon 20/07–Fri 24/07.
    const weekly = [week("2026-07-20")];
    expect(
      resolveDateRangeToWeeks(weekly, "mon_fri", "2026-07-20", "2026-07-20"),
    ).toEqual(["2026-07-20"]);
  });

  it("includes a week touched only at its right edge", () => {
    const weekly = [week("2026-07-20")];
    expect(
      resolveDateRangeToWeeks(weekly, "mon_fri", "2026-07-24", "2026-07-24"),
    ).toEqual(["2026-07-20"]);
  });

  it("resolves a range that sits entirely inside one week", () => {
    const weekly = [week("2026-07-20")];
    expect(
      resolveDateRangeToWeeks(weekly, "mon_fri", "2026-07-21", "2026-07-22"),
    ).toEqual(["2026-07-20"]);
  });

  it("returns every week with data when the range spans more than the observed period", () => {
    const weekly = [week("2026-07-06"), week("2026-07-13"), week("2026-07-20")];
    expect(
      resolveDateRangeToWeeks(weekly, "mon_fri", "2026-01-01", "2026-12-31"),
    ).toEqual(["2026-07-06", "2026-07-13", "2026-07-20"]);
  });

  it("returns an empty array when the range only touches a week without data", () => {
    const weekly = [week("2026-07-20", false)];
    expect(
      resolveDateRangeToWeeks(weekly, "mon_fri", "2026-07-20", "2026-07-24"),
    ).toEqual([]);
  });

  it("differs between mon_fri and mon_sun for the same range touching only the weekend", () => {
    // mon_fri week 2026-07-20 ends Fri 24/07; mon_sun ends Sun 26/07.
    const weekly = [week("2026-07-20")];
    expect(
      resolveDateRangeToWeeks(weekly, "mon_sun", "2026-07-25", "2026-07-26"),
    ).toEqual(["2026-07-20"]);
    expect(
      resolveDateRangeToWeeks(weekly, "mon_fri", "2026-07-25", "2026-07-26"),
    ).toEqual([]);
  });

  it("returns an empty array without throwing on malformed or missing bounds", () => {
    const weekly = [week("2026-07-20")];
    expect(resolveDateRangeToWeeks(weekly, "mon_fri", "", "")).toEqual([]);
    expect(
      resolveDateRangeToWeeks(weekly, "mon_fri", "not-a-date", "2026-07-24"),
    ).toEqual([]);
    expect(
      resolveDateRangeToWeeks(weekly, "mon_fri", "2026-07-20", "also-bad"),
    ).toEqual([]);
  });
});
