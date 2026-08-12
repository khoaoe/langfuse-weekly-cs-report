import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { dashboardEnvelopeFixture } from "./fixtures/dashboard";
import {
  DashboardEnvelopeSchema,
  type DashboardSnapshot,
  type WeeklyReportRow,
} from "../src/lib/dashboard-schema";
import { BelowFold } from "../src/components/BelowFold";

const baseSnapshot = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture)
  .snapshot as DashboardSnapshot;
const template = baseSnapshot.views.mon_sun.weekly[0] as WeeklyReportRow;

function week(
  cohortWeek: string,
  overrides: Partial<WeeklyReportRow> = {},
): WeeklyReportRow {
  return {
    ...template,
    cohort_week: cohortWeek,
    cohort_status: "complete",
    has_data: true,
    ...overrides,
  };
}

function snapshotWithWeeks(weekly: readonly WeeklyReportRow[]): DashboardSnapshot {
  const byWeekDetail = baseSnapshot.views.mon_sun.by_week["2026-07-20"]!;
  return {
    ...baseSnapshot,
    views: {
      ...baseSnapshot.views,
      mon_sun: {
        ...baseSnapshot.views.mon_sun,
        weekly: [...weekly],
        by_week: Object.fromEntries(
          weekly.map((row) => [row.cohort_week, byWeekDetail]),
        ),
      },
    },
  };
}

function snapshotWithSamePeriodTrend(): DashboardSnapshot {
  const fullWeeks = [
    week("2026-07-06", {
      total_tickets: 30,
      ai_first_count: 21,
      ai_first_rate: 0.7,
    }),
    week("2026-07-13", {
      total_tickets: 20,
      ai_first_count: 16,
      ai_first_rate: 0.8,
    }),
    week("2026-07-20", {
      cohort_status: "wtd",
      total_tickets: 10,
      ai_first_count: 8,
      ai_first_rate: 0.8,
    }),
  ];
  const snapshot = snapshotWithWeeks(fullWeeks);
  const samePeriod = {
    cutoff_date: "2026-07-23",
    cutoff_weekday: 4,
    current: {
      cohort_week: "2026-07-20",
      total_tickets: 4,
      ai_first_count: 3,
      ai_first_rate: 0.75,
      reopen_lifetime_rate: 0.25,
      reopen_lifetime_numerator: 1,
      reopen_lifetime_denominator: 4,
    },
    baseline: {
      weeks_used: 2,
      ai_first_rate: 0.7,
      reopen_lifetime_rate: 0.2,
    },
    by_week: {
      "2026-07-06": {
        cohort_week: "2026-07-06",
        total_tickets: 10,
        ai_first_count: 7,
        ai_first_rate: 0.7,
        reopen_lifetime_rate: 0.2,
        reopen_lifetime_numerator: 1,
        reopen_lifetime_denominator: 5,
      },
      "2026-07-13": {
        cohort_week: "2026-07-13",
        total_tickets: 10,
        ai_first_count: 7,
        ai_first_rate: 0.7,
        reopen_lifetime_rate: 0.2,
        reopen_lifetime_numerator: 1,
        reopen_lifetime_denominator: 5,
      },
      "2026-07-20": {
        cohort_week: "2026-07-20",
        total_tickets: 4,
        ai_first_count: 3,
        ai_first_rate: 0.75,
        reopen_lifetime_rate: 0.25,
        reopen_lifetime_numerator: 1,
        reopen_lifetime_denominator: 4,
      },
    },
  } as const;
  const monFriWeeks = fullWeeks.map((row) => ({
    ...row,
    week_definition: "mon_fri" as const,
  }));
  const monFriDetail = baseSnapshot.views.mon_fri.by_week["2026-07-20"]!;
  return {
    ...snapshot,
    views: {
      ...snapshot.views,
      mon_sun: {
        ...snapshot.views.mon_sun,
        same_period: samePeriod,
      },
      mon_fri: {
        ...snapshot.views.mon_fri,
        weekly: monFriWeeks,
        by_week: Object.fromEntries(
          monFriWeeks.map((row) => [row.cohort_week, monFriDetail]),
        ),
        same_period: samePeriod,
      },
    },
  };
}

