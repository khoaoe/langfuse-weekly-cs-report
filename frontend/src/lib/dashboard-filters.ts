import type { TransferTriggerReason, WeekDefinition } from "./dashboard-schema";
import { csatSatisfactionLabel } from "./csat-labels";
import { formatDateRangeLabel, formatWeekRange } from "./format";
import { transferReasonLabel } from "./transfer-copy";

export interface TicketFilters {
  readonly cohort_week: string;
  /** Comma-separated report weeks used only by the global multi-week scope. */
  readonly cohort_weeks: string;
  /** ISO date (YYYY-MM-DD), inclusive. Mutually exclusive with cohort_week/cohort_weeks. */
  readonly opened_from: string;
  /** ISO date (YYYY-MM-DD), inclusive. Mutually exclusive with cohort_week/cohort_weeks. */
  readonly opened_to: string;
  readonly outcome: string;
  readonly csat_satisfaction: string;
  readonly ticket_id: string;
  readonly issue_category: string;
  readonly app: string;
  readonly product_code: string;
  readonly skill: string;
  readonly intent: string;
  readonly tpe_code: string;
  readonly model_core: string;
  readonly transfer_reason: string;
  readonly gt4_turn: string;
  readonly transferred: string;
  readonly is_weekend_start: string;
}

export type TicketFilterKey = keyof TicketFilters;

export const EMPTY_TICKET_FILTERS: TicketFilters = Object.freeze({
  cohort_week: "",
  cohort_weeks: "",
  opened_from: "",
  opened_to: "",
  outcome: "",
  csat_satisfaction: "",
  ticket_id: "",
  issue_category: "",
  app: "",
  product_code: "",
  skill: "",
  intent: "",
  tpe_code: "",
  model_core: "",
  transfer_reason: "",
  gt4_turn: "",
  transferred: "",
  is_weekend_start: "",
});

export const OUTCOME_FILTER_LABELS: Readonly<Record<string, string>> = {
  ai_end_to_end: "AI xử lý trọn",
  ai_then_cs: "AI trả lời rồi chuyển CS",
  direct_cs: "Chuyển CS ngay từ đầu",
  unclassified: "Chưa phân loại",
};

const FILTER_LABELS: Readonly<
  Record<
    Exclude<
      TicketFilterKey,
      "cohort_week" | "cohort_weeks" | "opened_from" | "opened_to" | "outcome"
    >,
    string
  >
> = {
  ticket_id: "Ticket ID",
  csat_satisfaction: "Mức độ hài lòng (CS Agent)",
  issue_category: "Category",
  app: "App",
  product_code: "Product Code",
  skill: "Skill",
  intent: "Intent",
  tpe_code: "Transstatus",
  model_core: "Model",
  transfer_reason: "Lý do chuyển CS",
  gt4_turn: ">3 lượt xử lý",
  transferred: "Đã chuyển CS",
  is_weekend_start: "Bắt đầu cuối tuần",
};

const CHIP_ORDER: readonly TicketFilterKey[] = [
  "cohort_week",
  "cohort_weeks",
  "opened_from",
  "ticket_id",
  "outcome",
  "csat_satisfaction",
  "issue_category",
  "app",
  "product_code",
  "skill",
  "intent",
  "tpe_code",
  "model_core",
  "transfer_reason",
  "gt4_turn",
  "transferred",
  "is_weekend_start",
];

export interface ActiveFilterChip {
  readonly key: TicketFilterKey;
  readonly label: string;
  /** Keys to clear together when this chip's remove button is clicked.
   * Defaults to just `key` when omitted (see the combined date-range chip). */
  readonly clearKeys?: readonly TicketFilterKey[];
}

export interface TpeOptionSource {
  readonly transstatus: string;
  readonly step_result: string | null;
  readonly status: string | null;
}

const TPE_UNCLASSIFIED_STATUS_LABEL = "Chưa phân loại";
const TPE_MISSING_STEP_RESULT_LABEL = "—";

/**
 * Labels a Transstatus dropdown option for the Ticket Explorer, a dev/CS
 * investigation tool. Unlike the C-level narrative sentence, the raw code
 * pair stays visible in parentheses next to the resolved status so an
 * investigator can still cross-reference the taxonomy directly.
 */
