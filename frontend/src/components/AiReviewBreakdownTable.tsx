import { useEffect, useMemo, useState } from "react";

import type { AiReviewBucket } from "../lib/dashboard-schema";
import { OUTCOME_FILTER_LABELS } from "../lib/dashboard-filters";
import { PERCENTAGE_SAMPLE_MINIMUM, formatCount, formatRate, share } from "../lib/format";
import { FilterValueButton } from "./FilterValueButton";
import { OUTCOME_ORDER, type CsatGrouping } from "./CsatBreakdownTable";
import csatStyles from "./csat-section.module.css";
import styles from "./dashboard.module.css";
import satisfactionStyles from "./satisfaction-badge.module.css";

const GROUP_LIMIT = 10;
const SMALL_SAMPLE_TITLE = `Mẫu dưới ${PERCENTAGE_SAMPLE_MINIMUM} ticket được hậu kiểm — chỉ hiện số đếm, không suy ra tỉ lệ.`;

export interface AiReviewBreakdownRow {
  readonly value: string;
  readonly label: string;
  readonly reviewed_ticket_count: number;
  readonly rated_ticket_count: number;
  readonly satisfied_count: number;
  readonly satisfied_with_edit_count: number;
  readonly needs_edit_count: number;
}

/**
 * The rows behind one grouping. Exported so the ranking chart and the table
 * read from one implementation and can never disagree about a group's numbers.
 */
export function aiReviewRowsFor(
  data: AiReviewBucket,
  grouping: CsatGrouping,
): AiReviewBreakdownRow[] {
  if (grouping === "outcome") {
    return OUTCOME_ORDER.flatMap((outcome) => {
      const counts = data.by_outcome[outcome];
      return counts.reviewed_ticket_count === 0
        ? []
        : [{ value: outcome, label: OUTCOME_FILTER_LABELS[outcome] ?? outcome, ...counts }];
    });
  }
  const rows = data.by_dimension[grouping]
    .filter((row) => row.reviewed_ticket_count > 0)
    .map((row) => ({ ...row, label: row.value }));
  // Worst-first, same convention as CSAT's `sortBreakdownRows`: groups too
  // small to carry a rate sink below the ranked ones rather than topping the
  // ranking on one bad rating from a handful of tickets.
  return [...rows].sort((left, right) => {
    const leftSmall = left.rated_ticket_count < PERCENTAGE_SAMPLE_MINIMUM;
    const rightSmall = right.rated_ticket_count < PERCENTAGE_SAMPLE_MINIMUM;
    if (leftSmall !== rightSmall) {
      return leftSmall ? 1 : -1;
    }
    return (
      share(right.needs_edit_count, right.rated_ticket_count) -
        share(left.needs_edit_count, left.rated_ticket_count) ||
      right.reviewed_ticket_count - left.reviewed_ticket_count
    );
  });
}

function rateCell(count: number, denominator: number) {
  return denominator >= PERCENTAGE_SAMPLE_MINIMUM ? (
    formatRate(count / denominator)
  ) : (
    <span title={SMALL_SAMPLE_TITLE}>—</span>
  );
}

export interface AiReviewBreakdownTableProps {
  readonly data: AiReviewBucket;
  readonly grouping: CsatGrouping;
  readonly scopeKey: string;
  readonly onValueSelect: (grouping: CsatGrouping, value: string) => void;
  readonly groupingLabel: string;
}

/**
 * Hậu kiểm's own breakdown table, structurally parallel to `CsatBreakdownTable`
 * but with the rate split into its own column (dash + tooltip below n<20)
 * instead of one combined "count · rate" cell -- CSAT's cell packs the two
 * together because its rate always has the same denominator as the row's
 * headline count, but hậu kiểm's rate denominator (`rated_ticket_count`) and
 * count denominator (`reviewed_ticket_count`) are two different things, so
 * showing the same "—" against a nonzero count would misread as no reviews.
 */
