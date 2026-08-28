import type {
  DashboardSnapshot,
  DashboardView,
  DayAggregate,
  EntryCoverage,
  Segments,
  TransferReasons,
  WeekDefinition,
  WeeklyReportRow,
} from "./dashboard-schema";
import { parseIsoDate, weekSpanDays } from "./format";

/** The subset of DashboardView totals that a day-range scope can produce.
 * Named/shaped to drop straight into selectScope()'s no-week branch inputs. */
export interface ScopedTotals {
  readonly eligible: number;
  readonly aiFirstCount: number;
  readonly aiFirstRate: number;
  readonly transferTotal: number;
  readonly directCsCount: number;
  readonly aiEndToEndCount: number;
  readonly aiThenCsCount: number;
  readonly unclassifiedCount: number;
  readonly reopenLifetimeNumerator: number;
  readonly reopenLifetimeDenominator: number;
  readonly reopenLifetimeRate: number;
  readonly gt4TurnWithCs: number;
  readonly gt4TurnWithoutCs: number;
  readonly resolvedFirstReplyCount: number;
  readonly aiReplySumAiFirst: number;
  readonly aiReplyMeanAiFirst: number | null;
}

/**
 * Sums DayAggregate rows into the totals a report-scope UI reads, regardless
 * of week or day grain (see report-scope-daterange spec F8/A2: a smaller
 * grain always composes upward, so day mode never reads by_week in parallel).
 * Pure: an empty range returns all-zero totals, not a policy decision about
 * what to show for it -- that belongs to the caller.
 */
export function aggregateDays(days: readonly DayAggregate[]): ScopedTotals {
  const eligible = days.reduce((total, day) => total + day.total_tickets, 0);
  const aiFirstCount = days.reduce((total, day) => total + day.ai_first_count, 0);
  const reopenLifetimeNumerator = days.reduce(
    (total, day) => total + day.reopen_lifetime_numerator,
    0,
  );
  const reopenLifetimeDenominator = days.reduce(
    (total, day) => total + day.reopen_lifetime_denominator,
    0,
  );
  const aiReplySumAiFirst = days.reduce(
    (total, day) => total + day.ai_reply_sum_ai_first,
    0,
  );
  return {
    eligible,
    aiFirstCount,
    aiFirstRate: eligible === 0 ? 0 : aiFirstCount / eligible,
    transferTotal: days.reduce((total, day) => total + day.transferred_count, 0),
    directCsCount: days.reduce((total, day) => total + day.direct_cs_count, 0),
    aiEndToEndCount: days.reduce((total, day) => total + day.outcomes.ai_end_to_end, 0),
    aiThenCsCount: days.reduce((total, day) => total + day.outcomes.ai_then_cs, 0),
    unclassifiedCount: days.reduce((total, day) => total + day.outcomes.unclassified, 0),
    reopenLifetimeNumerator,
    reopenLifetimeDenominator,
    reopenLifetimeRate:
      reopenLifetimeDenominator === 0
        ? 0
        : reopenLifetimeNumerator / reopenLifetimeDenominator,
    gt4TurnWithCs: days.reduce((total, day) => total + day.gt4_turn_with_cs, 0),
    gt4TurnWithoutCs: days.reduce((total, day) => total + day.gt4_turn_without_cs, 0),
    resolvedFirstReplyCount: days.reduce(
      (total, day) => total + day.resolved_first_reply_count,
      0,
    ),
    aiReplySumAiFirst,
    aiReplyMeanAiFirst: aiFirstCount === 0 ? null : aiReplySumAiFirst / aiFirstCount,
  };
}

/**
 * Rolling window rate: sums numerator/denominator over `windowDays` ending at
 * each point, then divides once -- never averages per-day rates. With one
 * ticket some days (see F7), averaging rates and summing-then-dividing give
 * visibly different, and differently wrong/right, numbers.
 */