export function tpeOptionLabel(item: TpeOptionSource): string {
  const statusLabel = item.status ?? TPE_UNCLASSIFIED_STATUS_LABEL;
  const stepResult = item.step_result ?? TPE_MISSING_STEP_RESULT_LABEL;
  return `${statusLabel} (${item.transstatus} / ${stepResult})`;
}

/**
 * Picks the representative `(transstatus, step_result)` row for a dropdown
 * option keyed only by `transstatus`. A single transstatus code can carry
 * more than one step_result; `tpe` rows arrive sorted by count descending, so
 * the top match is the most common pairing for that code.
 *
 * Some codes resolve to more than one distinct governed status depending on
 * step_result (e.g. `-365` splits across FAILED_FACE_AUTH, WAITING_NFC_REVIEW,
 * FAILED_NFC, ... with no majority). The dropdown option still filters by
 * `transstatus` alone, so labelling it with just the top row's status would
 * assert one specific status for ticket volume that is really spread across
 * several — worse than showing the raw code. When a code is ambiguous like
 * this, return undefined so the caller falls back to the raw code instead of
 * picking a single (misleading) status to display.
 */
export function findTpeOptionSource(
  transstatus: string,
  tpe: readonly TpeOptionSource[],
): TpeOptionSource | undefined {
  const matches = tpe.filter((item) => item.transstatus === transstatus);
  if (matches.length === 0) {
    return undefined;
  }
  const distinctStatuses = new Set(
    matches
      .map((item) => item.status)
      .filter((status): status is string => status !== null),
  );
  if (distinctStatuses.size > 1) {
    return undefined;
  }
  return matches[0];
}

/**
 * The week filter (`cohort_week`/`cohort_weeks`) and the opened-date range
 * filter (`opened_from`/`opened_to`) are mutually exclusive: picking one
 * clears the other, so only one scoping mechanism is ever active.
 */
export function updateTicketFilters(
  current: TicketFilters,
  patch: Partial<TicketFilters>,
): TicketFilters {
  const setsWeekFilter =
    (patch.cohort_week !== undefined && patch.cohort_week !== "") ||
    (patch.cohort_weeks !== undefined && patch.cohort_weeks !== "");
  const setsDateRangeFilter =
    (patch.opened_from !== undefined && patch.opened_from !== "") ||
    (patch.opened_to !== undefined && patch.opened_to !== "");
  if (setsWeekFilter) {
    return { ...current, opened_from: "", opened_to: "", ...patch };
  }
  if (setsDateRangeFilter) {
    return { ...current, cohort_week: "", cohort_weeks: "", ...patch };
  }
  return { ...current, ...patch };
}

function displayFilterValue(
  key: TicketFilterKey,
  value: string,
  weekDefinition: WeekDefinition,
): string {
  if (key === "cohort_week") {
    return formatWeekRange(value, weekDefinition);
  }
  if (key === "cohort_weeks") {
    return `${value.split(",").filter(Boolean).length} tuần đã chọn`;
  }
  if (key === "outcome") {
    return OUTCOME_FILTER_LABELS[value] ?? value;
  }
  if (key === "csat_satisfaction") {
    return csatSatisfactionLabel(
      value as "positive" | "neutral" | "negative" | "unrated",
    );
  }
  if (key === "transfer_reason") {
    return transferReasonLabel(value as TransferTriggerReason);
  }
  if (
    key === "gt4_turn" ||
    key === "transferred" ||
    key === "is_weekend_start"
  ) {
    return value === "true" ? "Có" : "Không";
  }
  return value;
}

export function activeTicketFilterChips(
  filters: TicketFilters,
  weekDefinition: WeekDefinition,
): ActiveFilterChip[] {
  return CHIP_ORDER.flatMap((key): ActiveFilterChip[] => {
    if (key === "opened_from") {
      if (filters.opened_from === "" && filters.opened_to === "") {
        return [];
      }
      return [
        {
          key: "opened_from",
          label: `Ngày mở: ${formatDateRangeLabel(filters.opened_from, filters.opened_to)}`,
          clearKeys: ["opened_from", "opened_to"],
        },
      ];
    }
    if (key === "opened_to") {
      return [];
    }
    const value = filters[key];
    if (value === "") {
      return [];
    }
    const label =
      key === "cohort_week" || key === "cohort_weeks"
        ? "Tuần"
        : key === "outcome"
          ? "Kết quả"
          : FILTER_LABELS[key];
    return [
      {
        key,
        label: `${label}: ${displayFilterValue(key, value, weekDefinition)}`,
      },
    ];
  });
}
