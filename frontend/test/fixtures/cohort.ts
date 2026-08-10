import { dashboardEnvelopeFixture } from "./dashboard";

/**
 * Decision values intentionally diverge across the two cohort definitions.
 * This makes a stale or text-only cohort toggle impossible to miss in tests.
 */
export function divergentCohortEnvelope() {
  const base = dashboardEnvelopeFixture;
  const monFri = base.snapshot.views.mon_fri;
  const current = monFri.weekly[0];

  return {
    ...base,
    snapshot: {
      ...base.snapshot,
      views: {
        ...base.snapshot.views,
        mon_fri: {
          ...monFri,
          weekly: [
            {
              ...current,
              total_tickets: 20,
              ai_first_count: 10,
              ai_first_rate: 0.5,
              ai_then_cs_count: 5,
              direct_cs_count: 2,
              reopen_lifetime_numerator: 4,
              reopen_lifetime_denominator: 10,
              reopen_lifetime_rate: 0.4,
              gt4_turn_without_cs: 3,
            },
          ],
        },
      },
    },
  };
}

/**
 * Mirrors a midweek snapshot: no weekend-start ticket exists yet, so both
 * cohort definitions correctly resolve to the same four decision values.
 */
export function equivalentWtdCohortEnvelope() {
  const base = dashboardEnvelopeFixture;
  const monSun = base.snapshot.views.mon_sun;
  const monFri = base.snapshot.views.mon_fri;
  const monSunWeek = {
    ...monSun.weekly[0],
    cohort_status: "wtd",
  } as const;
  const monFriWeek = {
    ...monFri.weekly[0],
    cohort_status: "wtd",
    total_tickets: monSunWeek.total_tickets,
    ai_first_count: monSunWeek.ai_first_count,
    ai_first_rate: monSunWeek.ai_first_rate,
    ai_then_cs_count: monSunWeek.ai_then_cs_count,
    direct_cs_count: monSunWeek.direct_cs_count,
    reopen_lifetime_numerator: monSunWeek.reopen_lifetime_numerator,
    reopen_lifetime_denominator: monSunWeek.reopen_lifetime_denominator,
    reopen_lifetime_rate: monSunWeek.reopen_lifetime_rate,
    gt4_turn_without_cs: monSunWeek.gt4_turn_without_cs,
  } as const;

  return {
    ...base,
    snapshot: {
      ...base.snapshot,
      views: {
        ...base.snapshot.views,
        mon_sun: { ...monSun, weekly: [monSunWeek] },
        mon_fri: { ...monFri, weekly: [monFriWeek] },
      },
    },
  };
}

/**
 * The latest week counts zero stuck tickets; the range-wide rule tally the
 * diagnostics panel used to read by default counts ten. Reproduces the exact
 * contradiction a CS reader reported: the KPI cell said 0, the panel below
 * said 10, for what looked like the same week.
 */
export function staleViewLevelRuleGt4Envelope() {
  const base = dashboardEnvelopeFixture;
  const monSun = base.snapshot.views.mon_sun;
  const monFri = base.snapshot.views.mon_fri;

  const patch = (view: typeof monSun) => ({
    ...view,
    weekly: [{ ...view.weekly[0], gt4_turn_without_cs: 0 }],
    rule_gt4: {
      ...view.rule_gt4,
      gt4_turn_without_cs: 10,
      gt4_turn_total: view.rule_gt4.gt4_turn_with_cs + 10,
    },
  });

  return {
    ...base,
    snapshot: {
      ...base.snapshot,
      views: {
        ...base.snapshot.views,
        mon_sun: patch(monSun),
        mon_fri: patch(monFri),
      },
    },
  };
}
