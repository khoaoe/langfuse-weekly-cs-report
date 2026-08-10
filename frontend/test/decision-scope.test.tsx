import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { dashboardEnvelopeFixture } from "./fixtures/dashboard";
import {
  DashboardEnvelopeSchema,
  type DashboardSnapshot,
  type WeeklyReportRow,
} from "../src/lib/dashboard-schema";
import { DecisionLedger } from "../src/components/DecisionLedger";
import {
  buildNarrativeInput,
  isObservedWeek,
  selectAttentionItems,
  selectLedger,
  selectScope,
  selectWeakestCoverage,
} from "../src/lib/selectors";

const baseSnapshot = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture)
  .snapshot as DashboardSnapshot;
const latest = baseSnapshot.views.mon_sun.weekly[0] as WeeklyReportRow;
const selected: WeeklyReportRow = {
  ...latest,
  cohort_week: "2026-07-13",
  total_tickets: 4,
  ai_first_count: 2,
  ai_first_rate: 0.5,
  ai_end_to_end_count: 1,
  ai_then_cs_count: 1,
  direct_cs_count: 1,
  reopen_lifetime_numerator: 0,
  reopen_lifetime_denominator: 2,
  reopen_lifetime_rate: 0,
  gt4_turn_without_cs: 0,
};
const snapshot: DashboardSnapshot = {
  ...baseSnapshot,
  views: {
    ...baseSnapshot.views,
    mon_sun: {
      ...baseSnapshot.views.mon_sun,
      weekly: [selected, latest],
    },
  },
};

