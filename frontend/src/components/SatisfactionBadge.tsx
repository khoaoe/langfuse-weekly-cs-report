import type { TicketRow } from "../lib/dashboard-schema";
import { csatSatisfactionLabel } from "../lib/csat-labels";
import badgeStyles from "./satisfaction-badge.module.css";

const CLASS_BY_STATE: Readonly<
  Record<NonNullable<TicketRow["csat_satisfaction"]>, string>
> = {
  positive: badgeStyles.positive ?? "",
  neutral: badgeStyles.neutral ?? "",
  negative: badgeStyles.negative ?? "",
  unrated: badgeStyles.unrated ?? "",
};

export function SatisfactionBadge({
  value,
}: {
  readonly value: TicketRow["csat_satisfaction"];
}) {
  if (value === null) {
    return <>—</>;
  }
  return (
    <span
      className={`${badgeStyles.badge} ${CLASS_BY_STATE[value]}`}
      data-satisfaction={value}
    >
      {csatSatisfactionLabel(value)}
    </span>
  );
}
