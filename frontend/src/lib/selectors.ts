import type {
  DashboardSnapshot,
  DashboardView,
  WeekDefinition,
  WeeklyReportRow,
} from "./dashboard-schema";
import type { TicketFilters } from "./dashboard-filters";
import {
  formatAverage,
  formatCount,
  formatPointDelta,
  formatRate,
  formatWeekStart,
  formatWeekdayName,
} from "./format";

export const COHORT_LABELS: Readonly<Record<WeekDefinition, string>> = {
  mon_sun: "T2–CN",
  mon_fri: "T2–T6",
};

export const COHORT_DESCRIPTIONS: Readonly<Record<WeekDefinition, string>> = {
  mon_sun: "Tuần thứ Hai đến Chủ nhật, gồm ticket mở cuối tuần.",
  mon_fri: "Tuần thứ Hai đến thứ Sáu, loại ticket mở cuối tuần.",
};

/** A trend needs at least two observed weeks; one point is not a line. */
export const MIN_TREND_WEEKS = 2;

/** Internal selector value for an explicit all-period report scope. */
export const ALL_WEEKS_SCOPE = "__all__";
/** Internal selector value for a client-aggregated multi-week subset. */
export const SELECTED_WEEKS_SCOPE = "__selected_weeks__";

export function selectView(
  snapshot: DashboardSnapshot,
  weekDefinition: WeekDefinition,
): DashboardView {
  return snapshot.views[weekDefinition];
}

/** Canonical chronological order used by comparisons and exports. */
export function selectWeekly(view: DashboardView): WeeklyReportRow[] {
  return [...view.weekly].sort((left, right) =>
    left.cohort_week.localeCompare(right.cohort_week),
  );
}

export function isObservedWeek(
  view: DashboardView,
  cohortWeek: string,
): boolean {
  return view.weekly.some(
    (row) => row.cohort_week === cohortWeek && row.has_data,
  );
}

function selectReportWeek(
  view: DashboardView,
  activeWeek?: string,
): WeeklyReportRow | null {
  if (
    activeWeek === ALL_WEEKS_SCOPE ||
    activeWeek === SELECTED_WEEKS_SCOPE
  ) {
    return null;
  }
  if (activeWeek !== undefined && activeWeek !== "") {
    const selected = selectWeekly(view).find(
      (row) => row.cohort_week === activeWeek && row.has_data,
    );
    if (selected !== undefined) {
      return selected;
    }
  }
  return selectLatestWeek(view);
}

export function selectLatestWeek(view: DashboardView): WeeklyReportRow | null {
  const weeks = selectWeekly(view);
  for (let index = weeks.length - 1; index >= 0; index -= 1) {
    const row = weeks[index];
    if (row !== undefined && row.has_data) {
      return row;
    }
  }
  return null;
}

/**
 * The previous week is the most recent *completed* week before the latest one.
 *
 * A week-to-date row is never used as a comparison base, because a partial
 * week against a full week is not a like-for-like reading.
 */
export function selectPreviousWeek(
  view: DashboardView,
  latest: WeeklyReportRow | null,
): WeeklyReportRow | null {
  if (latest === null) {
    return null;
  }
  const weeks = selectWeekly(view).filter(
    (row) =>
      row.has_data &&
      row.cohort_status === "complete" &&
      row.cohort_week < latest.cohort_week,
  );
  return weeks.at(-1) ?? null;
}

export interface ReportRangeScope {
  readonly from: string;
  readonly to: string;
}

export type LedgerTone = "brand" | "neutral" | "warning" | "critical";

export interface LedgerCell {
  readonly id: string;
  readonly label: string;
  readonly value: string;
  /**
   * The unit that belongs to `value`, rendered subordinate to the number
   * rather than inside it. A rate cell needs its unit to avoid being misread
   * as a percentage, but at the 36px display size the unit set as part of the
   * value wrapped onto a second line and gave "lần/ticket" the same weight as
   * the number, breaking the one-line rhythm the other cells hold.
   */
  readonly unit: string | null;
  /** Null when the cell measured nothing and a share would restate the zero. */
  readonly support: string | null;
  readonly tone: LedgerTone;
  /**
   * Null unless this exact count maps to an existing Ticket Explorer filter
   * combination. Reopen has no matching filter key today, so it stays
   * non-interactive rather than open a filter that quietly means something
   * narrower than the number shown.
   */
  readonly filterPatch: Partial<TicketFilters> | null;
  /** Movement against the group's `comparison` baseline; null when none is valid. */
  readonly delta: LedgerDelta | null;
}

