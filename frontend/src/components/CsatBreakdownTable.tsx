import { useEffect, useMemo, useState } from "react";

import type { CsatWeek, Outcome } from "../lib/dashboard-schema";
import { OUTCOME_FILTER_LABELS } from "../lib/dashboard-filters";
import { PERCENTAGE_SAMPLE_MINIMUM, formatCount, formatRate, share } from "../lib/format";
import {
  type SortDirection,
  type SortValue,
  type TableSort,
  stableSortRows,
  toggleTableSort,
} from "../lib/table-sort";
import { CSAT_BUCKETS, SplitBar, guardedRate } from "./CsatCharts";
import { DataTableSortButton } from "./DataTableSortButton";
import { FilterValueButton } from "./FilterValueButton";
import chartStyles from "./csat-charts.module.css";
import csatStyles from "./csat-section.module.css";
import styles from "./dashboard.module.css";
import satisfactionStyles from "./satisfaction-badge.module.css";

export type CsatGrouping = "outcome" | "skill" | "issue_category" | "app";

export const OUTCOME_ORDER: readonly Outcome[] = [
  "ai_end_to_end",
  "ai_then_cs",
  "direct_cs",
  "unclassified",
];
const GROUP_LIMIT = 10;

export interface BreakdownRow {
  readonly value: string;
  readonly label: string;
  readonly ticket_count: number;
  readonly positive: number;
  readonly neutral: number;
  readonly negative: number;
}

export function csatGroupingLabel(grouping: CsatGrouping): string {
  if (grouping === "outcome") return "Kết quả xử lý";
  if (grouping === "skill") return "Skill";
  return grouping === "issue_category" ? "Category" : "App";
}

/**
 * Worst-first ranking shared by every breakdown table/chart: groups too small
 * to carry a rate sink below the ranked ones rather than topping the ranking
 * on one bad rating from a handful of tickets.
 */
export function sortBreakdownRows<
  R extends { readonly ticket_count: number; readonly negative: number },
>(rows: readonly R[]): R[] {
  return [...rows].sort((left, right) => {
    const leftSmall = left.ticket_count < PERCENTAGE_SAMPLE_MINIMUM;
    const rightSmall = right.ticket_count < PERCENTAGE_SAMPLE_MINIMUM;
    if (leftSmall !== rightSmall) {
      return leftSmall ? 1 : -1;
    }
    return (
      share(right.negative, right.ticket_count) - share(left.negative, left.ticket_count) ||
      right.ticket_count - left.ticket_count
    );
  });
}

/**
 * The rows behind one grouping, at response grain wherever the payload carries
 * it. Exported so the chart above the table and the table itself read from one
 * implementation and can never disagree about a group's numbers.
 */
export function rowsFor(data: CsatWeek, grouping: CsatGrouping): BreakdownRow[] {
  if (grouping === "outcome") {
    return OUTCOME_ORDER.flatMap((outcome) => {
      const counts = (data.response_by_outcome ?? data.by_outcome)[outcome];
      return counts.ticket_count === 0
        ? []
        : [{ value: outcome, label: OUTCOME_FILTER_LABELS[outcome] ?? outcome, ...counts }];
    });
  }
  const rows = (data.response_by_dimension ?? data.by_dimension)[grouping]
    .filter((row) => row.ticket_count > 0)
    .map((row) => ({ ...row, label: row.value }));
  return sortBreakdownRows(rows);
}

export function csatBreakdownOptions(
  data: CsatWeek,
  grouping: CsatGrouping,
): readonly Pick<BreakdownRow, "value" | "label">[] {
  return rowsFor(data, grouping).map(({ value, label }) => ({ value, label }));
}

export interface CsatTotals {
  readonly ticket_count: number;
  readonly positive: number;
  readonly neutral: number;
  readonly negative: number;
}

/**
 * Scope totals at response grain, falling back to ticket grain for a snapshot
 * written before `response_by_outcome` existed. Shared with the charts so the
 * headline share and the table's total row are the same arithmetic.
 */
