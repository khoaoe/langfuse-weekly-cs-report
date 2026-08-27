import type {
  DashboardSnapshot,
  DashboardView,
  EntryCoverage,
  Segments,
  TransferReasons,
  WeekDefinition,
  WeeklyReportRow,
} from "./dashboard-schema";
import { parseIsoDate, weekSpanDays } from "./format";

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