export interface LedgerDelta {
  /** Arrow, sign and unit together, so the direction never rests on colour. */
  readonly text: string;
  readonly tone: "warning" | "neutral";
}

interface ComparableRates {
  readonly aiFirst: number | null;
  readonly aiEndToEnd: number | null;
  readonly transfer: number | null;
  readonly reopen: number | null;
}

function weekRates(row: WeeklyReportRow): ComparableRates {
  const total = row.total_tickets;
  return {
    aiFirst: total === 0 ? null : row.ai_first_rate,
    aiEndToEnd: total === 0 ? null : row.ai_end_to_end_count / total,
    transfer:
      total === 0 ? null : (row.ai_then_cs_count + row.direct_cs_count) / total,
    reopen: row.reopen_lifetime_rate,
  };
}

/**
 * The like-for-like baseline for one scoped week, or null.
 *
 * A running week is compared only with `same_period` -- the previous weeks cut
 * at the same weekday -- which carries AI First and reopen and nothing else,
 * so the other two cells get no delta rather than one against a full week.
 * A completed week is compared with the completed week before it. Multi-week,
 * whole-period and day-range scopes have no single baseline.
 */
function selectComparison(
  view: DashboardView,
  week: WeeklyReportRow | null,
): { readonly label: string; readonly current: ComparableRates; readonly baseline: ComparableRates } | null {
  if (week === null) {
    return null;
  }
  if (week.cohort_status === "wtd") {
    const samePeriod = view.same_period;
    if (samePeriod === null || samePeriod.current.cohort_week !== week.cohort_week) {
      return null;
    }
    return {
      label: `so với cùng kỳ tới ${formatWeekdayName(samePeriod.cutoff_weekday)}`,
      current: {
        aiFirst: samePeriod.current.ai_first_rate,
        aiEndToEnd: null,
        transfer: null,
        reopen: samePeriod.current.reopen_lifetime_rate,
      },
      baseline: {
        aiFirst: samePeriod.baseline.ai_first_rate,
        aiEndToEnd: null,
        transfer: null,
        reopen: samePeriod.baseline.reopen_lifetime_rate,
      },
    };
  }
  const previous = selectPreviousWeek(view, week);
  return previous === null
    ? null
    : {
        label: `so với tuần ${formatWeekStart(previous.cohort_week)}`,
        current: weekRates(week),
        baseline: weekRates(previous),
      };
}

function arrow(rounded: number): string {
  return rounded > 0 ? "▲ " : rounded < 0 ? "▼ " : "";
}

function pointDelta(current: number | null, baseline: number | null): LedgerDelta | null {
  if (current === null || baseline === null) {
    return null;
  }
  // Rounded to the 0,1-point display step first, so "+0,0" never gets an arrow.
  const rounded = Math.round((current - baseline) * 1000) / 1000;
  return { text: `${arrow(rounded)}${formatPointDelta(rounded)}`, tone: "neutral" };
}

function reopenDelta(current: number | null, baseline: number | null): LedgerDelta | null {
  if (current === null || baseline === null) {
    return null;
  }
  const rounded = Math.round((current - baseline) * 100) / 100;
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "";
  return {
    text: `${arrow(rounded)}${sign}${formatAverage(Math.abs(rounded))} lần/ticket`,
    // Reopen is the one cell where up is bad.
    tone: rounded > 0 ? "warning" : "neutral",
  };
}

function share(numerator: number, denominator: number): string {
  return denominator === 0 ? "—" : formatRate(numerator / denominator);
}

