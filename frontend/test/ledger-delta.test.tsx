import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { dashboardEnvelopeFixture } from "./fixtures/dashboard";
import {
  DashboardEnvelopeSchema,
  type DashboardSnapshot,
  type WeeklyReportRow,
} from "../src/lib/dashboard-schema";
import { DecisionLedger } from "../src/components/DecisionLedger";
import { selectLedger } from "../src/lib/selectors";

const baseSnapshot = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture)
  .snapshot as DashboardSnapshot;
const template = baseSnapshot.views.mon_sun.weekly[0] as WeeklyReportRow;

function week(
  cohortWeek: string,
  status: WeeklyReportRow["cohort_status"],
  counts: {
    total: number;
    aiEndToEnd: number;
    aiThenCs: number;
    directCs: number;
    reopen: number;
  },
): WeeklyReportRow {
  const aiFirst = counts.aiEndToEnd + counts.aiThenCs;
  return {
    ...template,
    cohort_week: cohortWeek,
    cohort_status: status,
    has_data: true,
    total_tickets: counts.total,
    ai_first_count: aiFirst,
    ai_first_rate: aiFirst / counts.total,
    ai_end_to_end_count: counts.aiEndToEnd,
    ai_then_cs_count: counts.aiThenCs,
    direct_cs_count: counts.directCs,
    reopen_lifetime_numerator: counts.reopen,
    reopen_lifetime_denominator: aiFirst,
    reopen_lifetime_rate: aiFirst === 0 ? null : counts.reopen / aiFirst,
  };
}

function withWeeks(
  weekly: WeeklyReportRow[],
  samePeriod: DashboardSnapshot["views"]["mon_sun"]["same_period"] = null,
): DashboardSnapshot {
  return {
    ...baseSnapshot,
    views: {
      ...baseSnapshot.views,
      mon_sun: { ...baseSnapshot.views.mon_sun, weekly, same_period: samePeriod },
    },
  };
}

function deltas(snapshot: DashboardSnapshot, activeWeek?: string) {
  const [primary] = selectLedger(snapshot, "mon_sun", activeWeek);
  return {
    comparison: primary?.comparison ?? null,
    byId: Object.fromEntries(
      (primary?.cells ?? []).map((cell) => [cell.id, cell.delta]),
    ),
    tones: Object.fromEntries(
      (primary?.cells ?? []).map((cell) => [cell.id, cell.tone]),
    ),
  };
}

const previous = week("2026-07-13", "complete", {
  total: 100,
  aiEndToEnd: 40,
  aiThenCs: 20,
  directCs: 30,
  reopen: 6,
});
const completed = week("2026-07-20", "complete", {
  total: 100,
  aiEndToEnd: 45,
  aiThenCs: 20,
  directCs: 25,
  reopen: 13,
});

