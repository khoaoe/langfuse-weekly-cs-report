import { describe, expect, it } from "vitest";

import type { AiReviewBucket, CsatWeek } from "../src/lib/dashboard-schema";
import { rowsFor as csatRowsFor } from "../src/components/CsatBreakdownTable";
import { aiReviewRowsFor } from "../src/components/AiReviewBreakdownTable";

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
    feedback: [],
    ...overrides,
  } as unknown as CsatWeek;
}

const emptyAiCounts = {
  reviewed_ticket_count: 0,
  rated_ticket_count: 0,
  evaluated_ticket_count: 0,
  unrated_reviewed_ticket_count: 0,
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
  } as unknown as AiReviewBucket;
}

describe("CSAT rowsFor sort order", () => {
  it("puts small-sample groups last, then worst-rate-first among the rest", () => {
    const data = csatWeek({
      by_dimension: {
        skill: [
          // Big sample, moderate rate.
          { value: "skill-a", ...emptyCsatCounts, ticket_count: 30, negative: 6 },
          // Big sample, worst rate -- should sort first.
          { value: "skill-b", ...emptyCsatCounts, ticket_count: 25, negative: 15 },
          // Below PERCENTAGE_SAMPLE_MINIMUM (20) -- should sort last regardless of rate.
          { value: "skill-c", ...emptyCsatCounts, ticket_count: 5, negative: 5 },
        ],
        issue_category: [],
        app: [],
      },
    });
    const rows = csatRowsFor(data, "skill");
    expect(rows.map((row) => row.value)).toEqual(["skill-b", "skill-a", "skill-c"]);
  });
});

describe("AI review aiReviewRowsFor sort order", () => {
  it("puts small-sample groups last, then worst-rate-first among the rest", () => {
    const data = aiReviewBucket({
      by_dimension: {
        skill: [
          { value: "skill-a", ...emptyAiCounts, reviewed_ticket_count: 30, rated_ticket_count: 30, evaluated_ticket_count: 30, needs_edit_count: 6 },
          { value: "skill-b", ...emptyAiCounts, reviewed_ticket_count: 25, rated_ticket_count: 25, evaluated_ticket_count: 25, needs_edit_count: 15 },
          { value: "skill-c", ...emptyAiCounts, reviewed_ticket_count: 5, rated_ticket_count: 5, evaluated_ticket_count: 5, needs_edit_count: 5 },
        ],
        issue_category: [],
        app: [],
      },
    });
    const rows = aiReviewRowsFor(data, "skill");
    expect(rows.map((row) => row.value)).toEqual(["skill-b", "skill-a", "skill-c"]);
  });
});
