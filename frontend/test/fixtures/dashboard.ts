/**
 * Privacy-safe fixture mirroring web._state_envelope() and
 * DashboardSnapshot.dashboard_dict(), not the on-disk storage format.
 * It intentionally contains no trace/session/internal identifiers or customer text.
 */
const segmentCounts = {
  "Thanh toán-IBFT": { total: 10, ai_first: 8, transferred: 3, reopen: 2 },
};

const weekly = [
  {
    cohort_week: "2026-07-20",
    cohort_status: "complete",
    week_definition: "mon_sun",
    has_data: true,
    total_tickets: 10,
    ai_first_count: 8,
    ai_first_rate: 0.8,
    ai_end_to_end_count: 6,
    ai_then_cs_count: 2,
    direct_cs_count: 1,
    unclassified_count: 1,
    reopen_7d_rate: 0.25,
    reopen_7d_denominator: 8,
    reopen_lifetime_rate: 0.25,
    reopen_lifetime_numerator: 2,
    reopen_lifetime_denominator: 8,
    ai_reply_mean_ai_first: 1.25,
    ai_reply_p50: 1,
    ai_reply_p90: 2,
    ai_reply_max: 3,
    gt4_turn_with_cs: 1,
    gt4_turn_without_cs: 2,
    max_replies_rule_fired: 0,
    as_of: "2026-07-29T11:27:00Z",
    reopen_reason: {
      labels_version: null,
      status: "pending",
      counts: {},
      by_business: {},
      coverage: { population: 0, labeled: 0, abstained: 0, failed: 0, invalid: 0 },
      control: { direct_cs_reopen_7d_rate: null, direct_cs_denominator: 0 },
    },
  },
];

function view(weekDefinition: "mon_sun" | "mon_fri", total: number) {
  const rows = weekly.map((row) => ({
    ...row,
    week_definition: weekDefinition,
    total_tickets: total,
    ai_first_count: total - 2,
    ai_first_rate: (total - 2) / total,
  }));
  const segments: Record<
    string,
    Record<string, { total: number; ai_first: number; transferred: number; reopen: number }>
  > = Object.fromEntries(
    ["issue_category", "app", "product_code", "skill", "intent", "tpe", "guardrail_rule", "entry_point"].map(
      (name) => [
        name,
        name === "skill"
          ? { "interbank-fund-transfer": segmentCounts["Thanh toán-IBFT"] }
          : segmentCounts,
      ],
    ),
  );
  const transferReasons = {
    observed_transfer_denominator: 3,
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
      {
        reason: "unknown",
        rule: null,
        source: null,
        stage: null,
        skill: null,
        count: 1,
      },
    ],
    step_result_missing: { count: 1, denominator: 3 },
    tpe: [
      { transstatus: "-365", step_result: "-1013", count: 2, status: "FAILED_FACE_AUTH" },
      { transstatus: "-217", step_result: null, count: 1, status: null },
    ],
    guardrail: [{ rule: "missing_transaction_id", count: 2 }],
    escalation_guard_blocked: { count: 1, denominator: 3 },
  } as const;
  return {
    totals: { eligible_ticket_count: total, transfer_total: 3, gt4_turn_total: 3, weekend_start_count: weekDefinition === "mon_sun" ? 3 : 0 },
    outcomes: { ai_end_to_end: total - 4, ai_then_cs: 2, direct_cs: 1, unclassified: 1 },
    ai_first: { count: total - 2, rate: (total - 2) / total },
    reopen: { lifetime: { numerator: 2, denominator: total - 2 }, within_7d: { numerator: 2, denominator: total - 2 } },
    weekly: rows,
    segments,
    transfer_reasons: transferReasons,
    by_week: {
      "2026-07-20": {
        segments,
        transfer_reasons: transferReasons,
      },
    },
    same_period: null,
    csat: null,
    outcome_reconciliation: null,
    entry_coverage: null,
    rule_gt4: { gt4_turn_total: 3, gt4_turn_with_cs: 1, gt4_turn_without_cs: 2, max_replies_rule_fired: 0 },
  };
}

export const dashboardEnvelopeFixture = {
  status: "ready",
  refreshing: false,
  last_error_code: null,
  last_error_at: null,
  snapshot: {
    generated_at: "2026-07-29T11:27:00Z",
    source: { traces_fetched: 10, traces_deduplicated: 10, observations_fetched: 3 },
    enrichment_status: "complete",
    data_range: { first_week_with_data: "2026-07-20", weeks_without_data: [] },
    views: { mon_sun: view("mon_sun", 10), mon_fri: view("mon_fri", 7) },
    coverage: { issue_category: 0.9, app: 0.8, tpe: 0.8, intent: 0.7, skill: 0.6 },
    unmapped_tpe_codes: [],
    gate_status: { allowed: true, structural_invalid_rate: 0, reasons: [] },
    data_quality: { counts: {}, weekend_start_count: 3, left_censored_count: 0, pre_window_start_count: 0, invalid_keyed_session_count: 0, unkeyed_trace_count: 0 },
  },
} as const;

export const loadingEnvelopeFixture = {
  status: "loading",
  refreshing: true,
  last_error_code: null,
  last_error_at: null,
  snapshot: null,
} as const;