export function rollingRate(
  days: readonly DayAggregate[],
  windowDays: number,
  numerator: (day: DayAggregate) => number,
  denominator: (day: DayAggregate) => number,
): readonly (number | null)[] {
  return days.map((_current, index) => {
    if (index + 1 < windowDays) {
      return null;
    }
    const window = days.slice(index - windowDays + 1, index + 1);
    const windowDenominator = window.reduce((total, day) => total + denominator(day), 0);
    if (windowDenominator === 0) {
      return null;
    }
    const windowNumerator = window.reduce((total, day) => total + numerator(day), 0);
    return windowNumerator / windowDenominator;
  });
}

/**
 * Groups a (possibly sparse) day array into weeks by `weekDefinition`. Uses
 * each day's own ISO date to compute its week start, never positional
 * chunking -- a gap for a missing weekend day would otherwise silently shift
 * every following day into the wrong week.
 */
export function rollDaysIntoWeeks(
  days: readonly DayAggregate[],
  _weekDefinition: WeekDefinition,
): readonly DayAggregate[] {
  const buckets = new Map<string, DayAggregate[]>();
  for (const current of days) {
    const parsed = parseIsoDate(current.day);
    if (parsed === null) {
      continue;
    }
    const weekday = (parsed.getUTCDay() + 6) % 7; // Monday = 0
    const weekStart = new Date(parsed);
    weekStart.setUTCDate(parsed.getUTCDate() - weekday);
    const key = weekStart.toISOString().slice(0, 10);
    const bucket = buckets.get(key) ?? [];
    bucket.push(current);
    buckets.set(key, bucket);
  }

  return [...buckets.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([weekStart, weekDays]) => mergeDaysAsOneRow(weekStart, weekDays));
}

function mergeDaysAsOneRow(
  weekStart: string,
  days: readonly DayAggregate[],
): DayAggregate {
  const dimensionBuckets = {
    skill: new Map<string, { total: number; ai_first: number; transferred: number; reopen: number }>(),
    app: new Map<string, { total: number; ai_first: number; transferred: number; reopen: number }>(),
    issue_category: new Map<string, { total: number; ai_first: number; transferred: number; reopen: number }>(),
  };
  for (const current of days) {
    for (const dimension of ["skill", "app", "issue_category"] as const) {
      const buckets = dimensionBuckets[dimension];
      for (const [label, counts] of Object.entries(current.segments[dimension])) {
        const bucket = buckets.get(label) ?? {
          total: 0,
          ai_first: 0,
          transferred: 0,
          reopen: 0,
        };
        buckets.set(label, {
          total: bucket.total + counts.total,
          ai_first: bucket.ai_first + counts.ai_first,
          transferred: bucket.transferred + counts.transferred,
          reopen: bucket.reopen + counts.reopen,
        });
      }
    }
  }
  const segments: DayAggregate["segments"] = {
    skill: Object.fromEntries(dimensionBuckets.skill),
    app: Object.fromEntries(dimensionBuckets.app),
    issue_category: Object.fromEntries(dimensionBuckets.issue_category),
  };
  const transferReasons: Record<string, number> = {};
  for (const current of days) {
    for (const [reason, count] of Object.entries(current.transfer_reasons)) {
      transferReasons[reason] = (transferReasons[reason] ?? 0) + count;
    }
  }

  return {
    day: weekStart,
    total_tickets: days.reduce((total, current) => total + current.total_tickets, 0),
    ai_first_count: days.reduce((total, current) => total + current.ai_first_count, 0),
    transferred_count: days.reduce((total, current) => total + current.transferred_count, 0),
    direct_cs_count: days.reduce((total, current) => total + current.direct_cs_count, 0),
    outcomes: {
      ai_end_to_end: days.reduce((total, current) => total + current.outcomes.ai_end_to_end, 0),
      ai_then_cs: days.reduce((total, current) => total + current.outcomes.ai_then_cs, 0),
      direct_cs: days.reduce((total, current) => total + current.outcomes.direct_cs, 0),
      unclassified: days.reduce((total, current) => total + current.outcomes.unclassified, 0),
    },
    reopen_lifetime_numerator: days.reduce((total, current) => total + current.reopen_lifetime_numerator, 0),
    reopen_lifetime_denominator: days.reduce((total, current) => total + current.reopen_lifetime_denominator, 0),
    gt4_turn_with_cs: days.reduce((total, current) => total + current.gt4_turn_with_cs, 0),
    gt4_turn_without_cs: days.reduce((total, current) => total + current.gt4_turn_without_cs, 0),
    resolved_first_reply_count: days.reduce(
      (total, current) => total + current.resolved_first_reply_count,
      0,
    ),
    ai_reply_sum_ai_first: days.reduce(
      (total, current) => total + current.ai_reply_sum_ai_first,
      0,
    ),
    segments,
    transfer_reasons: transferReasons,
  };
}