/** The numbers the ledger and the title both read from. */
export interface LedgerScope {
  readonly eligible: number;
  readonly aiFirstCount: number;
  readonly aiFirstRate: number | null;
  readonly transferTotal: number;
  readonly reopenNumerator: number;
  readonly reopenDenominator: number;
  readonly gt4WithoutCs: number;
  /**
   * Counted with `gt4WithoutCs` so the ledger can show the whole tail. On its
   * own `gt4WithoutCs` is 0 in 2 of 10 observed weeks and <= 3 in 7 of them --
   * a number that would sit at zero most weeks -- while the two together run
   * 6..142 and move every week.
   */
  readonly gt4WithCs: number;
  readonly directCsCount: number;
  readonly resolvedFirstReply: number;
  readonly aiEndToEndCount: number;
  /**
   * Total AI reply turns across AI First tickets: the stored numerator of
   * `aiReplyMeanAiFirst`. Both come from the same field on the weekly row, and
   * the pipeline asserts `sum == mean * ai_first_count` before serialising, so
   * the two ledger cells that print them cannot disagree.
   */
  readonly aiReplySumAiFirst: number;
  readonly aiReplyMeanAiFirst: number | null;
  readonly week: WeeklyReportRow | null;
  readonly kind: "week" | "all" | "selection" | "empty" | "range";
  readonly rangeFrom?: string;
  readonly rangeTo?: string;
}

/**
 * Total AI reply turns and their mean across weeks with different ai_first
 * populations. The mean is the summed numerator over the summed denominator,
 * never the average of the per-week means: that would be the same
 * averaging-of-rates mistake as the rolling-rate trap, letting a week with 5
 * ai_first tickets count as much as a week with 500. Returning both from one
 * pass is what keeps the ledger cell showing the total and the cell showing
 * the total divided by its base in agreement.
 */
function replyTotals(weeks: readonly WeeklyReportRow[]): {
  readonly sum: number;
  readonly mean: number | null;
} {
  let sum = 0;
  let totalWeight = 0;
  for (const week of weeks) {
    if (week.ai_first_count === 0) {
      continue;
    }
    sum += week.ai_reply_sum_ai_first;
    totalWeight += week.ai_first_count;
  }
  return { sum, mean: totalWeight === 0 ? null : sum / totalWeight };
}

/**
 * Resolves the reporting scope to the latest observed week.
 *
 * The ledger and the dynamic title must describe the same
 * population. Mixing a twelve-week total into the ledger while the title
 * talks about the current week produces two different, unlabelled truths next
 * to each other; when no week has data the range total is used and the caller
 * labels it as such.
 */