describe("selected-week decision scope", () => {
  it("identifies a selected week that must be cleared after snapshot rollover", () => {
    expect(
      isObservedWeek(snapshot.views.mon_sun, "2026-07-13"),
    ).toBe(true);
    expect(
      isObservedWeek(snapshot.views.mon_sun, "2026-06-29"),
    ).toBe(false);
  });

  it("uses the chart-selected week for the title, ledger, narrative and warning", () => {
    expect(selectScope(snapshot, "mon_sun", "2026-07-13")).toMatchObject({
      eligible: 4,
      aiFirstCount: 2,
      gt4WithoutCs: 0,
      week: { cohort_week: "2026-07-13" },
    });
    expect(
      buildNarrativeInput(snapshot, "mon_sun", "2026-07-13").current.aiFirst,
    ).toEqual({ count: 2, rate: 0.5 });
    expect(
      selectAttentionItems(snapshot, "mon_sun", "2026-07-13").map(
        (item) => item.id,
      ),
    ).not.toContain("attention-gt4");

    render(
      <DecisionLedger
        snapshot={snapshot}
        weekDefinition="mon_sun"
        activeWeek="2026-07-13"
      />,
    );

    expect(
      screen.getByRole("heading", { level: 1, name: /13\/07–19\/07.*4 ticket/ }),
    ).toBeVisible();
    expect(screen.getByRole("group", { name: "Tóm tắt quyết định" })).toBeVisible();
    expect(document.getElementById("ledger-ai-first")).toHaveTextContent(
      "250,0% trong 4 ticket tuần này",
    );
    expect(
      screen.queryByText(/ticket có hơn 3 lượt xử lý nhưng chưa chuyển CS/),
    ).toBeNull();
  });

  it("uses the same-period block from the selected cohort view", () => {
    const runningSun = {
      ...latest,
      cohort_status: "wtd" as const,
    };
    const runningFri = {
      ...baseSnapshot.views.mon_fri.weekly[0]!,
      cohort_status: "wtd" as const,
    };
    const comparisonSnapshot: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        mon_sun: {
          ...baseSnapshot.views.mon_sun,
          weekly: [runningSun],
          same_period: {
            cutoff_date: "2026-07-23",
            cutoff_weekday: 4,
            current: {
              cohort_week: runningSun.cohort_week,
              total_tickets: 10,
              ai_first_count: 5,
              ai_first_rate: 0.5,
              reopen_lifetime_rate: 0.2,
              reopen_lifetime_numerator: 1,
              reopen_lifetime_denominator: 5,
            },
            baseline: {
              weeks_used: 4,
              ai_first_rate: 0.6,
              reopen_lifetime_rate: 0.25,
            },
            by_week: {},
          },
        },
        mon_fri: {
          ...baseSnapshot.views.mon_fri,
          weekly: [runningFri],
          same_period: {
            cutoff_date: "2026-07-23",
            cutoff_weekday: 4,
            current: {
              cohort_week: runningFri.cohort_week,
              total_tickets: 5,
              ai_first_count: 2,
              ai_first_rate: 0.4,
              reopen_lifetime_rate: 0.5,
              reopen_lifetime_numerator: 1,
              reopen_lifetime_denominator: 2,
            },
            baseline: {
              weeks_used: 2,
              ai_first_rate: 0.3,
              reopen_lifetime_rate: 0.4,
            },
            by_week: {},
          },
        },
      },
    };

    expect(buildNarrativeInput(comparisonSnapshot, "mon_sun")).toMatchObject({
      current: { aiFirst: { count: 5, rate: 0.5 }, reopenRate: 0.2 },
      samePeriod: { weeksUsed: 4, aiFirstRate: 0.6, reopenRate: 0.25 },
    });
    expect(buildNarrativeInput(comparisonSnapshot, "mon_fri")).toMatchObject({
      current: { aiFirst: { count: 2, rate: 0.4 }, reopenRate: 0.5 },
      samePeriod: { weeksUsed: 2, aiFirstRate: 0.3, reopenRate: 0.4 },
    });
  });

  it("keeps partial-enrichment context in the narrative without a separate alert card", () => {
    const partial: DashboardSnapshot = {
      ...baseSnapshot,
      enrichment_status: "partial",
    };

    render(
      <DecisionLedger snapshot={partial} weekDefinition="mon_sun" />,
    );

    expect(
      screen.getByText(
        "Lần đọc này chưa lấy đủ dữ liệu phụ từ Langfuse, nên Intent, Skill, Transstatus và Step result còn thiếu.",
      ),
    ).toBeVisible();
    expect(screen.queryByText(/Chờ lần làm mới kế tiếp/)).toBeNull();
    expect(screen.queryByText(/Cần lưu ý/i)).toBeNull();
  });

  it("names the single weakest coverage dimension instead of a blended score", () => {
    // A 78/100 aggregate hides which dimension is actually short and what
    // it costs. Naming the weakest one — Category 50%, tpe 50%, skill 50%
    // tied in this fixture, first-in-schema-order wins deterministically —
    // tells the reader something they can act on.
    const weak: DashboardSnapshot = {
      ...baseSnapshot,
      coverage: {
        ...baseSnapshot.coverage,
        issue_category: 0.5,
        tpe: 0.5,
        skill: 0.5,
      },
    };
    expect(selectWeakestCoverage(weak)).toEqual({
      name: "issue_category",
      label: "Category",
      missingShare: 0.5,
    });
  });

  it("reports no weak dimension once every coverage stat clears the floor", () => {
    const healthy: DashboardSnapshot = {
      ...baseSnapshot,
      coverage: {
        issue_category: 0.9,
        app: 0.8,
        tpe: 0.85,
        intent: 0.82,
        skill: 0.8,
      },
    };
    expect(selectWeakestCoverage(healthy)).toBeNull();
  });

  it("drops the share line on a count cell that measured nothing", () => {
    const zeroed: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        ...baseSnapshot.views,
        mon_sun: {
          ...baseSnapshot.views.mon_sun,
          weekly: [
            { ...latest, gt4_turn_without_cs: 0, gt4_turn_with_cs: 0 },
            ...baseSnapshot.views.mon_sun.weekly.slice(1),
          ],
        },
      },
    };

    const cells = selectLedger(zeroed, "mon_sun");
    const gt4 = cells.find((cell) => cell.id === "ledger-gt4");

    // "0 · 0% ticket trong tuần" spends a line restating the zero above it.
    expect(gt4?.value).toBe("0");
    expect(gt4?.support).toBeNull();
  });

  it("uses a count as the primary value in every KPI cell", () => {
    const reportingWeek: WeeklyReportRow = {
      ...latest,
      total_tickets: 935,
      ai_first_count: 727,
      ai_first_rate: 727 / 935,
      ai_then_cs_count: 180,
      direct_cs_count: 28,
      reopen_lifetime_numerator: 152,
      reopen_lifetime_denominator: 727,
      reopen_lifetime_rate: 152 / 727,
      gt4_turn_without_cs: 0,
    };
    const reportingSnapshot: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        ...baseSnapshot.views,
        mon_sun: {
          ...baseSnapshot.views.mon_sun,
          weekly: [reportingWeek],
        },
      },
    };

    expect(selectLedger(reportingSnapshot, "mon_sun")).toMatchObject([
      {
        id: "ledger-ai-first",
        value: "727",
        support: "77,8% trong 935 ticket tuần này",
      },
      {
        id: "ledger-transfer",
        value: "208",
        support: "22,2% trong 935 ticket tuần này",
      },
      {
        id: "ledger-reopen",
        value: "152",
        support: "20,9% trong 727 ticket AI First",
      },
      { id: "ledger-gt4", value: "0", support: null },
    ]);
  });

  it("renders critical rail items with a direct ticket filter", () => {
    const onCellSelect = vi.fn();
    render(
      <DecisionLedger
        snapshot={baseSnapshot}
        weekDefinition="mon_sun"
        onCellSelect={onCellSelect}
      />,
    );

    const rail = screen.getByRole("list", {
      name: "Cần xem trong phạm vi này",
    });
    expect(within(rail).queryByText("Cần xử lý")).toBeNull();
    expect(
      within(rail).getByText(/ticket có hơn 3 lượt xử lý mà chưa chuyển CS/),
    ).toBeVisible();
    fireEvent.click(within(rail).getByRole("button", { name: "Xem ticket" }));
    expect(onCellSelect).toHaveBeenCalledWith({
      gt4_turn: "true",
      transferred: "false",
    });
  });
});