const SEGMENT_DIMENSIONS = [
  "issue_category",
  "app",
  "product_code",
  "skill",
  "intent",
  "tpe",
  "guardrail_rule",
  "entry_point",
] as const satisfies readonly (keyof Segments)[];

type WeekDetail = DashboardView["by_week"][string];

function aggregateSegments(details: readonly WeekDetail[]): Segments {
  return Object.fromEntries(
    SEGMENT_DIMENSIONS.map((dimension) => {
      const buckets = new Map<
        string,
        { total: number; ai_first: number; transferred: number; reopen: number }
      >();
      for (const detail of details) {
        for (const [label, row] of Object.entries(detail.segments[dimension])) {
          const current = buckets.get(label) ?? {
            total: 0,
            ai_first: 0,
            transferred: 0,
            reopen: 0,
          };
          buckets.set(label, {
            total: current.total + row.total,
            ai_first: current.ai_first + row.ai_first,
            transferred: current.transferred + row.transferred,
            reopen: current.reopen + row.reopen,
          });
        }
      }
      return [dimension, Object.fromEntries(buckets)] as const;
    }),
  ) as Segments;
}

function aggregateCountRows<T extends { readonly count: number }>(
  rows: readonly T[],
  key: (row: T) => string,
): T[] {
  const grouped = new Map<string, T>();
  for (const row of rows) {
    const grain = key(row);
    const current = grouped.get(grain);
    grouped.set(
      grain,
      current === undefined
        ? row
        : { ...row, count: current.count + row.count },
    );
  }
  return [...grouped.values()].sort(
    (left, right) => right.count - left.count || key(left).localeCompare(key(right)),
  );
}

function aggregateTransferReasons(
  details: readonly WeekDetail[],
): TransferReasons {
  const reasons = details.map((detail) => detail.transfer_reasons);
  return {
    observed_transfer_denominator: reasons.reduce(
      (total, item) => total + item.observed_transfer_denominator,
      0,
    ),
    triggers: aggregateCountRows(
      reasons.flatMap((item) => item.triggers),
      (row) =>
        JSON.stringify([row.reason, row.rule, row.source, row.stage, row.skill]),
    ),
    step_result_missing: {
      count: reasons.reduce(
        (total, item) => total + item.step_result_missing.count,
        0,
      ),
      denominator: reasons.reduce(
        (total, item) => total + item.step_result_missing.denominator,
        0,
      ),
    },
    tpe: aggregateCountRows(
      reasons.flatMap((item) => item.tpe),
      (row) => JSON.stringify([row.transstatus, row.step_result]),
    ),
    guardrail: aggregateCountRows(
      reasons.flatMap((item) => item.guardrail),
      (row) => row.rule,
    ),
    escalation_guard_blocked: {
      count: reasons.reduce(
        (total, item) => total + item.escalation_guard_blocked.count,
        0,
      ),
      denominator: reasons.reduce(
        (total, item) => total + item.escalation_guard_blocked.denominator,
        0,
      ),
    },
  };
}

function scopeEntryCoverage(
  coverage: EntryCoverage | null,
  selected: ReadonlySet<string>,
): EntryCoverage | null {
  return coverage === null
    ? null
    : { ...coverage, by_week: filterByWeek(coverage.by_week, selected) };
}

function filterByWeek<T>(
  byWeek: Readonly<Record<string, T>>,
  selected: ReadonlySet<string>,
): Record<string, T> {
  return Object.fromEntries(
    Object.entries(byWeek).filter(([cohortWeek]) => selected.has(cohortWeek)),
  );
}

