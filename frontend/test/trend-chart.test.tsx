import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { dashboardEnvelopeFixture } from "./fixtures/dashboard";
import {
  DashboardEnvelopeSchema,
  type DashboardSnapshot,
  type DayAggregate,
  type WeeklyReportRow,
} from "../src/lib/dashboard-schema";
import { BelowFold } from "../src/components/BelowFold";

function dayAgg(overrides: Partial<DayAggregate> & { day: string }): DayAggregate {
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

describe("trend chart day mode", () => {
  // 6 lookback days (04-09) feeding the rolling window, then the plotted
  // range 08-10..08-11 -- mirrors useDayRangeAggregates()'s allDays/plottedDays split.
  const allDays: DayAggregate[] = [
    "2026-08-04",
    "2026-08-05",
    "2026-08-06",
    "2026-08-07",
    "2026-08-08",
    "2026-08-09",
    "2026-08-10",
    "2026-08-11",
  ].map((day) =>
    dayAgg({
      day,
      total_tickets: 10,
      ai_first_count: 7,
      reopen_lifetime_numerator: 2,
      reopen_lifetime_denominator: 10,
    }),
  );
  const plottedDays = allDays.slice(6);

  function renderDayMode(onDaySelect = vi.fn()) {
    const snapshot = snapshotWithWeeks([week("2026-07-06"), week("2026-07-13")]);
    return render(
      <BelowFold
        snapshot={snapshot}
        weekDefinition="mon_sun"
        activeWeek=""
        onWeekSelect={() => {}}
        onSegmentSelect={() => {}}
        activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
        onCsatBreakdownSelect={() => {}}
        onCsatBreakdownGroupingChange={() => {}}
        dayRange={{
          from: "2026-08-10",
          to: "2026-08-11",
          allDays,
          plottedDays,
          activeDay: "",
          onDaySelect,
        }}
      />,
    );
  }

  it("shows the mandatory two-line axis label with the exact required text", () => {
    renderDayMode();
    expect(
      screen.getByText("Xu hướng theo ngày · 10/08–11/08"),
    ).toBeVisible();
    expect(
      screen.getByText("Tỷ lệ là trung bình động 7 ngày"),
    ).toBeVisible();
  });

  it("plots only the selected range, not the lookback days", () => {
    renderDayMode();
    expect(
      document.querySelectorAll('[data-week-target="2026-08-10"]'),
    ).toHaveLength(2);
    expect(
      document.querySelectorAll('[data-week-target="2026-08-11"]'),
    ).toHaveLength(2);
    expect(
      document.querySelectorAll('[data-week-target="2026-08-04"]'),
    ).toHaveLength(0);
  });

  it("uses DD/MM axis labels with no year", () => {
    renderDayMode();
    const labels = screen.getAllByText("10/08");
    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) {
      expect(label).toBeVisible();
    }
  });

  it("clicking a day bar selects that day, not a week", () => {
    const onDaySelect = vi.fn();
    renderDayMode(onDaySelect);
    const target = document.querySelector('[data-week-target="2026-08-10"]');
    fireEvent.click(target as Element);
    expect(onDaySelect).toHaveBeenCalledWith("2026-08-10");
  });

  it("preserves id=\"trendChart\" on the volume chart svg", () => {
    renderDayMode();
    expect(document.getElementById("trendChart")).not.toBeNull();
  });
});

describe("transfer diagnostics day mode note", () => {
  const allDays: DayAggregate[] = ["2026-08-10", "2026-08-11"].map((day) =>
    dayAgg({ day, total_tickets: 5, ai_first_count: 3 }),
  );

  function renderWithWeeklySnapshot() {
    const latestComplete = week("2026-08-03", {
      cohort_status: "complete",
      has_data: true,
    });
    const weeklySnapshot = snapshotWithWeeks([latestComplete]);
    const daySnapshot = snapshotWithWeeks([latestComplete]);
    return render(
      <BelowFold
        snapshot={daySnapshot}
        weeklySnapshot={weeklySnapshot}
        weekDefinition="mon_sun"
        activeWeek=""
        onWeekSelect={() => {}}
        onSegmentSelect={() => {}}
        activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
        onCsatBreakdownSelect={() => {}}
        onCsatBreakdownGroupingChange={() => {}}
        dayRange={{
          from: "2026-08-10",
          to: "2026-08-11",
          allDays,
          plottedDays: allDays,
          activeDay: "",
          onDaySelect: () => {},
        }}
      />,
    );
  }

  it("shows a note that transfer diagnostics read by full week, not the selected day range", () => {
    renderWithWeeklySnapshot();
    expect(
      screen.getByText(
        "Chẩn đoán chuyển CS và TPE tính theo tuần trọn vẹn (03/08–09/08), không theo khoảng ngày đã chọn.",
      ),
    ).toBeVisible();
  });
});
