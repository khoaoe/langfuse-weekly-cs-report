import type {
  DashboardSnapshot,
  DashboardView,
  WeekDefinition,
  WeeklyReportRow,
} from "./dashboard-schema";
import type { TicketFilters } from "./dashboard-filters";
import type { NarrativeInput } from "./narrative";
import { formatAverage, formatCount, formatRate } from "./format";

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

export function buildNarrativeInput(
  snapshot: DashboardSnapshot,
  weekDefinition: WeekDefinition,
  activeWeek?: string,
  range?: ReportRangeScope | null,
): NarrativeInput {
  const view = selectView(snapshot, weekDefinition);
  const current = range != null ? null : selectReportWeek(view, activeWeek);
  const previous = selectPreviousWeek(view, current);
  const samePeriod =
    current?.cohort_status === "wtd" &&
    view.same_period?.current.cohort_week === current.cohort_week
      ? view.same_period
      : null;

  return {
    current: {
      aiFirst: {
        count:
          samePeriod?.current.ai_first_count ??
          current?.ai_first_count ??
          view.ai_first.count,
        rate:
          samePeriod?.current.ai_first_rate ??
          current?.ai_first_rate ??
          view.ai_first.rate,
      },
      reopenRate:
        samePeriod?.current.reopen_lifetime_rate ??
        current?.reopen_lifetime_rate ??
        null,
    },
    previous:
      previous === null
        ? null
        : {
            aiFirst: {
              count: previous.ai_first_count,
              rate: previous.ai_first_rate,
            },
            reopenRate: previous.reopen_lifetime_rate,
          },
    enrichmentStatus: snapshot.enrichment_status,
    ...(current?.cohort_status === "wtd" ? { isWtd: true } : {}),
    ...(samePeriod === null
      ? {}
      : {
          samePeriod: {
            cutoffWeekday: samePeriod.cutoff_weekday,
            weeksUsed: samePeriod.baseline.weeks_used,
            aiFirstRate: samePeriod.baseline.ai_first_rate,
            reopenRate: samePeriod.baseline.reopen_lifetime_rate,
          },
        }),
  };
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
   * combination. AI First and reopen have no matching filter key today, so
   * they stay non-interactive rather than open a filter that quietly means
   * something narrower than the number shown.
   */
  readonly filterPatch: Partial<TicketFilters> | null;
}

function share(numerator: number, denominator: number): string {
  return denominator === 0 ? "—" : formatRate(numerator / denominator);
}

/** The numbers the ledger, the narrative and the title all read from. */
export interface LedgerScope {
  readonly eligible: number;
  readonly aiFirstCount: number;
  readonly aiFirstRate: number | null;
  readonly transferTotal: number;
  readonly reopenNumerator: number;
  readonly reopenDenominator: number;
  readonly gt4WithoutCs: number;
  readonly directCsCount: number;
  readonly resolvedFirstReply: number;
  readonly aiEndToEndCount: number;
  readonly aiReplyMeanAiFirst: number | null;
  readonly week: WeeklyReportRow | null;
  readonly kind: "week" | "all" | "selection" | "empty" | "range";
  readonly rangeFrom?: string;
  readonly rangeTo?: string;
}

/**
 * Weighted mean of a per-week average across weeks with different ai_first
 * populations. Averaging the per-week means directly would be the same
 * averaging-of-rates mistake as the rolling-rate trap: a week with 5
 * ai_first tickets and a week with 500 must not count equally.
 */
function weightedReplyMean(weeks: readonly WeeklyReportRow[]): number | null {
  let weightedSum = 0;
  let totalWeight = 0;
  for (const week of weeks) {
    if (week.ai_reply_mean_ai_first === null || week.ai_first_count === 0) {
      continue;
    }
    weightedSum += week.ai_reply_mean_ai_first * week.ai_first_count;
    totalWeight += week.ai_first_count;
  }
  return totalWeight === 0 ? null : weightedSum / totalWeight;
}