export function selectScope(
  snapshot: DashboardSnapshot,
  weekDefinition: WeekDefinition,
  activeWeek?: string,
  range?: ReportRangeScope | null,
): LedgerScope {
  const view = selectView(snapshot, weekDefinition);
  if (range != null) {
    const observedWeeks = view.weekly.filter((row) => row.has_data);
    const replies = replyTotals(observedWeeks);
    return {
      eligible: view.totals.eligible_ticket_count,
      aiFirstCount: view.ai_first.count,
      aiFirstRate: view.ai_first.rate,
      transferTotal: view.totals.transfer_total,
      reopenNumerator: view.reopen.lifetime.numerator,
      reopenDenominator: view.reopen.lifetime.denominator,
      gt4WithoutCs: view.rule_gt4.gt4_turn_without_cs,
      gt4WithCs: view.rule_gt4.gt4_turn_with_cs,
      directCsCount: view.outcomes.direct_cs,
      resolvedFirstReply: observedWeeks.reduce(
        (total, row) => total + row.resolved_first_reply,
        0,
      ),
      aiEndToEndCount: view.outcomes.ai_end_to_end,
      aiReplySumAiFirst: replies.sum,
      aiReplyMeanAiFirst: replies.mean,
      week: null,
      kind: "range",
      rangeFrom: range.from,
      rangeTo: range.to,
    };
  }
  const week = selectReportWeek(view, activeWeek);
  if (week === null) {
    const observedWeeks = view.weekly.filter((row) => row.has_data);
    const replies = replyTotals(observedWeeks);
    return {
      eligible: view.totals.eligible_ticket_count,
      aiFirstCount: view.ai_first.count,
      aiFirstRate: view.ai_first.rate,
      transferTotal: view.totals.transfer_total,
      reopenNumerator: view.reopen.lifetime.numerator,
      reopenDenominator: view.reopen.lifetime.denominator,
      gt4WithoutCs: view.rule_gt4.gt4_turn_without_cs,
      gt4WithCs: view.rule_gt4.gt4_turn_with_cs,
      directCsCount: view.outcomes.direct_cs,
      resolvedFirstReply: observedWeeks.reduce(
        (total, row) => total + row.resolved_first_reply,
        0,
      ),
      aiEndToEndCount: view.outcomes.ai_end_to_end,
      aiReplySumAiFirst: replies.sum,
      aiReplyMeanAiFirst: replies.mean,
      week: null,
      kind:
        activeWeek === ALL_WEEKS_SCOPE
          ? "all"
          : activeWeek === SELECTED_WEEKS_SCOPE
            ? "selection"
            : "empty",
    };
  }

  return {
    eligible: week.total_tickets,
    aiFirstCount: week.ai_first_count,
    aiFirstRate: week.ai_first_rate,
    transferTotal: week.ai_then_cs_count + week.direct_cs_count,
    reopenNumerator: week.reopen_lifetime_numerator,
    reopenDenominator: week.reopen_lifetime_denominator,
    gt4WithoutCs: week.gt4_turn_without_cs,
    gt4WithCs: week.gt4_turn_with_cs,
    directCsCount: week.direct_cs_count,
    resolvedFirstReply: week.resolved_first_reply,
    aiEndToEndCount: week.ai_end_to_end_count,
    aiReplySumAiFirst: week.ai_reply_sum_ai_first,
    aiReplyMeanAiFirst: week.ai_reply_mean_ai_first,
    week,
    kind: "week",
  };
}

export interface LedgerGroup {
  readonly id: "ledger-group-ticket" | "ledger-group-secondary";
  readonly label: string;
  /**
   * The one base every cell in the group divides by, or null when the group
   * has no single base. The secondary row has none: its cells divide by the
   * eligible population, ai_first and ai_end_to_end, so any number printed
   * here would be wrong for most of them. Each cell states its own base.
   */
  readonly denominator: string | null;
  /** Names the baseline every cell delta in the group is measured against. */
  readonly comparison: string | null;
  readonly cells: readonly LedgerCell[];
}

/**
 * Four headline cells, then one secondary row.
 *
 * The headline answers "better or worse than the baseline" in ten seconds:
 * AI First, AI xử lý trọn, Tổng chuyển CS and reopen, each with a delta. The
 * five supporting numbers -- CS First, the >3-turn tail and the three
 * per-response cells -- sit in one smaller row below so they stay readable
 * without competing with the four the week is judged on.
 */