export function csatResponseTotals(data: CsatWeek): CsatTotals {
  const byOutcome = data.response_by_outcome;
  if (byOutcome === undefined) {
    return {
      ticket_count: data.response_count,
      positive: data.positive,
      neutral: data.neutral,
      negative: data.negative,
    };
  }
  return OUTCOME_ORDER.reduce<CsatTotals>(
    (total, outcome) => ({
      ticket_count: total.ticket_count + byOutcome[outcome].ticket_count,
      positive: total.positive + byOutcome[outcome].positive,
      neutral: total.neutral + byOutcome[outcome].neutral,
      negative: total.negative + byOutcome[outcome].negative,
    }),
    { ticket_count: 0, positive: 0, neutral: 0, negative: 0 },
  );
}

const SMALL_SAMPLE_TITLE = `Mẫu dưới ${PERCENTAGE_SAMPLE_MINIMUM} phản hồi — chỉ hiện số đếm, không suy ra tỉ lệ.`;

function rateCell(count: number, denominator: number) {
  return denominator >= PERCENTAGE_SAMPLE_MINIMUM ? (
    formatRate(count / denominator)
  ) : (
    <span title={SMALL_SAMPLE_TITLE}>—</span>
  );
}

/** Bar `aria-label`: all three bucket labels, each with its count and share. */
function csatBarLabel(row: BreakdownRow): string {
  return `${row.label}: ${CSAT_BUCKETS.map(
    (bucket) =>
      `${bucket.label} ${formatCount(row[bucket.key])} (${guardedRate(row[bucket.key], row.ticket_count)})`,
  ).join(", ")}`;
}

type CsatSortKey =
  | "label"
  | "rate"
  | "ticket_count"
  | "positive_rate"
  | "neutral_rate"
  | "negative_rate";

interface CsatSortColumn {
  readonly key: CsatSortKey;
  readonly label: string;
  readonly sortable: boolean;
  readonly initialDirection: SortDirection;
  readonly className?: string | undefined;
  readonly value: (row: BreakdownRow) => SortValue;
}

/**
 * Default sort ("Rất tệ (%)" descending) reproduces the exact ranking the
 * deleted ranking-panel chart used: `stableSortRows` sinks a `null` value to
 * the bottom regardless of direction, so a small sample always lands last;
 * ties keep the source order, which `rowsFor` already breaks by ticket count.
 */
function csatSortColumns(groupingLabel: string): readonly CsatSortColumn[] {
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
      key: "ticket_count",
      label: "Phản hồi có đánh giá",
      sortable: true,
      initialDirection: "desc",
      className: styles.numeric,
      value: (row) => row.ticket_count,
    },
    {
      key: "positive_rate",
      label: "Rất hài lòng (%)",
      sortable: true,
      initialDirection: "desc",
      className: `${styles.numeric} ${satisfactionStyles.positive}`,
      value: (row) =>
        row.ticket_count >= PERCENTAGE_SAMPLE_MINIMUM
          ? share(row.positive, row.ticket_count)
          : null,
    },
    {
      key: "neutral_rate",
      label: "Bình thường (%)",
      sortable: true,
      initialDirection: "desc",
      className: `${styles.numeric} ${satisfactionStyles.neutral}`,
      value: (row) =>
        row.ticket_count >= PERCENTAGE_SAMPLE_MINIMUM
          ? share(row.neutral, row.ticket_count)
          : null,
    },
    {
      key: "negative_rate",
      label: "Rất tệ (%)",
      sortable: true,
      initialDirection: "desc",
      className: `${styles.numeric} ${satisfactionStyles.negative}`,
      value: (row) =>
        row.ticket_count >= PERCENTAGE_SAMPLE_MINIMUM
          ? share(row.negative, row.ticket_count)
          : null,
    },
  ];
}

const DEFAULT_CSAT_SORT: TableSort<CsatSortKey> = { key: "negative_rate", direction: "desc" };

/**
 * The grouping control, lifted out of the table because it now steers the
 * ranking chart too. A control that sits below what it changes reads as
 * belonging to the table alone.
 */