describe("trend chart data gaps", () => {
  it("shows one accessible tooltip for chart hover", () => {
    const onWeekSelect = vi.fn();
    const snapshot = snapshotWithWeeks([
      week("2026-07-06", {
        total_tickets: 30,
        ai_first_count: 21,
        ai_first_rate: 0.7,
        reopen_lifetime_rate: 0.25,
      }),
      week("2026-07-13", {
        total_tickets: 20,
        ai_first_count: 16,
        ai_first_rate: 0.8,
        reopen_lifetime_rate: 0.2,
      }),
    ]);

    render(
      <BelowFold
        snapshot={snapshot}
        weekDefinition="mon_sun"
        activeWeek=""
        onWeekSelect={onWeekSelect}
        onSegmentSelect={() => {}}
        activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
        onCsatBreakdownSelect={() => {}}
        onCsatBreakdownGroupingChange={() => {}}
      />,
    );

    const targets = document.querySelectorAll(
      '[data-week-target="2026-07-06"]',
    );
    expect(targets).toHaveLength(2);

    fireEvent.pointerEnter(targets[0] as Element, { clientX: 120 });
    const volumeTooltip = screen.getByRole("tooltip");
    expect(volumeTooltip).toHaveTextContent("Tuần 06/07–12/07");
    expect(volumeTooltip).toHaveTextContent("Tổng 30 ticket");
    expect(volumeTooltip).toHaveTextContent("AI First 21 ticket");
    expect(volumeTooltip.tagName).toBe("DIV");
    expect(volumeTooltip.querySelector("title")).toBeNull();

    fireEvent.click(targets[0] as Element);
    expect(onWeekSelect).toHaveBeenCalledWith("2026-07-06");
    fireEvent.pointerLeave(targets[0] as Element);
    expect(screen.queryByRole("tooltip")).toBeNull();

    fireEvent.pointerEnter(targets[1] as Element, { clientX: 120 });
    const rateTooltip = screen.getByRole("tooltip");
    expect(rateTooltip).toHaveTextContent("AI First 70,0%");
    expect(rateTooltip).toHaveTextContent("Reopen sau AI First 25,0%");
    fireEvent.pointerLeave(targets[1] as Element);

    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it.each([
    { clientX: 5, edge: "left", transform: "translateX(0)" },
    { clientX: 385, edge: "right", transform: "translateX(-100%)" },
  ])("flips the tooltip inward at the $edge viewport edge", ({
    clientX,
    transform,
  }) => {
    const snapshot = snapshotWithWeeks([
      week("2026-07-06", {
        total_tickets: 30,
        ai_first_count: 21,
      }),
      week("2026-07-13", {
        total_tickets: 20,
        ai_first_count: 16,
      }),
    ]);

    render(
      <BelowFold
        snapshot={snapshot}
        weekDefinition="mon_sun"
        activeWeek=""
        onWeekSelect={() => {}}
        onSegmentSelect={() => {}}
        activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
        onCsatBreakdownSelect={() => {}}
        onCsatBreakdownGroupingChange={() => {}}
      />,
    );

    const volumeChart = screen.getByRole("img", {
      name: "Volume ticket theo tuần",
    });
    vi.spyOn(volumeChart, "getBoundingClientRect").mockReturnValue({
      bottom: 300,
      height: 300,
      left: 0,
      right: 390,
      top: 0,
      width: 390,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });

    const target = document.querySelector(
      '[data-week-target="2026-07-06"]',
    );
    expect(target).not.toBeNull();
    fireEvent.pointerEnter(target as Element, { clientX });

    expect(screen.getByRole("tooltip")).toHaveStyle({
      transform,
    });
  });

  it("does not connect rate lines across a week without data", () => {
    const snapshot = snapshotWithWeeks([
      week("2026-06-29"),
      week("2026-07-06"),
      week("2026-07-13", {
        has_data: false,
        total_tickets: 0,
        ai_first_count: 0,
      }),
      week("2026-07-20"),
      week("2026-07-27"),
    ]);

    render(
      <BelowFold
        snapshot={snapshot}
        weekDefinition="mon_sun"
        activeWeek=""
        onWeekSelect={() => {}}
        onSegmentSelect={() => {}}
        activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
        onCsatBreakdownSelect={() => {}}
        onCsatBreakdownGroupingChange={() => {}}
      />,
    );

    const rateChart = screen.getByRole("img", {
      name: /Tỷ lệ AI First và reopen theo tuần/,
    });

    const paths = [...rateChart.querySelectorAll("path")];
    expect(paths).toHaveLength(2);
    // Visx may encode the two observed runs as subpaths in one SVG path. Each
    // series therefore needs two move commands, one on either side of the gap.
    for (const path of paths) {
      expect(path.getAttribute("d")?.match(/M/g)).toHaveLength(2);
    }
  });

  it("gaps only the reopen series when its mature rate is unavailable", () => {
    const snapshot = snapshotWithWeeks([
      week("2026-06-29"),
      week("2026-07-06"),
      week("2026-07-13", { reopen_lifetime_rate: null }),
      week("2026-07-20"),
      week("2026-07-27"),
    ]);

    render(
      <BelowFold
        snapshot={snapshot}
        weekDefinition="mon_sun"
        activeWeek=""
        onWeekSelect={() => {}}
        onSegmentSelect={() => {}}
        activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
        onCsatBreakdownSelect={() => {}}
        onCsatBreakdownGroupingChange={() => {}}
      />,
    );

    const rateChart = screen.getByRole("img", {
      name: /Tỷ lệ AI First và reopen theo tuần/,
    });
    const paths = [...rateChart.querySelectorAll("path")];

    expect(paths[0]?.getAttribute("d")?.match(/M/g)).toHaveLength(1);
    expect(paths[1]?.getAttribute("d")?.match(/M/g)).toHaveLength(2);
  });

  it("shows the same-period toggle only when the active view has comparison data", async () => {
    const user = userEvent.setup();
    const snapshot = snapshotWithSamePeriodTrend();
    const { rerender } = render(
      <BelowFold
        snapshot={snapshot}
        weekDefinition="mon_sun"
        activeWeek=""
        onWeekSelect={() => {}}
        onSegmentSelect={() => {}}
        activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
        onCsatBreakdownSelect={() => {}}
        onCsatBreakdownGroupingChange={() => {}}
      />,
    );

    expect(screen.getByRole("button", { name: "Tuần đủ" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "Cùng kỳ đến T5" }));
    expect(screen.getByRole("button", { name: "Cùng kỳ đến T5" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.getByText("Mọi tuần đều cắt tới thứ Năm để so cùng kỳ."),
    ).toBeVisible();
    expect(
      screen.getByText(/Tuần gần nhất có dữ liệu 20\/07–26\/07: 4 ticket/),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Tuần gần nhất có dữ liệu: AI First 75,0%, reopen 25,0%.",
      ),
    ).toBeVisible();

    rerender(
      <BelowFold
        snapshot={{
          ...snapshot,
          views: {
            ...snapshot.views,
            mon_sun: { ...snapshot.views.mon_sun, same_period: null },
          },
        }}
        weekDefinition="mon_sun"
        activeWeek=""
        onWeekSelect={() => {}}
        onSegmentSelect={() => {}}
        activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
        onCsatBreakdownSelect={() => {}}
        onCsatBreakdownGroupingChange={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: "Cùng kỳ đến T5" })).toBeNull();
  });

  it("resets the comparison mode when the week definition changes", async () => {
    const user = userEvent.setup();
    const snapshot = snapshotWithSamePeriodTrend();
    const { rerender } = render(
      <BelowFold
        snapshot={snapshot}
        weekDefinition="mon_sun"
        activeWeek=""
        onWeekSelect={() => {}}
        onSegmentSelect={() => {}}
        activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
        onCsatBreakdownSelect={() => {}}
        onCsatBreakdownGroupingChange={() => {}}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Cùng kỳ đến T5" }));
    expect(screen.getByRole("button", { name: "Cùng kỳ đến T5" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    rerender(
      <BelowFold
        snapshot={snapshot}
        weekDefinition="mon_fri"
        activeWeek=""
        onWeekSelect={() => {}}
        onSegmentSelect={() => {}}
        activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
        onCsatBreakdownSelect={() => {}}
        onCsatBreakdownGroupingChange={() => {}}
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Tuần đủ" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(
      screen.queryByText("Mọi tuần đều cắt tới thứ Năm để so cùng kỳ."),
    ).toBeNull();
  });
});
