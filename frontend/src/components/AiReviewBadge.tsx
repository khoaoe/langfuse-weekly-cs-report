import type { TicketRow } from "../lib/dashboard-schema";
import { aiReviewRatingLabel } from "../lib/ai-review-labels";
import badgeStyles from "./satisfaction-badge.module.css";

const CLASS_BY_STATE: Readonly<
  Record<NonNullable<TicketRow["ai_review_rating"]>, string>
> = {
  satisfied: badgeStyles.positive ?? "",
  satisfied_with_edit: badgeStyles.neutral ?? "",
  needs_edit: badgeStyles.negative ?? "",
};

export function AiReviewBadge({
  value,
}: {
  readonly value: TicketRow["ai_review_rating"];
}) {
  if (value === null) {
    return <>—</>;
  }
  return (
    <span
      className={`${badgeStyles.badge} ${CLASS_BY_STATE[value]}`}
      data-ai-review={value}
    >
      {aiReviewRatingLabel(value)}
    </span>
  );
}
