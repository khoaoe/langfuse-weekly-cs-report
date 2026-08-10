import { describe, expect, it } from "vitest";

import { dashboardEnvelopeFixture, loadingEnvelopeFixture } from "./fixtures/dashboard";
import {
  DashboardEnvelopeSchema,
  TransferReasonsSchema,
  TicketRowSchema,
  parseDashboardEnvelope,
  type SamePeriod,
} from "../src/lib/dashboard-schema";

describe("dashboard API envelope", () => {
  it("keeps exclusive transfer-trigger source and stage in the strict schema", () => {
    const parsed = TransferReasonsSchema.parse({
      observed_transfer_denominator: 2,
      triggers: [
        {
          reason: "skill_suggested_transfer",
          rule: "cs_escalation",
          source: "skill_guardrail_checked",
          stage: "output",
          skill: "interbank-fund-transfer",
          count: 1,
        },
        {
          reason: "ai_response_requires_transfer",
          rule: "cs_escalation",
          source: "output_guardrail",
          stage: null,
          skill: null,
          count: 1,
        },
      ],
      step_result_missing: { count: 2, denominator: 2 },
      tpe: [],
      guardrail: [],
      escalation_guard_blocked: { count: 0, denominator: 2 },
    });

    expect(parsed.triggers.map((row) => [row.reason, row.source])).toEqual([
      ["skill_suggested_transfer", "skill_guardrail_checked"],
      ["ai_response_requires_transfer", "output_guardrail"],
    ]);
  });

  it.each([
    [
      "TPE count above the transfer denominator",
      (base: typeof dashboardEnvelopeFixture.snapshot.views.mon_sun.transfer_reasons) => ({
        ...base,
        tpe: [{ ...base.tpe[0], count: base.observed_transfer_denominator + 1 }],
      }),
    ],
    [
      "duplicate guardrail rules",
      (base: typeof dashboardEnvelopeFixture.snapshot.views.mon_sun.transfer_reasons) => ({
        ...base,
        guardrail: [base.guardrail[0], base.guardrail[0]],
      }),
    ],
    [
      "guardrail count above the transfer denominator",
      (base: typeof dashboardEnvelopeFixture.snapshot.views.mon_sun.transfer_reasons) => ({
        ...base,
        guardrail: [
          {
            ...base.guardrail[0],
            count: base.observed_transfer_denominator + 1,
          },
        ],
      }),
    ],
    [
      "escalation denominator mismatch",
      (base: typeof dashboardEnvelopeFixture.snapshot.views.mon_sun.transfer_reasons) => ({
        ...base,
        escalation_guard_blocked: {
          count: 0,
          denominator: base.observed_transfer_denominator + 1,
        },
      }),
    ],
    [
      "escalation count above the transfer denominator",
      (base: typeof dashboardEnvelopeFixture.snapshot.views.mon_sun.transfer_reasons) => ({
        ...base,
        escalation_guard_blocked: {
          count: base.observed_transfer_denominator + 1,
          denominator: base.observed_transfer_denominator,
        },
      }),
    ],
  ])("rejects %s", (_label, mutate) => {
    const base = dashboardEnvelopeFixture.snapshot.views.mon_sun.transfer_reasons;
    expect(TransferReasonsSchema.safeParse(mutate(base)).success).toBe(false);
  });

  it("rejects a transfer denominator that disagrees with segment totals", () => {
    const view = dashboardEnvelopeFixture.snapshot.views.mon_sun;
    const issueCategories = view.segments.issue_category;
    if (issueCategories === undefined) {
      throw new Error("Fixture must contain the issue_category dimension.");
    }
    const issueCategory = issueCategories["Thanh toán-IBFT"];
    if (issueCategory === undefined) {
      throw new Error("Fixture must contain the Thanh toán-IBFT segment.");
    }
    const malformed = {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        views: {
          ...dashboardEnvelopeFixture.snapshot.views,
          mon_sun: {
            ...view,
            segments: {
              ...view.segments,
              issue_category: {
                "Thanh toán-IBFT": {
                  ...issueCategory,
                  transferred: 1,
                },
              },
            },
          },
        },
      },
    };

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  const weeklyTemplate =
    dashboardEnvelopeFixture.snapshot.views.mon_sun.weekly[0];
  const detailTemplate =
    dashboardEnvelopeFixture.snapshot.views.mon_sun.by_week["2026-07-20"];
  const samePeriod = {
    cutoff_date: "2026-07-23",
    cutoff_weekday: 4,
    current: {
      cohort_week: "2026-07-20",
      total_tickets: 8,
      ai_first_count: 6,
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
        total_tickets: 8,
        ai_first_count: 6,
        ai_first_rate: 0.75,
        reopen_lifetime_rate: 0.25,
        reopen_lifetime_numerator: 1,
        reopen_lifetime_denominator: 4,
      },
    },
  };
  const csatFeedbackEntry = {
    ticket_id: "6991254",
    responded_at: "2026-07-21T01:00:00Z",
    satisfaction_bucket: "positive" as const,
    outcome: "ai_end_to_end" as const,
    skill: "interbank-fund-transfer",
    issue_category: "Chuyển tiền",
    text: "Cảm ơn, xử lý nhanh",
    response_number: 1,
    response_total: 2,
    is_latest_for_ticket: false,
  };
  const csatWeek = {
    response_count: 2,
    ticket_count: 1,
    positive: 0,
    neutral: 1,
    negative: 0,
    by_outcome: {
      ai_end_to_end: {
        ticket_count: 1,
        positive: 0,
        neutral: 1,
        negative: 0,
      },
      ai_then_cs: {
        ticket_count: 0,
        positive: 0,
        neutral: 0,
        negative: 0,
      },
      direct_cs: {
        ticket_count: 0,
        positive: 0,
        neutral: 0,
        negative: 0,
      },
      unclassified: {
        ticket_count: 0,
        positive: 0,
        neutral: 0,
        negative: 0,
      },
    },
    by_dimension: {
      skill: [
        {
          value: "interbank-fund-transfer",
          ticket_count: 1,
          positive: 0,
          neutral: 1,
          negative: 0,
        },
      ],
      issue_category: [
        {
          value: "Chuyển tiền",
          ticket_count: 1,
          positive: 0,
          neutral: 1,
          negative: 0,
        },
      ],
    },
    feedback_entries: [csatFeedbackEntry],
  };
  const csat = {
    source: "freshdesk" as const,
    fetched_at: "2026-08-01T03:00:00Z",
    by_week: { "2026-07-20": csatWeek },
  };

  function envelopeWithSamePeriod(
    comparison: SamePeriod = samePeriod,
  ) {
    return {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        views: {
          mon_sun: {
            ...dashboardEnvelopeFixture.snapshot.views.mon_sun,
            weekly: [
              {
                ...weeklyTemplate,
                cohort_week: "2026-07-06",
                cohort_status: "complete" as const,
              },
              {
                ...weeklyTemplate,
                cohort_week: "2026-07-13",
                cohort_status: "complete" as const,
              },
              { ...weeklyTemplate, cohort_status: "wtd" as const },
            ],
            by_week: {
              "2026-07-06": detailTemplate,
              "2026-07-13": detailTemplate,
              "2026-07-20": detailTemplate,
            },
            same_period: comparison,
          },
          mon_fri: {
            ...dashboardEnvelopeFixture.snapshot.views.mon_fri,
            same_period: null,
          },
        },
      },
    };
  }

  function envelopeWithCsat(value: unknown = csat) {
    return {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        views: {
          ...dashboardEnvelopeFixture.snapshot.views,
          mon_sun: {
            ...dashboardEnvelopeFixture.snapshot.views.mon_sun,
            csat: value,
          },
        },
      },
    };
  }

  const reconciliation = {
    source: "freshdesk" as const,
    fetched_at: "2026-08-03T01:00:00Z",
    by_week: {
      "2026-07-20": {
        langfuse_ai_end_to_end: 6,
        checked_ticket_count: 4,
        human_replied_after_ai: 1,
        unresolved_ticket_count: 1,
        mismatch_rate: 0.25,
      },
    },
  };

  function envelopeWithReconciliation(value: unknown = reconciliation) {
    return {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        views: {
          ...dashboardEnvelopeFixture.snapshot.views,
          mon_sun: {
            ...dashboardEnvelopeFixture.snapshot.views.mon_sun,
            outcome_reconciliation: value,
          },
        },
      },
    };
  }

  it("accepts the current ready envelope without storage-only fields", () => {
    const parsed = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture);

    expect(parsed.status).toBe("ready");
    expect(parsed.snapshot?.views.mon_sun.weekly[0]?.cohort_week).toBe("2026-07-20");
    expect(parsed.snapshot?.views.mon_sun.transfer_reasons).toMatchObject({
      observed_transfer_denominator: 3,
      step_result_missing: { count: 1, denominator: 3 },
      tpe: [
        { transstatus: "-365", step_result: "-1013", count: 2 },
        { transstatus: "-217", step_result: null, count: 1 },
      ],
    });
    expect(parsed.snapshot).not.toHaveProperty("schema_version");
    expect(parsed.snapshot).not.toHaveProperty("tickets");
    expect(parsed.snapshot?.views.mon_sun.csat).toBeNull();
  });

  it("accepts reconciled Freshdesk entry coverage aggregates", () => {
    const entryCoverage = {
      source: "freshdesk" as const,
      source_start_week: "2026-07-06" as const,
      fetched_at: "2026-08-04T03:00:00Z",
      by_week: {
        "2026-07-20": {
          freshdesk_ticket_count: 10,
          ai_replied_only: 4,
          ai_replied_then_transferred: 2,
          transferred_without_ai_reply: 1,
          invoked_no_result: 1,
          not_observed_invoked: 2,
          not_observed_human_replied: 1,
          not_observed_no_human_reply: 1,
          unresolved: 0,
        },
      },
    };
    const envelope = {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        views: {
          ...dashboardEnvelopeFixture.snapshot.views,
          mon_sun: {
            ...dashboardEnvelopeFixture.snapshot.views.mon_sun,
            entry_coverage: entryCoverage,
          },
        },
      },
    };

    const parsed = DashboardEnvelopeSchema.parse(envelope);
    expect(parsed.snapshot?.views.mon_sun.entry_coverage).toEqual(entryCoverage);
  });

  it.each(["unknown status", "status total mismatch"])(
    "rejects invalid Freshdesk entry coverage: %s",
    (label) => {
      const invalidCounts =
        label === "unknown status"
          ? { extra_status: 1 }
          : { freshdesk_ticket_count: 2 };
    const entryCoverage = {
      source: "freshdesk" as const,
      source_start_week: "2026-07-06" as const,
      fetched_at: "2026-08-04T03:00:00Z",
      by_week: {
        "2026-07-20": {
          freshdesk_ticket_count: 1,
          ai_replied_only: 1,
          ai_replied_then_transferred: 0,
          transferred_without_ai_reply: 0,
          invoked_no_result: 0,
          not_observed_invoked: 0,
          not_observed_human_replied: 0,
          not_observed_no_human_reply: 0,
          unresolved: 0,
          ...invalidCounts,
        },
      },
    };
    const envelope = {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        views: {
          ...dashboardEnvelopeFixture.snapshot.views,
          mon_sun: {
            ...dashboardEnvelopeFixture.snapshot.views.mon_sun,
            entry_coverage: entryCoverage,
          },
        },
      },
    };

      expect(DashboardEnvelopeSchema.safeParse(envelope).success).toBe(false);
    },
  );

  it("accepts the strict bot-only CSAT and redacted-comment contract", () => {
    const parsed = DashboardEnvelopeSchema.parse(envelopeWithCsat());

    expect(parsed.snapshot?.views.mon_sun.csat).toEqual(csat);
  });

  it("accepts strict observational Freshdesk reconciliation", () => {
    const parsed = DashboardEnvelopeSchema.parse(envelopeWithReconciliation());

    expect(
      parsed.snapshot?.views.mon_sun.outcome_reconciliation,
    ).toEqual(reconciliation);
  });

  it("accepts a fetchable reconciliation population below the Langfuse outcome total", () => {
    const fetchableOnly = {
      ...reconciliation,
      by_week: {
        "2026-07-20": {
          ...reconciliation.by_week["2026-07-20"],
          langfuse_ai_end_to_end: 5,
        },
      },
    };

    expect(
      DashboardEnvelopeSchema.safeParse(
        envelopeWithReconciliation(fetchableOnly),
      ).success,
    ).toBe(true);
  });

  it.each([
    {
      ...reconciliation,
      by_week: {
        "2026-07-20": {
          ...reconciliation.by_week["2026-07-20"],
          checked_ticket_count: 99,
        },
      },
    },
    {
      ...reconciliation,
      by_week: {
        "2026-07-20": {
          ...reconciliation.by_week["2026-07-20"],
          mismatch_rate: null,
        },
      },
    },
    {
      ...reconciliation,
      by_week: {
        "2026-07-20": {
          ...reconciliation.by_week["2026-07-20"],
          agent_id: 42,
        },
      },
    },
  ])("rejects non-reconciling or private reconciliation fields", (value) => {
    expect(
      DashboardEnvelopeSchema.safeParse(envelopeWithReconciliation(value)).success,
    ).toBe(false);
  });

  it("requires the nullable outcome reconciliation key on every view", () => {
    const view = dashboardEnvelopeFixture.snapshot.views.mon_sun;
    const { outcome_reconciliation: removed, ...withoutReconciliation } = view;
    expect(removed).toBeNull();

    expect(
      DashboardEnvelopeSchema.safeParse({
        ...dashboardEnvelopeFixture,
        snapshot: {
          ...dashboardEnvelopeFixture.snapshot,
          views: {
            ...dashboardEnvelopeFixture.snapshot.views,
            mon_sun: withoutReconciliation,
          },
        },
      }).success,
    ).toBe(false);
  });

  it("requires the nullable csat key on every dashboard view", () => {
    const view = dashboardEnvelopeFixture.snapshot.views.mon_sun;
    const { csat: removedCsat, ...withoutCsat } = view;
    expect(removedCsat).toBeNull();
    const malformed = {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        views: {
          ...dashboardEnvelopeFixture.snapshot.views,
          mon_sun: withoutCsat,
        },
      },
    };

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  it("requires a feedback_entries array in every CSAT week", () => {
    const { feedback_entries: removedEntries, ...withoutEntries } = csatWeek;
    expect(removedEntries).toHaveLength(1);

    expect(
      DashboardEnvelopeSchema.safeParse(
        envelopeWithCsat({
          ...csat,
          by_week: { "2026-07-20": withoutEntries },
        }),
      ).success,
    ).toBe(false);
  });

  it.each([
    ["CSAT object", { ...csat, agent_id: 42 }],
    [
      "weekly aggregate",
      {
        ...csat,
        by_week: {
          "2026-07-20": { ...csatWeek, rating_raw: 103 },
        },
      },
    ],
    [
      "feedback entry",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            feedback_entries: [{ ...csatFeedbackEntry, feedback: "raw" }],
          },
        },
      },
    ],
  ])("rejects unknown privacy-sensitive fields in the %s", (_name, value) => {
    expect(DashboardEnvelopeSchema.safeParse(envelopeWithCsat(value)).success).toBe(
      false,
    );
  });

  it.each(["agent_id", "survey_id", "rating_raw", "comment_present", "response_key"])(
    "rejects the private feedback field %s",
    (field) => {
      expect(
        DashboardEnvelopeSchema.safeParse(
          envelopeWithCsat({
            ...csat,
            by_week: {
              "2026-07-20": {
                ...csatWeek,
                feedback_entries: [
                  { ...csatFeedbackEntry, [field]: "private" },
                ],
              },
            },
          }),
        ).success,
      ).toBe(false);
    },
  );

  it.each([
    [
      "non-UTC fetched_at",
      { ...csat, fetched_at: "2026-08-01T10:00:00+07:00" },
    ],
    [
      "non-Freshdesk source",
      { ...csat, source: "langfuse" },
    ],
    ["counts that do not reconcile", {
      ...csat,
      by_week: { "2026-07-20": { ...csatWeek, positive: 1 } },
    }],
    [
      "an outcome bucket that does not reconcile",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            by_outcome: {
              ...csatWeek.by_outcome,
              ai_end_to_end: {
                ...csatWeek.by_outcome.ai_end_to_end,
                positive: 1,
              },
            },
          },
        },
      },
    ],
    [
      "more tickets than responses",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            ticket_count: 3,
          },
        },
      },
    ],
    [
      "a CSAT week outside the view",
      {
        ...csat,
        by_week: { "2026-07-27": csatWeek },
      },
    ],
    [
      "an invalid feedback ticket",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            feedback_entries: [{ ...csatFeedbackEntry, ticket_id: "ticket-1" }],
          },
        },
      },
    ],
    [
      "an unknown satisfaction bucket",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            feedback_entries: [
              { ...csatFeedbackEntry, satisfaction_bucket: "satisfied" },
            ],
          },
        },
      },
    ],
    [
      "feedback longer than the approved limit",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            feedback_entries: [{ ...csatFeedbackEntry, text: "x".repeat(201) }],
          },
        },
      },
    ],
    [
      "feedback containing a URL",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            feedback_entries: [
              { ...csatFeedbackEntry, text: "Xem https://private.example/a" },
            ],
          },
        },
      },
    ],
    [
      "a missing outcome key",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            by_outcome: {
              ai_end_to_end: csatWeek.by_outcome.ai_end_to_end,
              ai_then_cs: csatWeek.by_outcome.ai_then_cs,
              direct_cs: csatWeek.by_outcome.direct_cs,
            },
          },
        },
      },
    ],
    [
      "an extra dimension",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            by_dimension: { ...csatWeek.by_dimension, app: [] },
          },
        },
      },
    ],
    [
      "duplicate dimension values",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            by_dimension: {
              ...csatWeek.by_dimension,
              skill: [
                ...csatWeek.by_dimension.skill,
                ...csatWeek.by_dimension.skill,
              ],
            },
          },
        },
      },
    ],
    [
      "a dimension total that does not reconcile",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            by_dimension: {
              ...csatWeek.by_dimension,
              skill: [{ ...csatWeek.by_dimension.skill[0], ticket_count: 2 }],
            },
          },
        },
      },
    ],
    [
      "response number zero",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            feedback_entries: [{ ...csatFeedbackEntry, response_number: 0 }],
          },
        },
      },
    ],
    [
      "response number greater than total",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            feedback_entries: [{ ...csatFeedbackEntry, response_number: 3 }],
          },
        },
      },
    ],
    [
      "a mismatched latest marker",
      {
        ...csat,
        by_week: {
          "2026-07-20": {
            ...csatWeek,
            feedback_entries: [{ ...csatFeedbackEntry, is_latest_for_ticket: true }],
          },
        },
      },
    ],
  ])("rejects %s", (_name, value) => {
    expect(DashboardEnvelopeSchema.safeParse(envelopeWithCsat(value)).success).toBe(
      false,
    );
  });

  it.each([
    ["phone number", "Liên hệ 0912345678"],
    ["UUID", "Mã 550e8400-e29b-41d4-a716-446655440000"],
    ["long numeric identifier", "Mã tham chiếu 123456"],
    ["control character", "Cảm ơn\u0000"],
    ["Vietnamese personal name", "Nguyễn Văn An"],
  ])("rejects CSAT feedback containing a %s", (_name, text) => {
    expect(
      DashboardEnvelopeSchema.safeParse(
        envelopeWithCsat({
          ...csat,
          by_week: {
            "2026-07-20": {
              ...csatWeek,
              feedback_entries: [{ ...csatFeedbackEntry, text }],
            },
          },
        }),
      ).success,
    ).toBe(false);
  });

  it("accepts same_period inside each view", () => {
    const withSamePeriod = envelopeWithSamePeriod();

    expect(DashboardEnvelopeSchema.safeParse(withSamePeriod).success).toBe(true);
  });

  it("rejects a same_period current row that differs from its by_week row", () => {
    const malformed = envelopeWithSamePeriod({
      ...samePeriod,
      current: {
        ...samePeriod.current,
        total_tickets: 4,
        ai_first_count: 3,
        ai_first_rate: 0.75,
        reopen_lifetime_numerator: 1,
        reopen_lifetime_denominator: 4,
        reopen_lifetime_rate: 0.25,
      },
    });

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  it("rejects a same_period baseline using more than four weeks", () => {
    const malformed = envelopeWithSamePeriod({
      ...samePeriod,
      baseline: { ...samePeriod.baseline, weeks_used: 5 },
    });

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  it("rejects same_period when its current cohort is not the running week", () => {
    const valid = envelopeWithSamePeriod();
    const malformed = {
      ...valid,
      snapshot: {
        ...valid.snapshot,
        views: {
          ...valid.snapshot.views,
          mon_sun: {
            ...valid.snapshot.views.mon_sun,
            weekly: valid.snapshot.views.mon_sun.weekly.map((row) => ({
              ...row,
              cohort_status: "complete" as const,
            })),
          },
        },
      },
    };

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  it("rejects same_period with fewer non-empty historical rows than weeks_used", () => {
    const malformed = envelopeWithSamePeriod({
      ...samePeriod,
      by_week: {
        "2026-07-13": samePeriod.by_week["2026-07-13"],
        "2026-07-20": samePeriod.by_week["2026-07-20"],
      },
    });

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  it("rejects same_period at the dashboard top level", () => {
    const malformed = {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        same_period: null,
      },
    };

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  it("rejects same_period weeks that are absent from the view by_week map", () => {
    const malformed = envelopeWithSamePeriod({
      ...samePeriod,
      by_week: {
        ...samePeriod.by_week,
        "2026-07-27": {
          ...samePeriod.current,
          cohort_week: "2026-07-27",
        },
      },
    });

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  it("rejects the legacy inferred TPE shape instead of reviving Case or taxonomy mapping", () => {
    const view = dashboardEnvelopeFixture.snapshot.views.mon_sun;
    const malformed = {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        views: {
          ...dashboardEnvelopeFixture.snapshot.views,
          mon_sun: {
            ...view,
            transfer_reasons: {
              ...view.transfer_reasons,
              tpe: [
                {
                  code: "-383",
                  status: "Đang xử lý",
                  step: "700212",
                  case: 2,
                  mapped: true,
                  count: 2,
                },
              ],
            },
          },
        },
      },
    };

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  it.each([
    { count: 1, denominator: 2 },
    { count: 4, denominator: 3 },
  ])(
    "rejects non-reconciling missing Step result coverage %#",
    (stepResultMissing) => {
      const view = dashboardEnvelopeFixture.snapshot.views.mon_sun;
      const malformed = {
        ...dashboardEnvelopeFixture,
        snapshot: {
          ...dashboardEnvelopeFixture.snapshot,
          views: {
            ...dashboardEnvelopeFixture.snapshot.views,
            mon_sun: {
              ...view,
              transfer_reasons: {
                ...view.transfer_reasons,
                step_result_missing: stepResultMissing,
              },
            },
          },
        },
      };

      expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
    },
  );

  it("rejects duplicate Transstatus and Step result grains", () => {
    const view = dashboardEnvelopeFixture.snapshot.views.mon_sun;
    const row = view.transfer_reasons.tpe[0];
    if (row === undefined) {
      throw new Error("Fixture must contain a TPE signal.");
    }
    const malformed = {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        views: {
          ...dashboardEnvelopeFixture.snapshot.views,
          mon_sun: {
            ...view,
            transfer_reasons: {
              ...view.transfer_reasons,
              tpe: [row, row],
            },
          },
        },
      },
    };

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  it.each(["700212|2|Đang xử lý", "１２３", "1234567", "-1013\n", true])(
    "rejects an unsafe exact-source TPE token: %s",
    (unsafeToken) => {
      const view = dashboardEnvelopeFixture.snapshot.views.mon_sun;
      const row = view.transfer_reasons.tpe[0];
      if (row === undefined) {
        throw new Error("Fixture must contain a TPE signal.");
      }
      const malformed = {
        ...dashboardEnvelopeFixture,
        snapshot: {
          ...dashboardEnvelopeFixture.snapshot,
          views: {
            ...dashboardEnvelopeFixture.snapshot.views,
            mon_sun: {
              ...view,
              transfer_reasons: {
                ...view.transfer_reasons,
                tpe: [{ ...row, step_result: unsafeToken }],
              },
            },
          },
        },
      };

      expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
    },
  );

  it("rejects a newline after Transstatus instead of treating it as string end", () => {
    const view = dashboardEnvelopeFixture.snapshot.views.mon_sun;
    const row = view.transfer_reasons.tpe[0];
    if (row === undefined) {
      throw new Error("Fixture must contain a TPE signal.");
    }
    const malformed = {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        views: {
          ...dashboardEnvelopeFixture.snapshot.views,
          mon_sun: {
            ...view,
            transfer_reasons: {
              ...view.transfer_reasons,
              tpe: [{ ...row, transstatus: "-365\n" }],
            },
          },
        },
      },
    };

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  it("rejects legacy taxonomy data even when the browser would not render it", () => {
    const malformed = {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        unmapped_tpe_codes: [{ code: "-999", status: "Chờ map", count: 1 }],
      },
    };

    expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
  });

  it("requires the compatibility-only ticket status field to stay null", () => {
    const row = {
      ticket_id: "6991254",
      opened_at: "2026-07-20T02:00:00Z",
      cohort_week: "2026-07-20",
      cohort_status: "complete",
      is_weekend_start: false,
      outcome: "ai_end_to_end",
      ai_first: true,
      transferred: false,
      reopen_lifetime: 0,
      reopen_within_7d: 0,
      ai_reply_count: 1,
      turn_count: 2,
      gt4_turn: false,
      issue_category: "Thanh toán",
      app: "Zalopay",
      product_code: "IBFT",
      skill: null,
      intent: null,
      tpe_code: "-365",
      tpe_status: "Đang xử lý",
      guardrail_rule: null,
      transfer_reason: null,
      escalation_guard_blocked: false,
      csat_satisfaction: null,
      data_quality: "valid",
    };

    expect(TicketRowSchema.safeParse(row).success).toBe(false);
    expect(
      TicketRowSchema.safeParse({ ...row, tpe_status: null }).success,
    ).toBe(true);
    const { csat_satisfaction: removedCsat, ...withoutCsat } = {
      ...row,
      tpe_status: null,
    };
    expect(removedCsat).toBeNull();
    expect(TicketRowSchema.safeParse(withoutCsat).success).toBe(false);
    const { transfer_reason: removedReason, ...withoutTransferReason } = {
      ...row,
      tpe_status: null,
    };
    expect(removedReason).toBeNull();
    expect(TicketRowSchema.safeParse(withoutTransferReason).success).toBe(false);
    expect(
      TicketRowSchema.safeParse({
        ...row,
        tpe_status: null,
        transferred: true,
        transfer_reason: "max_replies_exceeded",
      }).success,
    ).toBe(true);
    expect(
      TicketRowSchema.safeParse({
        ...row,
        tpe_status: null,
        transferred: false,
        transfer_reason: "max_replies_exceeded",
      }).success,
    ).toBe(false);
    expect(
      TicketRowSchema.safeParse({
        ...row,
        tpe_status: null,
        csat_satisfaction: "unknown",
      }).success,
    ).toBe(false);
    expect(
      TicketRowSchema.safeParse({
        ...row,
        tpe_code: "-365\n",
        tpe_status: null,
      }).success,
    ).toBe(false);
  });

  it("rejects normalized invalid calendar timestamps and accepts canonical fractions", () => {
    const snapshot = dashboardEnvelopeFixture.snapshot;
    expect(
      DashboardEnvelopeSchema.safeParse({
        ...dashboardEnvelopeFixture,
        snapshot: {
          ...snapshot,
          generated_at: "2026-02-31T00:00:00Z",
        },
      }).success,
    ).toBe(false);
    expect(
      DashboardEnvelopeSchema.safeParse({
        ...dashboardEnvelopeFixture,
        snapshot: {
          ...snapshot,
          generated_at: "2026-02-28T00:00:00.123456Z",
        },
      }).success,
    ).toBe(true);
  });

  it("accepts initial loading with no snapshot", () => {
    expect(DashboardEnvelopeSchema.parse(loadingEnvelopeFixture)).toMatchObject({
      status: "loading",
      snapshot: null,
    });
  });

  it("fails closed with a safe user error for malformed server data", () => {
    const malformed = { ...dashboardEnvelopeFixture, snapshot: { ...dashboardEnvelopeFixture.snapshot, views: {} } };

    expect(parseDashboardEnvelope(malformed)).toEqual({
      ok: false,
      message: "Không thể đọc dữ liệu dashboard.",
    });
  });

  it.each(["missing", "unexpected"] as const)(
    "rejects %s by_week keys instead of mixing aggregate and weekly scopes",
    (caseName) => {
      const view = dashboardEnvelopeFixture.snapshot.views.mon_sun;
      const detail = view.by_week["2026-07-20"];
      const byWeek =
        caseName === "missing"
          ? {}
          : { ...view.by_week, "2026-07-27": detail };
      const malformed = {
        ...dashboardEnvelopeFixture,
        snapshot: {
          ...dashboardEnvelopeFixture.snapshot,
          views: {
            ...dashboardEnvelopeFixture.snapshot.views,
            mon_sun: { ...view, by_week: byWeek },
          },
        },
      };

      expect(DashboardEnvelopeSchema.safeParse(malformed).success).toBe(false);
    },
  );
});
