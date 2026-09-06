import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CsatBreakdownTable } from "../src/components/CsatBreakdownTable";
import { AiReviewBreakdownTable } from "../src/components/AiReviewBreakdownTable";
import type { AiReviewBucket, CsatWeek } from "../src/lib/dashboard-schema";

const emptyCsatCounts = { ticket_count: 0, positive: 0, neutral: 0, negative: 0 };

function csatWeek(overrides: Partial<CsatWeek> = {}): CsatWeek {
  return {
    ticket_count: 0,
    response_count: 0,
    positive: 0,
    neutral: 0,
    negative: 0,
    by_outcome: {
      ai_end_to_end: emptyCsatCounts,
      ai_then_cs: emptyCsatCounts,
      direct_cs: emptyCsatCounts,
      unclassified: emptyCsatCounts,
    },
    by_dimension: { skill: [], issue_category: [], app: [] },
    feedback_entries: [],
    ...overrides,
  } as unknown as CsatWeek;
}

const emptyAiCounts = {
  reviewed_ticket_count: 0,
  rated_ticket_count: 0,
  satisfied_count: 0,
  satisfied_with_edit_count: 0,
  needs_edit_count: 0,
};

function aiReviewBucket(overrides: Partial<AiReviewBucket> = {}): AiReviewBucket {
  return {
    ...emptyAiCounts,
    by_outcome: {
      ai_end_to_end: emptyAiCounts,
      ai_then_cs: emptyAiCounts,
      direct_cs: emptyAiCounts,
      unclassified: emptyAiCounts,
    },
    by_dimension: { skill: [], issue_category: [], app: [] },
    by_review_count: [],
    ...overrides,
  };
}

describe("CsatBreakdownTable — bar-in-table (no ranking-panel duplicate)", () => {
  it("renders each group exactly once (bar and cells share the same row, no panel duplicate)", () => {
    const data = csatWeek({
      ticket_count: 25,
      response_count: 25,
      positive: 15,
      neutral: 5,
      negative: 5,
      by_dimension: {
        skill: [
          { value: "interbank-fund-transfer", ...emptyCsatCounts, ticket_count: 25, positive: 15, neutral: 5, negative: 5 },
        ],
        issue_category: [],
        app: [],
      },
    });
    render(
      <CsatBreakdownTable data={data} grouping="skill" scopeKey="2026-08-31" onValueSelect={() => {}} />,
    );
    expect(
      screen.getAllByRole("button", { name: /interbank-fund-transfer/ }),
    ).toHaveLength(1);
  });

  it("the rate bar's aria-label carries all three bucket labels with count and share", () => {
    const data = csatWeek({
      ticket_count: 25,
      response_count: 25,
      positive: 15,
      neutral: 5,
      negative: 5,
      by_dimension: {
        skill: [
          { value: "interbank-fund-transfer", ...emptyCsatCounts, ticket_count: 25, positive: 15, neutral: 5, negative: 5 },
        ],
        issue_category: [],
        app: [],
      },
    });
    render(
      <CsatBreakdownTable data={data} grouping="skill" scopeKey="2026-08-31" onValueSelect={() => {}} />,
    );
    const row = screen.getByRole("button", { name: /interbank-fund-transfer/ }).closest("tr");
    expect(row).not.toBeNull();
    const bar = within(row!).getByRole("img");
    const label = bar.getAttribute("aria-label") ?? "";
    expect(label).toMatch(/Rất hài lòng 15/);
    expect(label).toMatch(/Bình thường 5/);
    expect(label).toMatch(/Rất tệ 5/);
  });

  it('shows "—" for the rate cell under the sample minimum, real count elsewhere', () => {
    const data = csatWeek({
      ticket_count: 3,
      response_count: 3,
      positive: 3,
      by_dimension: {
        skill: [{ value: "interbank-fund-transfer", ...emptyCsatCounts, ticket_count: 3, positive: 3 }],
        issue_category: [],
        app: [],
      },
    });
    render(
      <CsatBreakdownTable data={data} grouping="skill" scopeKey="2026-08-31" onValueSelect={() => {}} />,
    );
    const row = screen.getByRole("button", { name: /interbank-fund-transfer/ }).closest("tr");
    expect(row).not.toBeNull();
    expect(row!.textContent).toContain("3");
    const dash = within(row!).getByText("—");
    expect(dash.getAttribute("title")).toMatch(/Mẫu dưới 20/);
  });
});

describe("AiReviewBreakdownTable — bar-in-table (no ranking-panel duplicate)", () => {
  it("renders each group exactly once", () => {
    const data = aiReviewBucket({
      reviewed_ticket_count: 25,
      rated_ticket_count: 25,
      satisfied_count: 15,
      satisfied_with_edit_count: 5,
      needs_edit_count: 5,
      by_dimension: {
        skill: [
          {
            value: "interbank-fund-transfer",
            ...emptyAiCounts,
            reviewed_ticket_count: 25,
            rated_ticket_count: 25,
            satisfied_count: 15,
            satisfied_with_edit_count: 5,
            needs_edit_count: 5,
          },
        ],
        issue_category: [],
        app: [],
      },
    });
    render(
      <AiReviewBreakdownTable
        data={data}
        grouping="skill"
        scopeKey="2026-08-31"
        onValueSelect={() => {}}
        groupingLabel="Skill"
      />,
    );
    expect(
      screen.getAllByRole("button", { name: /interbank-fund-transfer/ }),
    ).toHaveLength(1);
  });

  it("the rate bar's aria-label carries all three bucket labels with count", () => {
    const data = aiReviewBucket({
      reviewed_ticket_count: 25,
      rated_ticket_count: 25,
      satisfied_count: 15,
      satisfied_with_edit_count: 5,
      needs_edit_count: 5,
      by_dimension: {
        skill: [
          {
            value: "interbank-fund-transfer",
            ...emptyAiCounts,
            reviewed_ticket_count: 25,
            rated_ticket_count: 25,
            satisfied_count: 15,
            satisfied_with_edit_count: 5,
            needs_edit_count: 5,
          },
        ],
        issue_category: [],
        app: [],
      },
    });
    render(
      <AiReviewBreakdownTable
        data={data}
        grouping="skill"
        scopeKey="2026-08-31"
        onValueSelect={() => {}}
        groupingLabel="Skill"
      />,
    );
    const row = screen.getByRole("button", { name: /interbank-fund-transfer/ }).closest("tr");
    expect(row).not.toBeNull();
    const bar = within(row!).getByRole("img");
    const label = bar.getAttribute("aria-label") ?? "";
    expect(label).toMatch(/Đạt 15/);
    expect(label).toMatch(/Đạt, có sửa 5/);
    expect(label).toMatch(/Cần sửa 5/);
  });
});