export function selectLedger(
  snapshot: DashboardSnapshot,
  weekDefinition: WeekDefinition,
  activeWeek?: string,
  range?: ReportRangeScope | null,
): LedgerGroup[] {
  const scope = selectScope(snapshot, weekDefinition, activeWeek, range);
  const comparison =
    scope.kind === "week"
      ? selectComparison(selectView(snapshot, weekDefinition), scope.week)
      : null;
  // Named once, on the group heading. Every cell in the ticket group divides
  // by the same number, so repeating it under each cell says it four times.
  const populationLabel =
    scope.kind === "all"
      ? "ticket trong toàn kỳ"
      : scope.kind === "selection"
        ? "ticket trong các tuần đã chọn"
        : scope.kind === "range"
          ? "ticket trong khoảng ngày"
          : "ticket tuần này";

  const gt4Total = scope.gt4WithCs + scope.gt4WithoutCs;
  const reopenCellDelta =
    comparison === null
      ? null
      : reopenDelta(comparison.current.reopen, comparison.baseline.reopen);

  const ticketCells: LedgerCell[] = [
    {
      id: "ledger-ai-first",
      label: "AI First",
      value: formatCount(scope.aiFirstCount),
      unit: null,
      support:
        scope.eligible === 0 ? null : share(scope.aiFirstCount, scope.eligible),
      tone: "brand",
      // Exact, not approximate: the pipeline validator rejects any week where
      // ai_first != ai_end_to_end + ai_then_cs, and `outcome` is multi-select.
      filterPatch:
        scope.aiFirstCount === 0 ? null : { outcome: "ai_end_to_end,ai_then_cs" },
      delta:
        comparison === null
          ? null
          : pointDelta(comparison.current.aiFirst, comparison.baseline.aiFirst),
    },
    {
      // The outcome the product is judged on: tickets AI closed with no human
      // in the loop.
      id: "ledger-ai-end-to-end",
      label: "AI xử lý trọn",
      value: formatCount(scope.aiEndToEndCount),
      unit: null,
      support:
        scope.eligible === 0
          ? null
          : share(scope.aiEndToEndCount, scope.eligible),
      tone: "brand",
      filterPatch:
        scope.aiEndToEndCount === 0 ? null : { outcome: "ai_end_to_end" },
      delta:
        comparison === null
          ? null
          : pointDelta(
              comparison.current.aiEndToEnd,
              comparison.baseline.aiEndToEnd,
            ),
    },
    {
      id: "ledger-transfer",
      label: "Tổng chuyển CS",
      value: formatCount(scope.transferTotal),
      unit: null,
      support:
        scope.eligible === 0 ? null : share(scope.transferTotal, scope.eligible),
      tone: "neutral",
      filterPatch: scope.transferTotal === 0 ? null : { transferred: "true" },
      delta:
        comparison === null
          ? null
          : pointDelta(comparison.current.transfer, comparison.baseline.transfer),
    },
    {
      id: "ledger-reopen",
      label: "Reopen sau AI First",
      // Rate leads, count supports. The absolute count rises with volume by
      // construction, so leading with it invited a false "reopen is climbing"
      // read every time traffic grew; lần/ticket compares across weeks.
      value:
        scope.reopenDenominator === 0
          ? "—"
          : formatAverage(scope.reopenNumerator / scope.reopenDenominator),
      unit: scope.reopenDenominator === 0 ? null : "lần/ticket",
      support:
        scope.reopenDenominator === 0
          ? null
          : `${formatCount(scope.reopenNumerator)} lần trên ${formatCount(
              scope.reopenDenominator,
            )} ticket AI First`,
      // Warning only when it rose against its baseline. A standing amber on
      // any non-zero reopen taught readers to ignore the colour.
      tone: reopenCellDelta?.tone === "warning" ? "warning" : "neutral",
      filterPatch: null,
      delta: reopenCellDelta,
    },
  ];

  const secondaryCells: LedgerCell[] = [
    {
      // Same tickets as outcome `direct_cs`, read from the CS side. AI First +
      // CS First falls short of `eligible` by `unclassified`, so this must
      // never be computed as `eligible - aiFirst`.
      id: "ledger-direct-cs",
      label: "CS First",
      value: formatCount(scope.directCsCount),
      unit: null,
      support:
        scope.eligible === 0 ? null : share(scope.directCsCount, scope.eligible),
      tone: "neutral",
      filterPatch:
        scope.directCsCount === 0 ? null : { outcome: "direct_cs" },
      delta: null,
    },
    {
      // The tail the mean hides. "lượt xử lý" counts `turn_count`, every turn
      // in the conversation, not `ai_reply_count`.
      id: "ledger-gt4-turn",
      label: "Ticket >3 lượt xử lý",
      value: formatCount(gt4Total),
      unit: null,
      support:
        scope.eligible === 0 ? null : share(gt4Total, scope.eligible),
      tone: "neutral",
      filterPatch: gt4Total === 0 ? null : { gt4_turn: "true" },
      delta: null,
    },
    {
      // The numerator the mean beside it divides, so the two read as one
      // division; only this one spells out the base.
      id: "ledger-ai-reply-total",
      label: "Tổng lượt AI trả lời",
      value: formatCount(scope.aiReplySumAiFirst),
      unit: "lượt",
      support:
        scope.aiFirstCount === 0
          ? null
          : `trên ${formatCount(scope.aiFirstCount)} ticket AI First`,
      tone: "neutral",
      filterPatch: null,
      delta: null,
    },
    {
      id: "ledger-replies-per-ticket",
      label: "TB lượt/ticket AI First",
      value:
        scope.aiReplyMeanAiFirst === null
          ? "—"
          : formatAverage(scope.aiReplyMeanAiFirst),
      unit: scope.aiReplyMeanAiFirst === null ? null : "lượt",
      support: null,
      tone: "neutral",
      filterPatch: null,
      delta: null,
    },
    {
      id: "ledger-first-reply-resolved",
      label: "Xong hẳn trong 1 lượt",
      value: share(scope.resolvedFirstReply, scope.aiEndToEndCount),
      unit: null,
      support:
        scope.aiEndToEndCount === 0
          ? null
          : `${formatCount(scope.resolvedFirstReply)} trong ${formatCount(
              scope.aiEndToEndCount,
            )} ticket AI xử lý trọn`,
      tone: "neutral",
      filterPatch: null,
      delta: null,
    },
  ];

  return [
    {
      id: "ledger-group-ticket",
      label: "Theo ticket",
      denominator: `${formatCount(scope.eligible)} ${populationLabel}`,
      comparison: comparison?.label ?? null,
      cells: ticketCells,
    },
    {
      id: "ledger-group-secondary",
      label: "Chỉ số phụ",
      denominator: null,
      comparison: null,
      cells: secondaryCells,
    },
  ];
}

