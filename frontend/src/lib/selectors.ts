import type {
  DashboardSnapshot,
  DashboardView,
  WeekDefinition,
  WeeklyReportRow,
} from "./dashboard-schema";
import type { TicketFilters } from "./dashboard-filters";
import type { NarrativeInput, NarrativeSignal } from "./narrative";
import { formatCount, formatRate } from "./format";

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

/**
 * Observed transfer signals, most frequent first.
 *
 * TPE codes are operational observations, not proven causes.  Only rows the
 * taxonomy could resolve carry a signal: a raw code means nothing to a CS or
 * exec reader, and this string is copied into their own reports verbatim.
 * Unresolved rows stay in the diagnostics table, where the count is the point.
 */
export function selectTransferSignals(view: {
  readonly transfer_reasons: DashboardView["transfer_reasons"];
}): NarrativeSignal[] {
  const tpe = view.transfer_reasons.tpe
    .filter((item) => item.status !== null)
    .map((item) => ({ label: item.status as string, count: item.count }));
  return tpe.sort((left, right) => right.count - left.count);
}

export function buildNarrativeInput(
  snapshot: DashboardSnapshot,
  weekDefinition: WeekDefinition,
  activeWeek?: string,
): NarrativeInput {
  const view = selectView(snapshot, weekDefinition);
  const current = selectReportWeek(view, activeWeek);
  const previous = selectPreviousWeek(view, current);
  // Signals for the week being described, falling back to the whole range only
  // when the payload carries no per-week breakdown.
  const scopedTransfer =
    current === null ? view : (view.by_week[current.cohort_week] ?? view);
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
    transferSignals: selectTransferSignals(scopedTransfer),
    transferDenominator:
      scopedTransfer.transfer_reasons.observed_transfer_denominator,
    gt4TurnWithoutCs:
      current?.gt4_turn_without_cs ?? view.rule_gt4.gt4_turn_without_cs,
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

export const COVERAGE_LABELS: Readonly<Record<string, string>> = {
  issue_category: "Category",
  app: "App",
  product_code: "Product Code",
  tpe: "Transstatus",
  intent: "Intent",
  skill: "Skill",
};

export function coverageLabel(name: string): string {
  return COVERAGE_LABELS[name] ?? name;
}

/** Below this share, a coverage dimension is unsafe to act on. */
const COVERAGE_BADGE_FLOOR = 0.8;

export interface WeakestCoverage {
  readonly name: string;
  readonly label: string;
  readonly missingShare: number;
}

/**
 * The single coverage dimension that most needs a reader's attention.
 *
 * A blended score across five unlike quantities (structural validity,
 * Category, Transstatus, Skill, freshness) tells the reader a number without
 * telling them what to do about it. Naming the weakest dimension does. Null
 * when every dimension already clears the floor — nothing to name.
 */
export function selectWeakestCoverage(
  snapshot: DashboardSnapshot,
): WeakestCoverage | null {
  let weakestName: string | null = null;
  let weakestValue = 1;
  for (const [name, value] of Object.entries(snapshot.coverage)) {
    if (value < COVERAGE_BADGE_FLOOR && value < weakestValue) {
      weakestName = name;
      weakestValue = value;
    }
  }
  return weakestName === null
    ? null
    : {
        name: weakestName,
        label: coverageLabel(weakestName),
        missingShare: 1 - weakestValue,
      };
}

export type LedgerTone = "brand" | "neutral" | "warning" | "critical";

export interface LedgerCell {
  readonly id: string;
  readonly label: string;
  readonly value: string;
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
  readonly week: WeeklyReportRow | null;
  readonly kind: "week" | "all" | "selection" | "empty";
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
): LedgerScope {
  const view = selectView(snapshot, weekDefinition);
  const week = selectReportWeek(view, activeWeek);
  if (week === null) {
    return {
      eligible: view.totals.eligible_ticket_count,
      aiFirstCount: view.ai_first.count,
      aiFirstRate: view.ai_first.rate,
      transferTotal: view.totals.transfer_total,
      reopenNumerator: view.reopen.lifetime.numerator,
      reopenDenominator: view.reopen.lifetime.denominator,
      gt4WithoutCs: view.rule_gt4.gt4_turn_without_cs,
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
    week,
    kind: "week",
  };
}

/**
 * The four cells of the decision ledger, in decision order: how much the agent
 * handled, how much left it, how much came back, and where users may be stuck.
 */
export function selectLedger(
  snapshot: DashboardSnapshot,
  weekDefinition: WeekDefinition,
  activeWeek?: string,
): LedgerCell[] {
  const scope = selectScope(snapshot, weekDefinition, activeWeek);
  const populationLabel =
    scope.kind === "all"
      ? "ticket trong toàn kỳ"
      : scope.kind === "selection"
        ? "ticket trong các tuần đã chọn"
        : "ticket tuần này";

  return [
    {
      id: "ledger-ai-first",
      label: "AI First",
      value: formatCount(scope.aiFirstCount),
      support:
        scope.eligible === 0
          ? null
          : `${share(scope.aiFirstCount, scope.eligible)} trong ${formatCount(
              scope.eligible,
            )} ${populationLabel}`,
      tone: "brand",
      filterPatch: null,
    },
    {
      id: "ledger-transfer",
      label: "Tổng chuyển CS",
      value: formatCount(scope.transferTotal),
      support:
        scope.eligible === 0
          ? null
          : `${share(scope.transferTotal, scope.eligible)} trong ${formatCount(
              scope.eligible,
            )} ${populationLabel}`,
      tone: "neutral",
      filterPatch: scope.transferTotal === 0 ? null : { transferred: "true" },
    },
    {
      id: "ledger-reopen",
      label: "Reopen sau AI First",
      value: formatCount(scope.reopenNumerator),
      support:
        scope.reopenDenominator === 0
          ? null
          : `${share(
              scope.reopenNumerator,
              scope.reopenDenominator,
            )} trong ${formatCount(scope.reopenDenominator)} ticket AI First`,
      tone: scope.reopenNumerator > 0 ? "warning" : "neutral",
      filterPatch: null,
    },
    {
      id: "ledger-gt4",
      label: ">3 lượt xử lý chưa chuyển CS",
      value: formatCount(scope.gt4WithoutCs),
      support:
        scope.gt4WithoutCs === 0 || scope.eligible === 0
          ? null
          : `${share(scope.gt4WithoutCs, scope.eligible)} trong ${formatCount(
              scope.eligible,
            )} ${populationLabel}`,
      tone: scope.gt4WithoutCs > 0 ? "critical" : "neutral",
      filterPatch:
        scope.gt4WithoutCs === 0
          ? null
          : { gt4_turn: "true", transferred: "false" },
    },
  ];
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
): AttentionItem[] {
  const scope = selectScope(snapshot, weekDefinition, activeWeek);
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

  return items.slice(0, 3);
}
