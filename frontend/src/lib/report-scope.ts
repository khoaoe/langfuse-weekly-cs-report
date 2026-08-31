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
import { formatDateRangeLabel, parseIsoDate, weekSpanDays } from "./format";

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
/**
 * Buckets a (possibly sparse) day array by Monday-start week, using each
 * day's own ISO date -- never positional chunking, since a gap for a missing
 * weekend day would otherwise silently shift every following day into the
 * wrong week. Shared by `rollDaysIntoWeeks()` (merged totals) and
 * `scopeSnapshotToDayRange()`/`buildDayRangeWeekLabels()`, which additionally
 * need the untouched per-day list to label a partially-touched week honestly.
 */
function groupDaysByWeekStart(
  days: readonly DayAggregate[],
): readonly { readonly weekStart: string; readonly days: readonly DayAggregate[] }[] {
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
    .map(([weekStart, weekDays]) => ({
      weekStart,
      days: [...weekDays].sort((left, right) => left.day.localeCompare(right.day)),
    }));
}

export function rollDaysIntoWeeks(
  days: readonly DayAggregate[],
  _weekDefinition: WeekDefinition,
): readonly DayAggregate[] {
  return groupDaysByWeekStart(days).map(({ weekStart, days: weekDays }) =>
    mergeDaysAsOneRow(weekStart, weekDays),
  );
}

/**
 * Per-touched-week label reflecting only the days actually selected, not the
 * full Monday-start week span -- a range covering only Tue-Thu of a week must
 * not claim the whole Mon-Fri/Mon-Sun week as its label (see F1).
 */
export function buildDayRangeWeekLabels(
  days: readonly DayAggregate[],
): Record<string, string> {
  return Object.fromEntries(
    groupDaysByWeekStart(days).map(({ weekStart, days: weekDays }) => {
      const first = weekDays[0]?.day ?? weekStart;
      const last = weekDays[weekDays.length - 1]?.day ?? weekStart;
      return [weekStart, formatDateRangeLabel(first, last)];
    }),
  );
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
    transfer_reasons: aggregateTransferReasonsFromDays(days),
  };
}

/**
 * Sums each day's full TransferReasons block by grain. Returns `null` if any
 * day in the range lacks the block -- an incomplete sum across a mixed grain
 * would silently understate every count instead of admitting the gap.
 */