export interface AttentionItem {
  readonly id: string;
  readonly severity: "critical" | "warning";
  readonly headline: string;
  /** Null when the item's own button already says what to do next. */
  readonly action: string | null;
  readonly filterPatch: Partial<TicketFilters> | null;
}

/**
 * Only actionable warnings reach the rail.
 *
 * Everything here names the number, the consequence and the next step, so the
 * rail stays empty on a healthy week instead of manufacturing alarm.
 */
export function selectAttentionItems(
  snapshot: DashboardSnapshot,
  weekDefinition: WeekDefinition,
  activeWeek?: string,
  range?: ReportRangeScope | null,
): AttentionItem[] {
  const scope = selectScope(snapshot, weekDefinition, activeWeek, range);
  const items: AttentionItem[] = [];

  if (scope.gt4WithoutCs > 0) {
    items.push({
      id: "attention-gt4",
      severity: "critical",
      headline: `${formatCount(scope.gt4WithoutCs)} ticket có hơn 3 lượt xử lý mà chưa chuyển CS`,
      action: null,
      filterPatch: { gt4_turn: "true", transferred: "false" },
    });
  }

  if (!snapshot.gate_status.allowed) {
    items.push({
      id: "attention-gate",
      severity: "critical",
      headline: `${formatRate(snapshot.gate_status.structural_invalid_rate)} bản ghi lỗi cấu trúc, vượt ngưỡng 5%`,
      action: "Số tuần này chưa dùng để ra quyết định. Kiểm tra nguồn dữ liệu trước.",
      filterPatch: null,
    });
  }

  if (snapshot.enrichment_status === "partial") {
    items.push({
      id: "attention-enrichment",
      severity: "warning",
      headline:
        "Lần đọc này chưa lấy đủ dữ liệu phụ từ Langfuse, nên Intent, Skill, Transstatus và Step result còn thiếu.",
      action: null,
      filterPatch: null,
    });
  }

  // Coverage floors deliberately do NOT raise a rail item. They are measured
  // over every ticket in the whole period, so putting one beside a single
  // week's numbers compares two different denominators and reads as "this
  // week is broken" when nothing about this week changed (SPEC-v2 §5.13).
  // The "Dữ liệu này đáng tin tới đâu" panel used to state them with their
  // own denominator; it was removed on 2026-09-02 and nothing reports them
  // in the UI now.

  return items.slice(0, 3);
}
