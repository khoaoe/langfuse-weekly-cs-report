import type { TicketRow } from "./dashboard-schema";

export type AiReviewRating = NonNullable<TicketRow["ai_review_rating"]>;

export const AI_REVIEW_RATING_LABELS: Readonly<Record<AiReviewRating, string>> = {
  satisfied: "Đạt",
  satisfied_with_edit: "Đạt, có sửa",
  needs_edit: "Cần sửa",
};

export function aiReviewRatingLabel(
  value: TicketRow["ai_review_rating"],
): string {
  return value === null ? "—" : AI_REVIEW_RATING_LABELS[value];
}

export const AI_REVIEW_RATING_OPTIONS: readonly {
  readonly value: AiReviewRating;
  readonly label: string;
}[] = (
  ["satisfied", "satisfied_with_edit", "needs_edit"] as const
).map((value) => ({ value, label: AI_REVIEW_RATING_LABELS[value] }));