export function CsatGroupingField({
  grouping,
  onGroupingChange,
}: {
  readonly grouping: CsatGrouping;
  readonly onGroupingChange: (grouping: CsatGrouping) => void;
}) {
  return (
    <label className={csatStyles.groupingField} htmlFor="csatBreakdownGroupingInput">
      <span>Nhóm theo</span>
      <select
        id="csatBreakdownGroupingInput"
        value={grouping}
        onChange={(event) => onGroupingChange(event.target.value as CsatGrouping)}
      >
        <option value="outcome">Kết quả xử lý</option>
        <option value="skill">Skill</option>
        <option value="issue_category">Category</option>
        <option value="app">App</option>
      </select>
    </label>
  );
}

export interface CsatBreakdownTableProps {
  readonly data: CsatWeek;
  readonly grouping: CsatGrouping;
  readonly scopeKey: string;
  readonly onValueSelect: (grouping: CsatGrouping, value: string) => void;
}

export function CsatBreakdownTable({
  data,
  grouping,
  scopeKey,
  onValueSelect,
}: CsatBreakdownTableProps) {
  const [expanded, setExpanded] = useState(false);
  const [sort, setSort] = useState<TableSort<CsatSortKey>>(DEFAULT_CSAT_SORT);
  const rows = useMemo(() => rowsFor(data, grouping), [data, grouping]);
  const responseTotals = csatResponseTotals(data);
  const groupingLabel = csatGroupingLabel(grouping);
  const sortable = grouping !== "outcome";
  const columns = useMemo(() => csatSortColumns(groupingLabel), [groupingLabel]);
  useEffect(() => setExpanded(false), [grouping, scopeKey]);
  useEffect(() => setSort(DEFAULT_CSAT_SORT), [grouping, scopeKey]);
  // `rows` already carries the default rank (see `sortBreakdownRows`); a
  // column click re-sorts it, `outcome` keeps its fixed pipeline-stage order.
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
          id="csat-breakdown-table"
          className={`${styles.table} ${csatStyles.table}`}
          aria-describedby="csat-scope csat-breakdown-caption csat-source"
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
                  buckets={CSAT_BUCKETS}
                  counts={responseTotals}
                  total={responseTotals.ticket_count}
                  label={csatBarLabel({ ...responseTotals, value: "Tổng", label: "Tổng" })}
                />
              </td>
              <td className={styles.numeric}>
                <strong>{`${formatCount(responseTotals.ticket_count)} phản hồi`}</strong>
                <span className={csatStyles.totalSupport}>{`${formatCount(data.ticket_count)} ticket`}</span>
              </td>
              <td className={styles.numeric}>
                {rateCell(responseTotals.positive, responseTotals.ticket_count)}
              </td>
              <td className={styles.numeric}>
                {rateCell(responseTotals.neutral, responseTotals.ticket_count)}
              </td>
              <td className={styles.numeric}>
                {rateCell(responseTotals.negative, responseTotals.ticket_count)}
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
                    buckets={CSAT_BUCKETS}
                    counts={row}
                    total={row.ticket_count}
                    label={csatBarLabel(row)}
                  />
                </td>
                <td className={styles.numeric}>
                  {formatCount(row.ticket_count)}
                  {row.ticket_count < PERCENTAGE_SAMPLE_MINIMUM ? (
                    <span className={csatStyles.sampleLabel}>Mẫu nhỏ</span>
                  ) : null}
                </td>
                <td className={styles.numeric}>{rateCell(row.positive, row.ticket_count)}</td>
                <td className={styles.numeric}>{rateCell(row.neutral, row.ticket_count)}</td>
                <td className={styles.numeric}>{rateCell(row.negative, row.ticket_count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canExpand ? (
        <button
          type="button"
          className={styles.action}
          aria-controls="csat-breakdown-table"
          onClick={() => setExpanded((current) => !current)}
        >
          {showAll ? "Thu gọn" : `Xem tất cả ${formatCount(sortedRows.length)} nhóm`}
        </button>
      ) : null}
    </div>
  );
}
