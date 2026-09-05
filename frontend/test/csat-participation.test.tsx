import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CsatCharts } from "../src/components/CsatCharts";
import type { CsatWeek } from "../src/lib/dashboard-schema";

const emptyCounts = { ticket_count: 0, positive: 0, neutral: 0, negative: 0 };

/** 40 rated tickets: the participation numerator. Declared, not measured. */
const week: CsatWeek = {
  response_count: 44,
  ticket_count: 40,
  positive: 30,
  neutral: 6,
  negative: 4,
  by_outcome: {
    ai_end_to_end: emptyCounts,
    ai_then_cs: emptyCounts,
    direct_cs: emptyCounts,
    unclassified: emptyCounts,
  },
  by_dimension: { skill: [], issue_category: [] },
  feedback_entries: [],
} as unknown as CsatWeek;

const renderCharts = (scopeTickets: number | null) =>
  render(
    <CsatCharts
      data={week}
      buckets={[["2026-08-31", week]]}
      grouping="outcome"
      dayGrain={false}
      weekDefinition="mon_sun"
      scopeTickets={scopeTickets}
    />,
  );

describe("CSAT participation share", () => {
  it("states how much of the scope answered, next to the raw counts", () => {
    renderCharts(200);
    // 40 rated out of 200 tickets in scope.
    expect(
      screen.getByText(/40 ticket · 20,0% ticket trong phạm vi có đánh giá/),
    ).toBeVisible();
  });

  it("prints only the counts when no denominator is available", () => {
    renderCharts(null);
    expect(screen.getByText(/44 phản hồi từ 40 ticket$/)).toBeVisible();
  });

  it("drops the share when the two sources disagree about the population", () => {
    // Fewer tickets in scope than tickets that answered: the share would read
    // above 100%. Silence beats a number that cannot be true.
    renderCharts(30);
    expect(screen.queryByText(/trong phạm vi có đánh giá/)).toBeNull();
  });
});
