import { useEffect, useMemo, useState } from "react";

import type { AiReviewBucket } from "../lib/dashboard-schema";
import { OUTCOME_FILTER_LABELS } from "../lib/dashboard-filters";
import { PERCENTAGE_SAMPLE_MINIMUM, formatCount, formatRate, share } from "../lib/format";
import {
  type SortDirection,
  type SortValue,
  type TableSort,
  stableSortRows,
  toggleTableSort,
} from "../lib/table-sort";
import { SplitBar, guardedRate } from "./CsatCharts";
import { AI_REVIEW_BUCKETS } from "./AiReviewCharts";
import { DataTableSortButton } from "./DataTableSortButton";
import { FilterValueButton } from "./FilterValueButton";
import { OUTCOME_ORDER, type CsatGrouping } from "./CsatBreakdownTable";
import chartStyles from "./csat-charts.module.css";
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
  readonly evaluated_ticket_count: number;
  readonly unrated_reviewed_ticket_count: number;
  readonly satisfied_count: number;
  readonly satisfied_with_edit_count: number;
  readonly needs_edit_count: number;
}

/**
 * The rows behind one grouping. Exported so the ranking chart and the table
 * read from one implementation and can never disagree about a group's numbers.
 *
 * Gated on `evaluated_ticket_count` (rated OR reviewed>=1), not
 * `reviewed_ticket_count` (rated AND reviewed) -- a group can be all
 * "Chưa đánh giá lại" tickets and still deserve a row.
 */