export function AiReviewBreakdownTable({
  data,
  grouping,
  scopeKey,
  onValueSelect,
  groupingLabel,
}: AiReviewBreakdownTableProps) {
  const [expanded, setExpanded] = useState(false);
  const rows = useMemo(() => aiReviewRowsFor(data, grouping), [data, grouping]);
  useEffect(() => setExpanded(false), [grouping, scopeKey]);
  const showAll = expanded;
  const visibleRows = grouping === "outcome" || showAll ? rows : rows.slice(0, GROUP_LIMIT);
  const canExpand = grouping !== "outcome" && rows.length > GROUP_LIMIT;

  return (
    <div className={csatStyles.breakdown}>
      <p id="ai-review-breakdown-caption" className={styles.sectionNote}>
        Mẫu số tỉ lệ là ticket có nhãn hậu kiểm (`rated_ticket_count`), khác mẫu số cột đếm.
      </p>
      <div className={`${styles.tableScroll} ${csatStyles.tableScroll}`}>
        <table
          id="ai-review-breakdown-table"
          className={`${styles.table} ${csatStyles.table}`}
          aria-describedby="ai-review-scope ai-review-breakdown-caption ai-review-source"
        >
          <thead>
            <tr>
              <th scope="col">{groupingLabel}</th>
              <th scope="col" className={styles.numeric}>Đã hậu kiểm</th>
              <th scope="col" className={`${styles.numeric} ${satisfactionStyles.positive}`}>Đạt (n)</th>
              <th scope="col" className={`${styles.numeric} ${satisfactionStyles.positive}`}>Đạt (%)</th>
              <th scope="col" className={`${styles.numeric} ${satisfactionStyles.neutral}`}>Đạt, có sửa (n)</th>
              <th scope="col" className={`${styles.numeric} ${satisfactionStyles.neutral}`}>Đạt, có sửa (%)</th>
              <th scope="col" className={`${styles.numeric} ${satisfactionStyles.negative}`}>Cần sửa (n)</th>
              <th scope="col" className={`${styles.numeric} ${satisfactionStyles.negative}`}>Cần sửa (%)</th>
            </tr>
          </thead>
          <tbody>
            <tr className={csatStyles.totalRow}>
              <th scope="row" className={styles.stickyColumn}>Tổng</th>
              <td className={styles.numeric}>
                <strong>{`${formatCount(data.reviewed_ticket_count)} ticket`}</strong>
              </td>
              <td className={styles.numeric}>{formatCount(data.satisfied_count)}</td>
              <td className={styles.numeric}>
                {rateCell(data.satisfied_count, data.rated_ticket_count)}
              </td>
              <td className={styles.numeric}>{formatCount(data.satisfied_with_edit_count)}</td>
              <td className={styles.numeric}>
                {rateCell(data.satisfied_with_edit_count, data.rated_ticket_count)}
              </td>
              <td className={styles.numeric}>{formatCount(data.needs_edit_count)}</td>
              <td className={styles.numeric}>
                {rateCell(data.needs_edit_count, data.rated_ticket_count)}
              </td>
            </tr>
            {visibleRows.map((row) => (
              <tr key={`${grouping}:${row.value}`}>
                <th scope="row" className={styles.stickyColumn}>
                  <FilterValueButton
                    label={row.label}
                    filterLabel={groupingLabel}
                    onClick={() => onValueSelect(grouping, row.value)}
                  />
                </th>
                <td className={styles.numeric}>
                  {formatCount(row.reviewed_ticket_count)}
                  {row.rated_ticket_count < PERCENTAGE_SAMPLE_MINIMUM ? (
                    <span className={csatStyles.sampleLabel}>Mẫu nhỏ</span>
                  ) : null}
                </td>
                <td className={styles.numeric}>{formatCount(row.satisfied_count)}</td>
                <td className={styles.numeric}>
                  {rateCell(row.satisfied_count, row.rated_ticket_count)}
                </td>
                <td className={styles.numeric}>{formatCount(row.satisfied_with_edit_count)}</td>
                <td className={styles.numeric}>
                  {rateCell(row.satisfied_with_edit_count, row.rated_ticket_count)}
                </td>
                <td className={styles.numeric}>{formatCount(row.needs_edit_count)}</td>
                <td className={styles.numeric}>
                  {rateCell(row.needs_edit_count, row.rated_ticket_count)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canExpand ? (
        <button
          type="button"
          className={styles.action}
          aria-controls="ai-review-breakdown-table"
          onClick={() => setExpanded((current) => !current)}
        >
          {showAll ? "Thu gọn" : `Xem tất cả ${formatCount(rows.length)} nhóm`}
        </button>
      ) : null}
    </div>
  );
}
