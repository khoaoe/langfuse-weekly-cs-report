import type { TransferTriggerReason, WeekDefinition } from "./dashboard-schema";
import { csatSatisfactionLabel } from "./csat-labels";
import { formatWeekRange } from "./format";
import { transferReasonLabel } from "./transfer-copy";

export interface TicketFilters {
  readonly cohort_week: string;
  /** Comma-separated report weeks used only by the global multi-week scope. */
  readonly cohort_weeks: string;
  readonly outcome: string;
  readonly csat_satisfaction: string;
  readonly ticket_id: string;
  readonly issue_category: string;
  readonly app: string;
  readonly product_code: string;
  readonly skill: string;
  readonly intent: string;
  readonly tpe_code: string;
  readonly transfer_reason: string;
  readonly gt4_turn: string;
  readonly transferred: string;
  readonly is_weekend_start: string;
}

export type TicketFilterKey = keyof TicketFilters;

export const EMPTY_TICKET_FILTERS: TicketFilters = Object.freeze({
  cohort_week: "",
  cohort_weeks: "",
  outcome: "",
  csat_satisfaction: "",
  ticket_id: "",
  issue_category: "",
  app: "",
  product_code: "",
  skill: "",
  intent: "",
  tpe_code: "",
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
    Exclude<TicketFilterKey, "cohort_week" | "cohort_weeks" | "outcome">,
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
  transfer_reason: "Lý do chuyển CS",
  gt4_turn: ">3 lượt xử lý",
  transferred: "Đã chuyển CS",
  is_weekend_start: "Bắt đầu cuối tuần",
};

const CHIP_ORDER: readonly TicketFilterKey[] = [
  "cohort_week",
  "cohort_weeks",
  "ticket_id",
  "outcome",
  "csat_satisfaction",
  "issue_category",
  "app",
  "product_code",
  "skill",
  "intent",
  "tpe_code",
  "transfer_reason",
  "gt4_turn",
  "transferred",
  "is_weekend_start",
];

export interface ActiveFilterChip {
  readonly key: TicketFilterKey;
  readonly label: string;
}

export function updateTicketFilters(
  current: TicketFilters,
  patch: Partial<TicketFilters>,
): TicketFilters {
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
  return CHIP_ORDER.flatMap((key) => {
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
