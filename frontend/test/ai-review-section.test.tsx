import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AiReviewBreakdownTable } from "../src/components/AiReviewBreakdownTable";
import { CsatSection } from "../src/components/CsatSection";
import type { AiReview, AiReviewBucket } from "../src/lib/dashboard-schema";

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

describe("AiReviewBreakdownTable", () => {
  it('shows "—" for the rate but the real count when the row is under the sample minimum', () => {
    const data = aiReviewBucket({
      reviewed_ticket_count: 3,
      rated_ticket_count: 3,
      satisfied_count: 3,
      by_dimension: {
        skill: [{ value: "interbank-fund-transfer", ...emptyAiCounts, reviewed_ticket_count: 3, rated_ticket_count: 3, satisfied_count: 3 }],
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
    // The row's own count cell always shows the true count, n<20 or not.
    expect(screen.getByRole("button", { name: /interbank-fund-transfer/ })).toBeVisible();
    const row = screen.getByRole("button", { name: /interbank-fund-transfer/ }).closest("tr");
    expect(row).not.toBeNull();
    expect(row!.textContent).toContain("3");
    // Every rate cell in that row is a dash with an explanatory tooltip, not a number.
    const dashes = row!.querySelectorAll('td span[title]');
    expect(dashes.length).toBeGreaterThan(0);
    for (const dash of dashes) {
      expect(dash.textContent).toBe("—");
      expect(dash.getAttribute("title")).toMatch(/Mẫu dưới 20 ticket/);
    }
  });

  it("shows a normal computed rate at the n=20 boundary (no dash)", () => {
    const data = aiReviewBucket({
      reviewed_ticket_count: 20,
      rated_ticket_count: 20,
      satisfied_count: 20,
      by_dimension: {
        skill: [{ value: "interbank-fund-transfer", ...emptyAiCounts, reviewed_ticket_count: 20, rated_ticket_count: 20, satisfied_count: 20 }],
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
    // 20/20 satisfied is an exact, counted 100% (no decimal noise) -- and no
    // dash cell anywhere in the row, since n=20 clears PERCENTAGE_SAMPLE_MINIMUM.
    expect(row!.textContent).toContain("100%");
    expect(row!.querySelectorAll('td span[title]').length).toBe(0);
  });
});

const baseProps = {
  effectiveWeek: "2026-08-31",
  weekDefinition: "mon_sun" as const,
  activeBreakdownFilters: { outcome: "", skill: "", issue_category: "", app: "" },
  onBreakdownSelect: () => {},
  onBreakdownRowSelect: () => {},
  onBreakdownGroupingChange: () => {},
};

describe("CsatSection — CS hậu kiểm empty states", () => {
  it("shows the cookie-broken sentence when the Freshdesk cookie is expired", () => {
    render(
      <CsatSection
        {...baseProps}
        csat={null}
        aiReview={null}
        freshdeskCookieState="expired"
      />,
    );
    expect(
      screen.getByText("Cookie Freshdesk đã hết hạn — hậu kiểm đã dừng cập nhật."),
    ).toBeVisible();
  });

  it("shows the job-never-run sentence when the cookie is fine but ai_review is null", () => {
    render(
      <CsatSection
        {...baseProps}
        csat={null}
        aiReview={null}
        freshdeskCookieState="ok"
      />,
    );
    expect(
      screen.getByText("Chưa chạy job hậu kiểm lần nào — chưa có dữ liệu CS hậu kiểm."),
    ).toBeVisible();
    // No cookie-connect button once the cookie is already fine.
    expect(screen.queryByRole("button", { name: "Kết nối Freshdesk" })).toBeNull();
  });

  it("shows the zero-tickets-in-scope sentence when ai_review fetched but this week has none", () => {
    const aiReview: AiReview = {
      source: "freshdesk",
      fetched_at: "2026-08-31T03:00:00Z",
      by_week: { "2026-08-31": aiReviewBucket() },
      by_day: {},
    };
    render(
      <CsatSection
        {...baseProps}
        csat={null}
        aiReview={aiReview}
        freshdeskCookieState="ok"
      />,
    );
    expect(
      screen.getByText("Không có ticket nào vào diện hậu kiểm trong tuần này."),
    ).toBeVisible();
  });

  it("renders no hậu kiểm block and does not throw when ai_review is null", () => {
    expect(() =>
      render(
        <CsatSection
          {...baseProps}
          csat={null}
          aiReview={null}
          freshdeskCookieState="ok"
        />,
      ),
    ).not.toThrow();
    expect(screen.queryByRole("table", { name: /Skill/ })).toBeNull();
    expect(screen.queryByText(/Hậu kiểm: Freshdesk/)).toBeNull();
  });
});