describe("ledger deltas", () => {
  it("compares a completed week with the previous completed week", () => {
    const result = deltas(withWeeks([previous, completed]));

    expect(result.comparison).toBe("so với tuần 13/07");
    expect(result.byId).toEqual({
      "ledger-ai-first": { text: "▲ +5,0 điểm", baseline: "so với 60,0% tuần 13/07", tone: "neutral" },
      "ledger-ai-end-to-end": { text: "▲ +5,0 điểm", baseline: "so với 40,0% tuần 13/07", tone: "neutral" },
      "ledger-transfer": { text: "▼ −5,0 điểm", baseline: "so với 50,0% tuần 13/07", tone: "neutral" },
      // 13/65 = 0,20 vs 6/60 = 0,10 lần/ticket: rising reopen is the one
      // movement the ledger tones as bad.
      "ledger-reopen": { text: "▲ +0,10 lần/ticket", baseline: "so với 0,10 tuần 13/07", tone: "warning" },
    });
    expect(result.tones["ledger-reopen"]).toBe("warning");
  });

  it("does not tone a falling reopen rate as a warning", () => {
    const better = week("2026-07-20", "complete", {
      total: 100,
      aiEndToEnd: 40,
      aiThenCs: 20,
      directCs: 30,
      reopen: 3,
    });
    const result = deltas(withWeeks([previous, better]));

    expect(result.byId["ledger-reopen"]).toEqual({
      text: "▼ −0,05 lần/ticket",
      baseline: "so với 0,10 tuần 13/07",
      tone: "neutral",
    });
    expect(result.tones["ledger-reopen"]).toBe("neutral");
  });

  it("compares a running week with the same-period baseline, never with a full week", () => {
    const running = week("2026-07-20", "wtd", {
      total: 40,
      aiEndToEnd: 18,
      aiThenCs: 6,
      directCs: 10,
      reopen: 2,
    });
    const result = deltas(
      withWeeks([previous, running], {
        cutoff_date: "2026-07-23",
        cutoff_weekday: 4,
        current: {
          cohort_week: "2026-07-20",
          total_tickets: 40,
          ai_first_count: 24,
          ai_first_rate: 0.6,
          reopen_lifetime_rate: 2 / 24,
          reopen_lifetime_numerator: 2,
          reopen_lifetime_denominator: 24,
        },
        baseline: {
          weeks_used: 3,
          ai_first_rate: 0.55,
          reopen_lifetime_rate: 0.1,
        },
        by_week: {},
      }),
    );

    expect(result.comparison).toBe("so với cùng kỳ tới thứ Năm các tuần trước");
    // same_period carries AI First and reopen only; the other two cells have
    // no like-for-like baseline and so show no delta at all.
    expect(result.byId).toEqual({
      "ledger-ai-first": {
        text: "▲ +5,0 điểm",
        baseline: "so với 55,0% cùng kỳ tới thứ Năm các tuần trước",
        tone: "neutral",
      },
      "ledger-ai-end-to-end": null,
      "ledger-transfer": null,
      "ledger-reopen": {
        text: "▼ −0,02 lần/ticket",
        baseline: "so với 0,10 cùng kỳ tới thứ Năm các tuần trước",
        tone: "neutral",
      },
    });
  });

  it("shows no delta, not a zero, when there is no valid baseline", () => {
    const running = week("2026-07-20", "wtd", {
      total: 40,
      aiEndToEnd: 18,
      aiThenCs: 6,
      directCs: 10,
      reopen: 2,
    });

    for (const snapshot of [
      withWeeks([completed]),
      withWeeks([previous, running]),
    ]) {
      const result = deltas(snapshot);
      expect(result.comparison).toBeNull();
      expect(Object.values(result.byId).every((delta) => delta === null)).toBe(
        true,
      );
    }

    render(
      <DecisionLedger
        snapshot={withWeeks([previous, running])}
        weekDefinition="mon_sun"
      />,
    );
    expect(screen.queryByText(/[▲▼]/)).toBeNull();
    expect(screen.queryByText(/0,0 điểm/)).toBeNull();
  });

  it("renders four headline cells with their deltas and the other five as one secondary row", () => {
    render(
      <DecisionLedger
        snapshot={withWeeks([previous, completed])}
        weekDefinition="mon_sun"
      />,
    );

    const grid = document.getElementById("kpiGrid");
    expect(grid?.children).toHaveLength(4);
    expect(document.getElementById("ledger-ai-first")).toHaveTextContent(
      "▲ +5,0 điểm",
    );
    // Every delta names its own baseline; the heading no longer carries it.
    expect(document.getElementById("ledger-ai-first")).toHaveTextContent(
      "so với 60,0% tuần 13/07",
    );
    expect(document.getElementById("ledger-group-ticket")).toHaveTextContent(
      "Chỉ số chính",
    );
    const secondary = document.getElementById("ledger-secondary");
    expect(secondary?.children).toHaveLength(5);
    expect(document.getElementById("narrativeSummary")).toBeNull();
  });
});