/**
 * Resolves the reporting scope to the latest observed week.
 *
 * The ledger, the narrative and the dynamic title must describe the same
 * population. Mixing a twelve-week total into the ledger while the narrative
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
    return {
      eligible: view.totals.eligible_ticket_count,
      aiFirstCount: view.ai_first.count,
      aiFirstRate: view.ai_first.rate,
      transferTotal: view.totals.transfer_total,
      reopenNumerator: view.reopen.lifetime.numerator,
      reopenDenominator: view.reopen.lifetime.denominator,
      gt4WithoutCs: view.rule_gt4.gt4_turn_without_cs,
      directCsCount: view.outcomes.direct_cs,
      resolvedFirstReply: observedWeeks.reduce(
        (total, row) => total + row.resolved_first_reply,
        0,
      ),
      aiEndToEndCount: view.outcomes.ai_end_to_end,
      aiReplyMeanAiFirst: weightedReplyMean(observedWeeks),
      week: null,
      kind: "range",
      rangeFrom: range.from,
      rangeTo: range.to,
    };
  }
  const week = selectReportWeek(view, activeWeek);
  if (week === null) {
    const observedWeeks = view.weekly.filter((row) => row.has_data);
    return {
      eligible: view.totals.eligible_ticket_count,
      aiFirstCount: view.ai_first.count,
      aiFirstRate: view.ai_first.rate,
      transferTotal: view.totals.transfer_total,
      reopenNumerator: view.reopen.lifetime.numerator,
      reopenDenominator: view.reopen.lifetime.denominator,
      gt4WithoutCs: view.rule_gt4.gt4_turn_without_cs,
      directCsCount: view.outcomes.direct_cs,
      resolvedFirstReply: observedWeeks.reduce(
        (total, row) => total + row.resolved_first_reply,
        0,
      ),
      aiEndToEndCount: view.outcomes.ai_end_to_end,
      aiReplyMeanAiFirst: weightedReplyMean(observedWeeks),
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
    directCsCount: week.direct_cs_count,
    resolvedFirstReply: week.resolved_first_reply,
    aiEndToEndCount: week.ai_end_to_end_count,
    aiReplyMeanAiFirst: week.ai_reply_mean_ai_first,
    week,
    kind: "week",
  };
}

export interface LedgerGroup {
  readonly id: "ledger-group-ticket" | "ledger-group-response";
  readonly label: string;
  /**
   * Whether the group starts folded away. SPEC-v2 §5.5 asks for exactly 4 KPI
   * above the fold at 1440x900 and says to cut ① rather than ② when there is
   * not enough room. Measured on production data, both groups expanded pushed
   * the first row of ② to y=862 -- no rows visible at all. Folding the
   * per-response group keeps every number one click away instead of dropping
   * it, and hands the ~150px back to the table.
   */
  readonly collapsed: boolean;
  /**
   * The one base every cell in the group divides by, or null when the group
   * has no single base. Group ② has none: "Xong hẳn trong 1 lượt" divides by
   * ai_end_to_end while "TB lượt/ticket AI First" divides by ai_first, so any
   * number printed here is wrong for one of the two. It used to print the
   * ai_end_to_end ticket count, which was both wrong for half the group and a
   * ticket count captioning a per-response heading.
   */
  readonly denominator: string | null;
  readonly cells: readonly LedgerCell[];
}

/**
 * Two ledger groups with two different denominators, kept apart on purpose:
 * "Theo ticket" (mẫu số là ticket) and "Theo lượt CS-agent trả lời" (mẫu số
 * là lượt AI trả lời). Mixing the two under one flat list lets a reader add a
 * ticket-count cell to a per-response-count cell, which is not a real number.
 */