/**
 * Resolves an inclusive date range to the observed weeks it touches, snapping
 * to full weeks: a week is included when it overlaps `[from, to]` by at least
 * one day.
 *
 * Returns `[]` on malformed input or when no week is touched — it does not
 * decide what to do about an empty result. That policy (keep the previous
 * selection, show an inline error) lives in the caller.
 */
export function resolveDateRangeToWeeks(
  weekly: readonly WeeklyReportRow[],
  weekDefinition: WeekDefinition,
  from: string,
  to: string,
): readonly string[] {
  const fromDate = parseIsoDate(from);
  const toDate = parseIsoDate(to);
  if (fromDate === null || toDate === null) {
    return [];
  }

  const spanDays = weekSpanDays(weekDefinition);
  const touched: { cohortWeek: string; weekStart: Date }[] = [];
  for (const row of weekly) {
    if (!row.has_data) {
      continue;
    }
    const weekStart = parseIsoDate(row.cohort_week);
    if (weekStart === null) {
      continue;
    }
    const weekEnd = new Date(weekStart);
    weekEnd.setUTCDate(weekStart.getUTCDate() + spanDays);
    if (
      weekStart.getTime() <= toDate.getTime() &&
      weekEnd.getTime() >= fromDate.getTime()
    ) {
      touched.push({ cohortWeek: row.cohort_week, weekStart });
    }
  }

  return touched
    .sort((left, right) => left.weekStart.getTime() - right.weekStart.getTime())
    .map((entry) => entry.cohortWeek);
}

/** Build a read-only client projection for an arbitrary set of observed weeks. */
export function scopeSnapshotToWeeks(
  snapshot: DashboardSnapshot,
  weekDefinition: WeekDefinition,
  cohortWeeks: readonly string[],
): DashboardSnapshot {
  const view = snapshot.views[weekDefinition];
  const selected = new Set(cohortWeeks);
  const weekly = view.weekly.filter(
    (row) => row.has_data && selected.has(row.cohort_week),
  );
  const details = weekly.flatMap((row) => {
    const detail = view.by_week[row.cohort_week];
    return detail === undefined ? [] : [detail];
  });
  if (weekly.length === 0 || details.length !== weekly.length) {
    return snapshot;
  }

  const eligible = weekly.reduce((total, row) => total + row.total_tickets, 0);
  const aiFirst = weekly.reduce((total, row) => total + row.ai_first_count, 0);
  const lifetimeNumerator = weekly.reduce(
    (total, row) => total + row.reopen_lifetime_numerator,
    0,
  );
  const lifetimeDenominator = weekly.reduce(
    (total, row) => total + row.reopen_lifetime_denominator,
    0,
  );
  const within7dDenominator = weekly.reduce(
    (total, row) => total + (row.reopen_7d_denominator ?? 0),
    0,
  );
  const within7dNumerator = weekly.reduce(
    (total, row) =>
      total +
      Math.round((row.reopen_7d_rate ?? 0) * (row.reopen_7d_denominator ?? 0)),
    0,
  );
  const transferReasons = aggregateTransferReasons(details);
  const monFriByWeek = new Map(
    snapshot.views.mon_fri.weekly.map((row) => [row.cohort_week, row]),
  );
  const weekendStartCount =
    weekDefinition === "mon_fri"
      ? 0
      : weekly.reduce((total, row) => {
          const weekdayRow = monFriByWeek.get(row.cohort_week);
          return (
            total +
            Math.max(
              0,
              row.total_tickets - (weekdayRow?.total_tickets ?? row.total_tickets),
            )
          );
        }, 0);
  const scopedView: DashboardView = {
    ...view,
    totals: {
      eligible_ticket_count: eligible,
      transfer_total: weekly.reduce(
        (total, row) => total + row.ai_then_cs_count + row.direct_cs_count,
        0,
      ),
      gt4_turn_total: weekly.reduce(
        (total, row) =>
          total + row.gt4_turn_with_cs + row.gt4_turn_without_cs,
        0,
      ),
      weekend_start_count: weekendStartCount,
    },
    outcomes: {
      ai_end_to_end: weekly.reduce(
        (total, row) => total + row.ai_end_to_end_count,
        0,
      ),
      ai_then_cs: weekly.reduce(
        (total, row) => total + row.ai_then_cs_count,
        0,
      ),
      direct_cs: weekly.reduce(
        (total, row) => total + row.direct_cs_count,
        0,
      ),
      unclassified: weekly.reduce(
        (total, row) => total + row.unclassified_count,
        0,
      ),
    },
    ai_first: {
      count: aiFirst,
      rate: eligible === 0 ? 0 : aiFirst / eligible,
    },
    reopen: {
      lifetime: {
        numerator: lifetimeNumerator,
        denominator: lifetimeDenominator,
      },
      within_7d: {
        numerator: within7dNumerator,
        denominator: within7dDenominator,
      },
    },
    weekly,
    segments: aggregateSegments(details),
    transfer_reasons: transferReasons,
    by_week: filterByWeek(view.by_week, selected),
    same_period: null,
    csat:
      view.csat === null
        ? null
        : { ...view.csat, by_week: filterByWeek(view.csat.by_week, selected) },
    outcome_reconciliation:
      view.outcome_reconciliation === null
        ? null
        : {
            ...view.outcome_reconciliation,
            by_week: filterByWeek(
              view.outcome_reconciliation.by_week,
              selected,
            ),
          },
    entry_coverage: scopeEntryCoverage(view.entry_coverage, selected),
    rule_gt4: {
      gt4_turn_total: weekly.reduce(
        (total, row) =>
          total + row.gt4_turn_with_cs + row.gt4_turn_without_cs,
        0,
      ),
      gt4_turn_with_cs: weekly.reduce(
        (total, row) => total + row.gt4_turn_with_cs,
        0,
      ),
      gt4_turn_without_cs: weekly.reduce(
        (total, row) => total + row.gt4_turn_without_cs,
        0,
      ),
      max_replies_rule_fired: weekly.reduce(
        (total, row) => total + row.max_replies_rule_fired,
        0,
      ),
    },
  };

  return {
    ...snapshot,
    views: { ...snapshot.views, [weekDefinition]: scopedView },
  };
}