export function aggregateTransferReasonsFromDays(
  days: readonly DayAggregate[],
): TransferReasons | null {
  if (days.length === 0) {
    return EMPTY_TRANSFER_REASONS;
  }
  const blocks: TransferReasons[] = [];
  for (const day of days) {
    if (day.transfer_reasons === null) {
      return null;
    }
    blocks.push(day.transfer_reasons);
  }
  return {
    observed_transfer_denominator: blocks.reduce(
      (total, block) => total + block.observed_transfer_denominator,
      0,
    ),
    triggers: aggregateCountRows(
      blocks.flatMap((block) => block.triggers),
      (row) => JSON.stringify([row.reason, row.rule, row.source, row.stage, row.skill]),
    ),
    step_result_missing: {
      count: blocks.reduce((total, block) => total + block.step_result_missing.count, 0),
      denominator: blocks.reduce(
        (total, block) => total + block.step_result_missing.denominator,
        0,
      ),
    },
    tpe: aggregateCountRows(
      blocks.flatMap((block) => block.tpe),
      (row) => JSON.stringify([row.transstatus, row.step_result]),
    ),
    guardrail: aggregateCountRows(
      blocks.flatMap((block) => block.guardrail),
      (row) => row.rule,
    ),
    escalation_guard_blocked: {
      count: blocks.reduce((total, block) => total + block.escalation_guard_blocked.count, 0),
      denominator: blocks.reduce(
        (total, block) => total + block.escalation_guard_blocked.denominator,
        0,
      ),
    },
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
    : {
        ...coverage,
        by_week: filterByWeek(coverage.by_week, selected),
        // A spread would carry every day of every unselected week through
        // untouched, leaving a projection whose two grains disagree about
        // what is in scope.
        ...(coverage.by_day === undefined
          ? {}
          : { by_day: filterByWeekOfDay(coverage.by_day, selected) }),
      };
}

/** An inclusive Vietnam-local day window, as the day-range picker reports it. */
export interface DayRangeScope {
  readonly from: string;
  readonly to: string;
}

/**
 * The day keys inside an inclusive range, or `null` when the payload carries no
 * day grain at all (written before day-grain scoping existed). An empty array is
 * a real answer -- "nothing opened in that range" -- and must not be confused
 * with the missing-grain case, which falls back to whole weeks.
 */
export function selectScopeDays(
  byDay: Readonly<Record<string, unknown>> | undefined,
  dayRange: DayRangeScope,
): readonly string[] | null {
  if (byDay === undefined) {
    return null;
  }
  return Object.keys(byDay)
    .filter((day) => day >= dayRange.from && day <= dayRange.to)
    .sort();
}

function filterByWeek<T>(
  byWeek: Readonly<Record<string, T>>,
  selected: ReadonlySet<string>,
): Record<string, T> {
  return Object.fromEntries(
    Object.entries(byWeek).filter(([cohortWeek]) => selected.has(cohortWeek)),
  );
}

/** Same containment rule as `filterByWeek()`, applied to day-keyed buckets. */
function filterByWeekOfDay<T>(
  byDay: Readonly<Record<string, T>>,
  selected: ReadonlySet<string>,
): Record<string, T> {
  return Object.fromEntries(
    Object.entries(byDay).filter(([day]) => {
      const parsed = parseIsoDate(day);
      if (parsed === null) {
        return false;
      }
      const weekStart = new Date(parsed);
      weekStart.setUTCDate(parsed.getUTCDate() - ((parsed.getUTCDay() + 6) % 7));
      return selected.has(weekStart.toISOString().slice(0, 10));
    }),
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
        : {
            ...view.csat,
            by_week: filterByWeek(view.csat.by_week, selected),
            // A spread would carry every day of every unselected week
            // through untouched, leaving a projection whose two grains
            // disagree about what is in scope.
            ...(view.csat.by_day === undefined
              ? {}
              : { by_day: filterByWeekOfDay(view.csat.by_day, selected) }),
          },
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
const UNAVAILABLE_REOPEN_REASON: WeeklyReportRow["reopen_reason"] = {
  labels_version: null,
  status: "unavailable",
  counts: {},
  by_business: {},
  coverage: { population: 0, labeled: 0, abstained: 0, failed: 0, invalid: 0 },
  control: { direct_cs_reopen_7d_rate: null, direct_cs_denominator: 0 },
};

const EMPTY_TRANSFER_REASONS: TransferReasons = {
  observed_transfer_denominator: 0,
  triggers: [],
  step_result_missing: { count: 0, denominator: 0 },
  tpe: [],
  guardrail: [],
  escalation_guard_blocked: { count: 0, denominator: 0 },
};

export function scopeSnapshotToDayRange(
  weekDefinition: WeekDefinition,
  days: readonly DayAggregate[],
): DashboardView {
  const totals = aggregateDays(days);
  const segments = daySegmentsToSegments(days);
  const weekBuckets = groupDaysByWeekStart(days);
  const transferReasons = aggregateTransferReasonsFromDays(days) ?? EMPTY_TRANSFER_REASONS;

  const weekly: WeeklyReportRow[] = weekBuckets.map(({ weekStart, days: weekDays }) => {
    const merged = mergeDaysAsOneRow(weekStart, weekDays);
    return {
      cohort_week: weekStart,
      cohort_status: "complete",
      week_definition: weekDefinition,
      has_data: merged.total_tickets > 0,
      total_tickets: merged.total_tickets,
      ai_first_count: merged.ai_first_count,
      ai_first_rate:
        merged.total_tickets === 0 ? 0 : merged.ai_first_count / merged.total_tickets,
      ai_end_to_end_count: merged.outcomes.ai_end_to_end,
      ai_then_cs_count: merged.outcomes.ai_then_cs,
      direct_cs_count: merged.direct_cs_count,
      unclassified_count: merged.outcomes.unclassified,
      reopen_7d_rate: null,
      reopen_7d_denominator: null,
      reopen_lifetime_rate:
        merged.reopen_lifetime_denominator === 0
          ? 0
          : merged.reopen_lifetime_numerator / merged.reopen_lifetime_denominator,
      reopen_lifetime_numerator: merged.reopen_lifetime_numerator,
      reopen_lifetime_denominator: merged.reopen_lifetime_denominator,
      ai_reply_mean_ai_first:
        merged.ai_first_count === 0
          ? null
          : merged.ai_reply_sum_ai_first / merged.ai_first_count,
      ai_reply_p50: null,
      ai_reply_p90: null,
      ai_reply_max: null,
      gt4_turn_with_cs: merged.gt4_turn_with_cs,
      gt4_turn_without_cs: merged.gt4_turn_without_cs,
      max_replies_rule_fired: 0,
      resolved_first_reply: merged.resolved_first_reply_count,
      as_of: new Date(0).toISOString(),
      reopen_reason: UNAVAILABLE_REOPEN_REASON,
    };
  });

  const byWeek = Object.fromEntries(
    weekBuckets.map(({ weekStart, days: weekDays }) => [
      weekStart,
      {
        segments: daySegmentsToSegments(weekDays),
        transfer_reasons: aggregateTransferReasonsFromDays(weekDays) ?? EMPTY_TRANSFER_REASONS,
      },
    ]),
  );

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
    weekly,
    segments,
    transfer_reasons: transferReasons,
    by_week: byWeek,
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
): DashboardSnapshot {
  return {
    ...snapshot,
    views: {
      ...snapshot.views,
      [weekDefinition]: scopeSnapshotToDayRange(weekDefinition, days),
    },
  };
}