export function aiReviewRowsFor(
  data: AiReviewBucket,
  grouping: CsatGrouping,
): AiReviewBreakdownRow[] {
  if (grouping === "outcome") {
    return OUTCOME_ORDER.flatMap((outcome) => {
      const counts = data.by_outcome[outcome];
      return counts.evaluated_ticket_count === 0
        ? []
        : [{ value: outcome, label: OUTCOME_FILTER_LABELS[outcome] ?? outcome, ...counts }];
    });
  }
  const rows = data.by_dimension[grouping]
    .filter((row) => row.evaluated_ticket_count > 0)
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

/** Bar `aria-label`: all three bucket labels, each with its count and share. */
function aiReviewBarLabel(row: AiReviewBreakdownRow): string {
  return `${row.label}: ${AI_REVIEW_BUCKETS.map(
    (bucket) =>
      `${bucket.label} ${formatCount(row[bucket.key])} (${guardedRate(row[bucket.key], row.rated_ticket_count)})`,
  ).join(", ")}`;
}

type AiReviewSortKey =
  | "label"
  | "rate"
  | "reviewed_ticket_count"
  | "evaluated_ticket_count"
  | "satisfied_rate"
  | "satisfied_with_edit_rate"
  | "needs_edit_rate";

interface AiReviewSortColumn {
  readonly key: AiReviewSortKey;
  readonly label: string;
  readonly sortable: boolean;
  readonly initialDirection: SortDirection;
  readonly className?: string | undefined;
  readonly value: (row: AiReviewBreakdownRow) => SortValue;
}

/**
 * Default sort ("Cần sửa (%)" descending) reproduces the exact ranking the
 * deleted ranking-panel chart used: `stableSortRows` sinks a `null` value to
 * the bottom regardless of direction, so a small sample always lands last;
 * ties keep the source order, which `aiReviewRowsFor` already breaks by count.
 */
function aiReviewSortColumns(groupingLabel: string): readonly AiReviewSortColumn[] {
  return [
    {
      key: "label",
      label: groupingLabel,
      sortable: true,
      initialDirection: "asc",
      value: (row) => row.label,
    },
    {
      key: "rate",
      label: "Tỉ lệ",
      sortable: false,
      initialDirection: "desc",
      value: () => null,
    },
    {
      key: "reviewed_ticket_count",
      label: "Số lần hậu kiểm",
      sortable: true,
      initialDirection: "desc",
      className: styles.numeric,
      value: (row) => row.reviewed_ticket_count,
    },
    {
      key: "evaluated_ticket_count",
      label: "Đã đánh giá",
      sortable: true,
      initialDirection: "desc",
      className: styles.numeric,
      value: (row) => row.evaluated_ticket_count,
    },
    {
      key: "satisfied_rate",
      label: "Đạt (%)",
      sortable: true,
      initialDirection: "desc",
      className: `${styles.numeric} ${satisfactionStyles.positive}`,
      value: (row) =>
        row.rated_ticket_count >= PERCENTAGE_SAMPLE_MINIMUM
          ? share(row.satisfied_count, row.rated_ticket_count)
          : null,
    },
    {
      key: "satisfied_with_edit_rate",
      label: "Đạt, có sửa (%)",
      sortable: true,
      initialDirection: "desc",
      className: `${styles.numeric} ${satisfactionStyles.neutral}`,
      value: (row) =>
        row.rated_ticket_count >= PERCENTAGE_SAMPLE_MINIMUM
          ? share(row.satisfied_with_edit_count, row.rated_ticket_count)
          : null,
    },
    {
      key: "needs_edit_rate",
      label: "Cần sửa (%)",
      sortable: true,
      initialDirection: "desc",
      className: `${styles.numeric} ${satisfactionStyles.negative}`,
      value: (row) =>
        row.rated_ticket_count >= PERCENTAGE_SAMPLE_MINIMUM
          ? share(row.needs_edit_count, row.rated_ticket_count)
          : null,
    },
  ];
}

const DEFAULT_AI_REVIEW_SORT: TableSort<AiReviewSortKey> = {
  key: "needs_edit_rate",
  direction: "desc",
};

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
  const [sort, setSort] = useState<TableSort<AiReviewSortKey>>(DEFAULT_AI_REVIEW_SORT);
  const rows = useMemo(() => aiReviewRowsFor(data, grouping), [data, grouping]);
  const sortable = grouping !== "outcome";
  const columns = useMemo(() => aiReviewSortColumns(groupingLabel), [groupingLabel]);
  useEffect(() => setExpanded(false), [grouping, scopeKey]);
  useEffect(() => setSort(DEFAULT_AI_REVIEW_SORT), [grouping, scopeKey]);
  // `rows` already carries the default rank (see `aiReviewRowsFor`); a column
  // click re-sorts it, `outcome` keeps its fixed pipeline-stage order.
  const sortedRows = useMemo(() => {
    if (!sortable) {
      return rows;
    }
    const column = columns.find((item) => item.key === sort.key) ?? columns[0];
    return stableSortRows(rows, (row) => column?.value(row), sort.direction);
  }, [columns, rows, sort, sortable]);
  const showAll = expanded;
  const visibleRows = !sortable || showAll ? sortedRows : sortedRows.slice(0, GROUP_LIMIT);
  const canExpand = sortable && sortedRows.length > GROUP_LIMIT;

  return (
    <div className={csatStyles.breakdown}>
      <div className={`${styles.tableScroll} ${csatStyles.tableScroll}`}>
        <table
          id="ai-review-breakdown-table"
          className={`${styles.table} ${csatStyles.table}`}
          aria-describedby="ai-review-scope ai-review-source"
        >
          <thead>
            <tr>
              {columns.map((column, index) => {
                const active = sortable && column.sortable && sort.key === column.key;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    className={index === 0 ? styles.stickyColumn : column.className}
                    aria-sort={
                      !column.sortable
                        ? undefined
                        : active
                          ? sort.direction === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                    }
                  >
                    {sortable && column.sortable ? (
                      <DataTableSortButton
                        label={column.label}
                        active={active}
                        direction={sort.direction}
                        align={index === 0 ? "start" : "end"}
                        onClick={() =>
                          setSort((current) => toggleTableSort(current, column.key, column.initialDirection))
                        }
                      />
                    ) : (
                      column.label
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            <tr className={csatStyles.totalRow}>
              <th scope="row" className={styles.stickyColumn}>Tổng</th>
              <td className={chartStyles.tableBar}>
                <SplitBar
                  buckets={AI_REVIEW_BUCKETS}
                  counts={data}
                  total={data.rated_ticket_count}
                  label={aiReviewBarLabel({
                    value: "Tổng",
                    label: "Tổng",
                    reviewed_ticket_count: data.reviewed_ticket_count,
                    rated_ticket_count: data.rated_ticket_count,
                    evaluated_ticket_count: data.evaluated_ticket_count,
                    unrated_reviewed_ticket_count: data.unrated_reviewed_ticket_count,
                    satisfied_count: data.satisfied_count,
                    satisfied_with_edit_count: data.satisfied_with_edit_count,
                    needs_edit_count: data.needs_edit_count,
                  })}
                />
              </td>
              <td className={styles.numeric}>
                <strong>{`${formatCount(data.reviewed_ticket_count)} lần`}</strong>
              </td>
              <td className={styles.numeric}>{formatCount(data.evaluated_ticket_count)}</td>
              <td className={styles.numeric}>
                {rateCell(data.satisfied_count, data.rated_ticket_count)}
              </td>
              <td className={styles.numeric}>
                {rateCell(data.satisfied_with_edit_count, data.rated_ticket_count)}
              </td>
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
                <td className={chartStyles.tableBar}>
                  <SplitBar
                    buckets={AI_REVIEW_BUCKETS}
                    counts={row}
                    total={row.rated_ticket_count}
                    label={aiReviewBarLabel(row)}
                  />
                </td>
                <td className={styles.numeric}>
                  {`${formatCount(row.reviewed_ticket_count)} lần`}
                  {row.rated_ticket_count < PERCENTAGE_SAMPLE_MINIMUM ? (
                    <span className={csatStyles.sampleLabel}>Mẫu nhỏ</span>
                  ) : null}
                </td>
                <td className={styles.numeric}>{formatCount(row.evaluated_ticket_count)}</td>
                <td className={styles.numeric}>
                  {rateCell(row.satisfied_count, row.rated_ticket_count)}
                </td>
                <td className={styles.numeric}>
                  {rateCell(row.satisfied_with_edit_count, row.rated_ticket_count)}
                </td>
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