const EMPTY_SEGMENT_BUCKETS: Segments[keyof Segments] = {};

/** Segments dimensions no day-grain source can populate (see DayAggregateSegments). */
const DAY_UNAVAILABLE_SEGMENT_DIMENSIONS = [
  "product_code",
  "intent",
  "tpe",
  "guardrail_rule",
  "entry_point",
  "model_core",
] as const satisfies readonly (keyof Segments)[];

function daySegmentsToSegments(days: readonly DayAggregate[]): Segments {
  const dayLevel = mergeDaysAsOneRow("__scope__", days).segments;
  const segments = { ...dayLevel } as Segments;
  for (const dimension of DAY_UNAVAILABLE_SEGMENT_DIMENSIONS) {
    segments[dimension] = EMPTY_SEGMENT_BUCKETS;
  }
  return segments;
}

/**
 * Builds a read-only client projection for an arbitrary true day range,
 * mirroring scopeSnapshotToWeeks()'s pattern but sourced from ticket-level
 * DayAggregate rows instead of by_week weekly detail (see spec F8/A2: day
 * grain sums up, it is never derived by decomposing a weekly aggregate).
 *
 * Several WeeklyReportRow/DashboardView fields have no day-grain source
 * (ai_reply_p50/p90/max, reopen_reason, same_period, csat,
 * outcome_reconciliation, and the full TransferReasons breakdown incl. TPE):
 * these become null/zero/empty placeholders here. Callers must not read them
 * from this view -- TransferDiagnostics in particular must keep reading the
 * real weekly snapshot's latest complete week, never this synthetic one.
 */
