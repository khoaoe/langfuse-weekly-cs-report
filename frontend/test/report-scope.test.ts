import { describe, expect, it } from "vitest";

import {
  aggregateDays,
  resolveDateRangeToWeeks,
  rollDaysIntoWeeks,
  rollingRate,
  scopeSnapshotToDayRange,
  scopeSnapshotToDayRangeSnapshot,
} from "../src/lib/report-scope";
import {
  DashboardEnvelopeSchema,
  DashboardViewSchema,
  type DashboardSnapshot,
  type DayAggregate,
  type WeeklyReportRow,
} from "../src/lib/dashboard-schema";
import { dashboardEnvelopeFixture } from "./fixtures/dashboard";

function week(cohortWeek: string, hasData = true): WeeklyReportRow {
  return { cohort_week: cohortWeek, has_data: hasData } as WeeklyReportRow;
}

function day(overrides: Partial<DayAggregate> & { day: string }): DayAggregate {
  return {
    total_tickets: 0,
    ai_first_count: 0,
    transferred_count: 0,
    direct_cs_count: 0,
    outcomes: { ai_end_to_end: 0, ai_then_cs: 0, direct_cs: 0, unclassified: 0 },
    reopen_lifetime_numerator: 0,
    reopen_lifetime_denominator: 0,
    gt4_turn_with_cs: 0,
    gt4_turn_without_cs: 0,
    resolved_first_reply_count: 0,
    ai_reply_sum_ai_first: 0,
    segments: { skill: {}, app: {}, issue_category: {} },
    transfer_reasons: {},
    ...overrides,
  };
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

describe("aggregateDays", () => {
  it("returns empty totals for an empty range", () => {
    const totals = aggregateDays([]);
    expect(totals.eligible).toBe(0);
    expect(totals.aiFirstCount).toBe(0);
    expect(totals.aiFirstRate).toBe(0);
    expect(totals.reopenLifetimeNumerator).toBe(0);
    expect(totals.reopenLifetimeDenominator).toBe(0);
  });

  it("sums multiple days correctly", () => {
    const days = [
      day({
        day: "2026-08-03",
        total_tickets: 10,
        ai_first_count: 7,
        transferred_count: 3,
        direct_cs_count: 2,
        outcomes: { ai_end_to_end: 5, ai_then_cs: 3, direct_cs: 2, unclassified: 0 },
        reopen_lifetime_numerator: 2,
        reopen_lifetime_denominator: 10,
      }),
      day({
        day: "2026-08-04",
        total_tickets: 5,
        ai_first_count: 3,
        transferred_count: 1,
        direct_cs_count: 1,
        outcomes: { ai_end_to_end: 3, ai_then_cs: 1, direct_cs: 1, unclassified: 0 },
        reopen_lifetime_numerator: 1,
        reopen_lifetime_denominator: 5,
      }),
    ];

    const totals = aggregateDays(days);

    expect(totals.eligible).toBe(15);
    expect(totals.aiFirstCount).toBe(10);
    expect(totals.aiFirstRate).toBeCloseTo(10 / 15);
    expect(totals.transferTotal).toBe(4);
    expect(totals.directCsCount).toBe(3);
    expect(totals.reopenLifetimeNumerator).toBe(3);
    expect(totals.reopenLifetimeDenominator).toBe(15);
    expect(totals.aiEndToEndCount).toBe(8);
  });

  it("handles a single day the same as multiple days", () => {
    const totals = aggregateDays([
      day({ day: "2026-08-03", total_tickets: 4, ai_first_count: 4 }),
    ]);
    expect(totals.eligible).toBe(4);
    expect(totals.aiFirstCount).toBe(4);
    expect(totals.aiFirstRate).toBe(1);
  });

  it("does not divide by zero when reopen_lifetime_denominator is zero", () => {
    const totals = aggregateDays([
      day({
        day: "2026-08-03",
        reopen_lifetime_numerator: 0,
        reopen_lifetime_denominator: 0,
      }),
    ]);
    expect(totals.reopenLifetimeDenominator).toBe(0);
    expect(Number.isNaN(totals.reopenLifetimeRate)).toBe(false);
  });

  it("sums resolved-first-reply and ai-first reply counts, weighted-mean-ready", () => {
    // Mirrors selectScope()'s week-grain resolvedFirstReply/aiReplyMeanAiFirst:
    // sum numerators/counts across days, divide once at the call site -- never
    // average a per-day mean.
    const days = [
      day({
        day: "2026-08-03",
        ai_first_count: 7,
        resolved_first_reply_count: 4,
        ai_reply_sum_ai_first: 9,
      }),
      day({
        day: "2026-08-04",
        ai_first_count: 3,
        resolved_first_reply_count: 1,
        ai_reply_sum_ai_first: 5,
      }),
    ];

    const totals = aggregateDays(days);

    expect(totals.resolvedFirstReplyCount).toBe(5);
    expect(totals.aiReplySumAiFirst).toBe(14);
    expect(totals.aiReplyMeanAiFirst).toBeCloseTo(14 / 10);
  });

  it("returns null aiReplyMeanAiFirst when no ai_first ticket is in range", () => {
    const totals = aggregateDays([
      day({ day: "2026-08-03", ai_first_count: 0, ai_reply_sum_ai_first: 0 }),
    ]);
    expect(totals.aiReplyMeanAiFirst).toBeNull();
  });
});

describe("rollingRate", () => {
  const numerator = (d: DayAggregate) => d.ai_first_count;
  const denominator = (d: DayAggregate) => d.total_tickets;

  it("sums numerator and denominator across the window rather than averaging rates", () => {
    // Day A: 100 tickets, 50 ai_first (50%). Day B: 2 tickets, 2 ai_first (100%).
    // Averaging rates gives 75%; summing then dividing gives 52/102 ~= 51%.
    const days = [
      day({ day: "2026-08-01", total_tickets: 100, ai_first_count: 50 }),
      day({ day: "2026-08-02", total_tickets: 2, ai_first_count: 2 }),
    ];

    const rates = rollingRate(days, 2, numerator, denominator);

    expect(rates[1]).toBeCloseTo(52 / 102);
    expect(rates[1]).not.toBeCloseTo(0.75);
  });

  it("returns null for points that do not yet have a full window", () => {
    const days = [
      day({ day: "2026-08-01", total_tickets: 10, ai_first_count: 5 }),
      day({ day: "2026-08-02", total_tickets: 10, ai_first_count: 5 }),
    ];

    const rates = rollingRate(days, 7, numerator, denominator);

    expect(rates).toEqual([null, null]);
  });

  it("returns null when the window denominator is zero rather than dividing by zero", () => {
    const days = [
      day({ day: "2026-08-01", total_tickets: 0, ai_first_count: 0 }),
    ];

    const rates = rollingRate(days, 1, numerator, denominator);

    expect(rates).toEqual([null]);
  });
});

describe("rollDaysIntoWeeks", () => {
  it("groups a gapless run of days into full weeks by weekDefinition", () => {
    const days = [
      day({ day: "2026-07-20", total_tickets: 3 }), // Mon
      day({ day: "2026-07-21", total_tickets: 2 }), // Tue
      day({ day: "2026-07-27", total_tickets: 5 }), // next Mon
    ];

    const weeks = rollDaysIntoWeeks(days, "mon_sun");

    expect(weeks.map((w) => w.day)).toEqual(["2026-07-20", "2026-07-27"]);
    expect(weeks[0]?.total_tickets).toBe(5);
    expect(weeks[1]?.total_tickets).toBe(5);
  });

  it("groups correctly when the array has holes for missing weekend days", () => {
    // mon_sun week starting 2026-07-20 is missing Sat 25/07 and Sun 26/07 entirely.
    const days = [
      day({ day: "2026-07-20", total_tickets: 10 }),
      day({ day: "2026-07-24", total_tickets: 10 }),
      // gap: 25, 26 missing
      day({ day: "2026-07-27", total_tickets: 7 }), // next week's Monday
    ];

    const weeks = rollDaysIntoWeeks(days, "mon_sun");

    expect(weeks.map((w) => w.day)).toEqual(["2026-07-20", "2026-07-27"]);
    expect(weeks[0]?.total_tickets).toBe(20);
    expect(weeks[1]?.total_tickets).toBe(7);
  });

  it("keeps the sum of weeks equal to the sum of days", () => {
    const days = [
      day({ day: "2026-07-20", total_tickets: 3, ai_first_count: 1 }),
      day({ day: "2026-07-22", total_tickets: 4, ai_first_count: 2 }),
      day({ day: "2026-07-29", total_tickets: 6, ai_first_count: 3 }),
    ];

    const weeks = rollDaysIntoWeeks(days, "mon_sun");

    const totalDays = days.reduce((sum, d) => sum + d.total_tickets, 0);
    const totalWeeks = weeks.reduce((sum, w) => sum + w.total_tickets, 0);
    expect(totalWeeks).toBe(totalDays);
    const aiFirstDays = days.reduce((sum, d) => sum + d.ai_first_count, 0);
    const aiFirstWeeks = weeks.reduce((sum, w) => sum + w.ai_first_count, 0);
    expect(aiFirstWeeks).toBe(aiFirstDays);
  });

  it("sums resolved-first-reply and ai-first reply counts across days into weeks", () => {
    const days = [
      day({ day: "2026-07-20", resolved_first_reply_count: 2, ai_reply_sum_ai_first: 3 }),
      day({ day: "2026-07-21", resolved_first_reply_count: 1, ai_reply_sum_ai_first: 4 }),
      day({ day: "2026-07-27", resolved_first_reply_count: 5, ai_reply_sum_ai_first: 6 }),
    ];

    const weeks = rollDaysIntoWeeks(days, "mon_sun");

    expect(weeks[0]?.resolved_first_reply_count).toBe(3);
    expect(weeks[0]?.ai_reply_sum_ai_first).toBe(7);
    expect(weeks[1]?.resolved_first_reply_count).toBe(5);
    expect(weeks[1]?.ai_reply_sum_ai_first).toBe(6);
  });
});

describe("scopeSnapshotToDayRange", () => {
  it("builds a view whose totals match aggregateDays() for the same days", () => {
    const days = [
      day({
        day: "2026-08-03",
        total_tickets: 10,
        ai_first_count: 7,
        transferred_count: 3,
        direct_cs_count: 2,
        outcomes: { ai_end_to_end: 5, ai_then_cs: 3, direct_cs: 2, unclassified: 0 },
        reopen_lifetime_numerator: 2,
        reopen_lifetime_denominator: 10,
        gt4_turn_with_cs: 1,
        gt4_turn_without_cs: 1,
        resolved_first_reply_count: 4,
        ai_reply_sum_ai_first: 9,
      }),
      day({
        day: "2026-08-04",
        total_tickets: 5,
        ai_first_count: 3,
        transferred_count: 1,
        direct_cs_count: 1,
        outcomes: { ai_end_to_end: 3, ai_then_cs: 1, direct_cs: 1, unclassified: 0 },
        reopen_lifetime_numerator: 1,
        reopen_lifetime_denominator: 5,
      }),
    ];

    const view = scopeSnapshotToDayRange("mon_sun", days, "2026-08-03");

    expect(view.totals.eligible_ticket_count).toBe(15);
    expect(view.ai_first.count).toBe(10);
    expect(view.ai_first.rate).toBeCloseTo(10 / 15);
    expect(view.outcomes.ai_end_to_end).toBe(8);
    expect(view.reopen.lifetime.numerator).toBe(3);
    expect(view.reopen.lifetime.denominator).toBe(15);
    expect(view.rule_gt4.gt4_turn_with_cs).toBe(1);
    expect(view.rule_gt4.gt4_turn_without_cs).toBe(1);
  });

  it("produces exactly one synthetic weekly row covering the whole range, never wtd", () => {
    const days = [day({ day: "2026-08-03", total_tickets: 4, ai_first_count: 2 })];
    const view = scopeSnapshotToDayRange("mon_sun", days, "2026-08-03");

    expect(view.weekly).toHaveLength(1);
    const row = view.weekly[0] as WeeklyReportRow;
    expect(row.cohort_status).toBe("complete");
    expect(row.has_data).toBe(true);
    expect(row.cohort_week).toBe("2026-08-03");
    expect(Object.keys(view.by_week)).toEqual([row.cohort_week]);
  });

  it("carries no same-period, csat, or outcome-reconciliation comparison data", () => {
    const days = [day({ day: "2026-08-03", total_tickets: 1 })];
    const view = scopeSnapshotToDayRange("mon_sun", days, "2026-08-03");

    expect(view.same_period).toBeNull();
    expect(view.csat).toBeNull();
    expect(view.outcome_reconciliation).toBeNull();
  });

  it("satisfies DashboardViewSchema structurally aside from the day-sourced synthetic row", () => {
    const days = [
      day({ day: "2026-08-03", total_tickets: 4, ai_first_count: 2, transferred_count: 1, direct_cs_count: 1 }),
      day({ day: "2026-08-04", total_tickets: 2, ai_first_count: 1 }),
    ];
    const view = scopeSnapshotToDayRange("mon_sun", days, "2026-08-03");

    expect(() => DashboardViewSchema.parse(view)).not.toThrow();
  });

  it("returns segments limited to day-grain dimensions (skill/app/issue_category), others empty", () => {
    const days = [
      day({
        day: "2026-08-03",
        segments: {
          skill: { billing: { total: 2, ai_first: 1, transferred: 0, reopen: 0 } },
          app: {},
          issue_category: {},
        },
      }),
    ];
    const view = scopeSnapshotToDayRange("mon_sun", days, "2026-08-03");

    expect(view.segments.skill.billing?.total).toBe(2);
    expect(view.segments.product_code).toEqual({});
    expect(view.segments.intent).toEqual({});
    expect(view.segments.tpe).toEqual({});
    expect(view.segments.guardrail_rule).toEqual({});
    expect(view.segments.entry_point).toEqual({});
    expect(view.segments.model_core).toEqual({});
  });
});

describe("scopeSnapshotToDayRangeSnapshot", () => {
  const baseSnapshot = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture)
    .snapshot as DashboardSnapshot;

  it("replaces only the active weekDefinition's view with the day-range synthetic view", () => {
    const days = [day({ day: "2026-08-03", total_tickets: 4, ai_first_count: 2 })];
    const snapshot = scopeSnapshotToDayRangeSnapshot(
      baseSnapshot,
      "mon_sun",
      days,
      "2026-08-03",
    );
    expect(snapshot.views.mon_sun.totals.eligible_ticket_count).toBe(4);
    expect(snapshot.views.mon_fri).toBe(baseSnapshot.views.mon_fri);
  });

  it("keeps top-level snapshot fields (generated_at, source, coverage) from the real snapshot", () => {
    const days = [day({ day: "2026-08-03", total_tickets: 1, ai_first_count: 1 })];
    const snapshot = scopeSnapshotToDayRangeSnapshot(
      baseSnapshot,
      "mon_sun",
      days,
      "2026-08-03",
    );
    expect(snapshot.generated_at).toBe(baseSnapshot.generated_at);
    expect(snapshot.source).toBe(baseSnapshot.source);
    expect(snapshot.coverage).toBe(baseSnapshot.coverage);
  });
});
