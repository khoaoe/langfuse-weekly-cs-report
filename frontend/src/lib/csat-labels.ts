import type { TicketRow } from "./dashboard-schema";

export type CsatSatisfaction = NonNullable<TicketRow["csat_satisfaction"]>;

export const CSAT_SATISFACTION_LABELS: Readonly<
  Record<CsatSatisfaction, string>
> = {
  positive: "Rất hài lòng",
  neutral: "Bình thường",
  negative: "Rất tệ",
  unrated: "Chưa có đánh giá",
};

export const CSAT_SATISFACTION_OPTIONS: readonly {
  readonly value: CsatSatisfaction;
  readonly label: string;
}[] = (["positive", "neutral", "negative", "unrated"] as const).map(
  (value) => ({ value, label: CSAT_SATISFACTION_LABELS[value] }),
);

export function csatSatisfactionLabel(
  value: TicketRow["csat_satisfaction"],
): string {
  return value === null ? "—" : CSAT_SATISFACTION_LABELS[value];
}