export function scopeSnapshotToDayRange(
  weekDefinition: WeekDefinition,
  days: readonly DayAggregate[],
  from: string,
): DashboardView {
  const totals = aggregateDays(days);
  const segments = daySegmentsToSegments(days);
  const cohortWeek = from;

  const syntheticRow: WeeklyReportRow = {
    cohort_week: cohortWeek,
    cohort_status: "complete",
    week_definition: weekDefinition,
    has_data: totals.eligible > 0,
    total_tickets: totals.eligible,
    ai_first_count: totals.aiFirstCount,
    ai_first_rate: totals.aiFirstRate,
    ai_end_to_end_count: totals.aiEndToEndCount,
    ai_then_cs_count: totals.aiThenCsCount,
    direct_cs_count: totals.directCsCount,
    unclassified_count: totals.unclassifiedCount,
    reopen_7d_rate: null,
    reopen_7d_denominator: null,
    reopen_lifetime_rate: totals.reopenLifetimeRate,
    reopen_lifetime_numerator: totals.reopenLifetimeNumerator,
    reopen_lifetime_denominator: totals.reopenLifetimeDenominator,
    ai_reply_mean_ai_first: totals.aiReplyMeanAiFirst,
    ai_reply_p50: null,
    ai_reply_p90: null,
    ai_reply_max: null,
    gt4_turn_with_cs: totals.gt4TurnWithCs,
    gt4_turn_without_cs: totals.gt4TurnWithoutCs,
    max_replies_rule_fired: 0,
    resolved_first_reply: totals.resolvedFirstReplyCount,
    as_of: new Date(0).toISOString(),
    reopen_reason: {
      labels_version: null,
      status: "unavailable",
      counts: {},
      by_business: {},
      coverage: { population: 0, labeled: 0, abstained: 0, failed: 0, invalid: 0 },
      control: { direct_cs_reopen_7d_rate: null, direct_cs_denominator: 0 },
    },
  };

  return {
    totals: {
      eligible_ticket_count: totals.eligible,
      transfer_total: totals.transferTotal,
      gt4_turn_total: totals.gt4TurnWithCs + totals.gt4TurnWithoutCs,
      weekend_start_count: 0,
    },
    outcomes: {
      ai_end_to_end: totals.aiEndToEndCount,
      ai_then_cs: totals.aiThenCsCount,
      direct_cs: totals.directCsCount,
      unclassified: totals.unclassifiedCount,
    },
    ai_first: {
      count: totals.aiFirstCount,
      rate: totals.aiFirstRate,
    },
    reopen: {
      lifetime: {
        numerator: totals.reopenLifetimeNumerator,
        denominator: totals.reopenLifetimeDenominator,
      },
      within_7d: { numerator: 0, denominator: 0 },
    },
    weekly: [syntheticRow],
    segments,
    transfer_reasons: {
      observed_transfer_denominator: 0,
      triggers: [],
      step_result_missing: { count: 0, denominator: 0 },
      tpe: [],
      guardrail: [],
      escalation_guard_blocked: { count: 0, denominator: 0 },
    },
    by_week: {
      [cohortWeek]: {
        segments,
        transfer_reasons: {
          observed_transfer_denominator: 0,
          triggers: [],
          step_result_missing: { count: 0, denominator: 0 },
          tpe: [],
          guardrail: [],
          escalation_guard_blocked: { count: 0, denominator: 0 },
        },
      },
    },
    same_period: null,
    csat: null,
    outcome_reconciliation: null,
    entry_coverage: null,
    rule_gt4: {
      gt4_turn_total: totals.gt4TurnWithCs + totals.gt4TurnWithoutCs,
      gt4_turn_with_cs: totals.gt4TurnWithCs,
      gt4_turn_without_cs: totals.gt4TurnWithoutCs,
      max_replies_rule_fired: 0,
    },
  };
}

/**
 * Wraps `scopeSnapshotToDayRange()`'s single-cohort view into a full
 * `DashboardSnapshot`, mirroring `scopeSnapshotToWeeks()`'s pattern: only
 * `views[weekDefinition]` is replaced with the day-range synthetic view;
 * the other cohort's view and every top-level field (generated_at, source,
 * coverage, data_range) stay the real snapshot's, unmodified.
 */
export function scopeSnapshotToDayRangeSnapshot(
  snapshot: DashboardSnapshot,
  weekDefinition: WeekDefinition,
  days: readonly DayAggregate[],
  from: string,
): DashboardSnapshot {
  return {
    ...snapshot,
    views: {
      ...snapshot.views,
      [weekDefinition]: scopeSnapshotToDayRange(weekDefinition, days, from),
    },
  };
}