export function selectLedger(
  snapshot: DashboardSnapshot,
  weekDefinition: WeekDefinition,
  activeWeek?: string,
  range?: ReportRangeScope | null,
): LedgerGroup[] {
  const scope = selectScope(snapshot, weekDefinition, activeWeek, range);
  // Named once, on the group heading. Every cell in the ticket group divides
  // by the same number, so repeating "trong N ticket tuần này" under all three
  // spends three lines saying what the caption above them already said.
  const populationLabel =
    scope.kind === "all"
      ? "ticket trong toàn kỳ"
      : scope.kind === "selection"
        ? "ticket trong các tuần đã chọn"
        : scope.kind === "range"
          ? "ticket trong khoảng ngày"
          : "ticket tuần này";

  const ticketCells: LedgerCell[] = [
    {
      id: "ledger-ai-first",
      label: "AI First",
      value: formatCount(scope.aiFirstCount),
      unit: null,
      support:
        scope.eligible === 0 ? null : share(scope.aiFirstCount, scope.eligible),
      tone: "brand",
      filterPatch: null,
    },
    {
      // The outcome the product is judged on: tickets AI closed with no human
      // in the loop. It is ticket-denominated, so it belongs in this group --
      // it previously appeared only as the caption of the collapsed group
      // below, which meant the headline number was folded away by default.
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
    },
    {
      id: "ledger-direct-cs",
      label: "Chuyển CS ngay từ đầu",
      value: formatCount(scope.directCsCount),
      unit: null,
      support:
        scope.eligible === 0 ? null : share(scope.directCsCount, scope.eligible),
      tone: "neutral",
      filterPatch:
        scope.directCsCount === 0 ? null : { outcome: "direct_cs" },
    },
    {
      id: "ledger-reopen",
      label: "Reopen sau AI First",
      // Rate leads, count supports. The absolute count rises with volume by
      // construction -- a week with more AI First tickets reopens more even
      // when nothing got worse -- so leading with it invited a false "reopen
      // is climbing" read every time traffic grew. lần/ticket is the number
      // that compares across weeks and can be held to a target. It also stops
      // this cell from looking like a fourth member of the count partition
      // above it, which it never was: those three are composition, this is
      // quality.
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
      tone: scope.reopenNumerator > 0 ? "warning" : "neutral",
      filterPatch: null,
    },
  ];

  const responseCells: LedgerCell[] = [
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
      tone: "brand",
      filterPatch: null,
    },
    {
      id: "ledger-replies-per-ticket",
      label: "TB lượt/ticket AI First",
      value:
        scope.aiReplyMeanAiFirst === null
          ? "—"
          : formatAverage(scope.aiReplyMeanAiFirst),
      unit: scope.aiReplyMeanAiFirst === null ? null : "lượt",
      support:
        scope.aiFirstCount === 0
          ? null
          : `trên ${formatCount(scope.aiFirstCount)} ticket AI First`,
      tone: "neutral",
      filterPatch: null,
    },
  ];

  return [
    {
      id: "ledger-group-ticket",
      label: "Theo ticket",
      denominator: `${formatCount(scope.eligible)} ${populationLabel}`,
      collapsed: false,
      cells: ticketCells,
    },
    {
      id: "ledger-group-response",
      label: "Theo lượt CS-agent trả lời",
      denominator: null,
      collapsed: true,
      cells: responseCells,
    },
  ];
}

/**
 * The P0 coverage floors from SPEC-v2 §5.3, which gate whether a dimension is
 * safe to slice by. Coverage below a floor does not make a number wrong; it
 * makes the *segment* view incomplete, because the missing share cannot be
 * attributed to any bucket.
 */
export const COVERAGE_FLOORS = {
  issue_category: 0.9,
  tpe: 0.85,
} as const;

export const COVERAGE_LABELS: Readonly<Record<string, string>> = {
  issue_category: "Category",
  app: "App",
  tpe: "TPE",
  intent: "Intent",
  skill: "Skill",
};

export interface CoverageDimension {
  readonly key: string;
  readonly label: string;
  readonly value: number;
  readonly floor: number | null;
  /** True only when a P0 floor exists and the measured value is under it. */
  readonly belowFloor: boolean;
}

/** Every coverage dimension, weakest first. */
export function selectCoverage(
  snapshot: DashboardSnapshot,
): CoverageDimension[] {
  return Object.entries(snapshot.coverage)
    .map(([key, value]) => {
      const floor =
        key in COVERAGE_FLOORS
          ? COVERAGE_FLOORS[key as keyof typeof COVERAGE_FLOORS]
          : null;
      return {
        key,
        label: COVERAGE_LABELS[key] ?? key,
        value,
        floor,
        belowFloor: floor !== null && value < floor,
      };
    })
    .sort((left, right) => left.value - right.value);
}

export function selectCoverageBelowFloor(
  snapshot: DashboardSnapshot,
): CoverageDimension[] {
  return selectCoverage(snapshot).filter((item) => item.belowFloor);
}

export interface AttentionItem {
  readonly id: string;
  readonly severity: "critical" | "warning";
  readonly headline: string;
  readonly action: string;
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
      action: "Mở Ticket Explorer, lọc >3 lượt xử lý để xem từng ticket.",
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

  // Coverage floors deliberately do NOT raise a rail item. They are measured
  // over every ticket in the whole period, so putting one beside a single
  // week's numbers compares two different denominators and reads as "this
  // week is broken" when nothing about this week changed (SPEC-v2 §5.13).
  // `DataTrustSection` reports them where the denominator can be stated.

  return items.slice(0, 3);
}
