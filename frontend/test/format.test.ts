import { describe, expect, it } from "vitest";

import {
  formatCount,
  formatDateRangeLabel,
  formatRate,
  formatRateAxis,
  formatWeekRange,
  formatWeekStart,
  shareWithSampleGuard,
} from "../src/lib/format";

describe("dashboard formatting", () => {
  it("uses Vietnamese-readable counts, one-decimal percentage rates, and cohort ranges", () => {
    expect(formatCount(1_374)).toBe("1.374");
    expect(formatRate(0.798)).toBe("79,8%");
    expect(formatWeekRange("2026-07-20", "mon_sun")).toBe("20/07–26/07");
    expect(formatWeekRange("2026-07-20", "mon_fri")).toBe("20/07–24/07");
    expect(formatWeekStart("2026-07-20")).toBe("20/07");
  });

  it("never turns unavailable values into zero", () => {
    expect(formatRate(null)).toBe("—");
    expect(formatCount(null)).toBe("—");
    expect(formatWeekStart("not-a-week")).toBe("—");
  });

  it("formats an opened-date range, one open bound, or neither", () => {
    expect(formatDateRangeLabel("2026-07-06", "2026-07-30")).toBe("06/07–30/07");
    expect(formatDateRangeLabel("2026-07-06", "")).toBe("Từ 06/07");
    expect(formatDateRangeLabel("", "2026-07-30")).toBe("Đến 30/07");
    expect(formatDateRangeLabel("", "")).toBe("—");
  });

  it("drops the decimal when a rate carries no fractional information", () => {
    // "0,0%" implies a measured fraction that rounded down. Nothing was
    // measured: the count is exactly zero.
    expect(formatRate(0)).toBe("0%");
    expect(formatRate(1)).toBe("100%");
    // Everything between keeps its decimal, because half a point of AI First
    // movement is precisely what the weekly narrative reports on.
    expect(formatRate(0.798)).toBe("79,8%");
    expect(formatRate(0.029)).toBe("2,9%");
  });

  it("formats axis ticks as whole percentages", () => {
    // Gridlines are a scale, not a measurement. "0,0% 25,0% 50,0%" spends two
    // characters per tick to say nothing.
    expect(formatRateAxis(0)).toBe("0%");
    expect(formatRateAxis(0.25)).toBe("25%");
    expect(formatRateAxis(0.5)).toBe("50%");
    expect(formatRateAxis(1)).toBe("100%");
  });

  it("giau ty le khi mau duoi nguong va giu nguyen so dem", () => {
    expect(shareWithSampleGuard(3, 8)).toBe("3");
    expect(shareWithSampleGuard(30, 200)).toBe("30 · 15,0%");
  });
});
