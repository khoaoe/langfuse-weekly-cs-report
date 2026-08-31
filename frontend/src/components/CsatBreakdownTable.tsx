import { useEffect, useMemo, useState } from "react";

import type { CsatWeek, Outcome } from "../lib/dashboard-schema";
import { OUTCOME_FILTER_LABELS } from "../lib/dashboard-filters";
import { PERCENTAGE_SAMPLE_MINIMUM, formatCount, formatRate } from "../lib/format";
import { FilterValueButton } from "./FilterValueButton";
import csatStyles from "./csat-section.module.css";
import styles from "./dashboard.module.css";
import satisfactionStyles from "./satisfaction-badge.module.css";

export type CsatGrouping = "outcome" | "skill" | "issue_category";

const OUTCOME_ORDER: readonly Outcome[] = [
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
  return grouping === "skill" ? "Skill" : "Category";
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
  return (data.response_by_dimension ?? data.by_dimension)[grouping]
    .filter((row) => row.ticket_count > 0)
    .map((row) => ({ ...row, label: row.value }));
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

function ratingCell(count: number, denominator: number) {
  return denominator >= PERCENTAGE_SAMPLE_MINIMUM
    ? `${formatCount(count)} · ${formatRate(count / denominator)}`
    : formatCount(count);
}

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
  const rows = useMemo(() => rowsFor(data, grouping), [data, grouping]);
  const responseTotals = csatResponseTotals(data);
  useEffect(() => setExpanded(false), [grouping, scopeKey]);
  const showAll = expanded;
  const visibleRows = grouping === "outcome" || showAll ? rows : rows.slice(0, GROUP_LIMIT);
  const canExpand = grouping !== "outcome" && rows.length > GROUP_LIMIT;

  return (
    <div className={csatStyles.breakdown}>
      <p id="csat-breakdown-caption" className={styles.sectionNote}>
        Mỗi phản hồi survey được tính một lần.
      </p>
      <div className={`${styles.tableScroll} ${csatStyles.tableScroll}`}>
        <table
          id="csat-breakdown-table"
          className={`${styles.table} ${csatStyles.table}`}
          aria-describedby="csat-scope csat-breakdown-caption csat-source"
        >
          <thead>
            <tr>
              <th scope="col">{csatGroupingLabel(grouping)}</th>
              <th scope="col" className={styles.numeric}>Phản hồi có đánh giá</th>
              <th
                scope="col"
                className={`${styles.numeric} ${satisfactionStyles.positive}`}
              >
                Rất hài lòng
              </th>
              <th
                scope="col"
                className={`${styles.numeric} ${satisfactionStyles.neutral}`}
              >
                Bình thường
              </th>
              <th
                scope="col"
                className={`${styles.numeric} ${satisfactionStyles.negative}`}
              >
                Rất tệ
              </th>
            </tr>
          </thead>
          <tbody>
            <tr className={csatStyles.totalRow}>
              <th scope="row" className={styles.stickyColumn}>Tổng</th>
              <td className={styles.numeric}>
                <strong>{`${formatCount(responseTotals.ticket_count)} phản hồi`}</strong>
                <span className={csatStyles.totalSupport}>{`${formatCount(data.ticket_count)} ticket`}</span>
              </td>
              <td className={styles.numeric}>
                {ratingCell(responseTotals.positive, responseTotals.ticket_count)}
              </td>
              <td className={styles.numeric}>
                {ratingCell(responseTotals.neutral, responseTotals.ticket_count)}
              </td>
              <td className={styles.numeric}>
                {ratingCell(responseTotals.negative, responseTotals.ticket_count)}
              </td>
            </tr>
            {visibleRows.map((row) => (
              <tr key={`${grouping}:${row.value}`}>
                <th scope="row" className={styles.stickyColumn}>
                  <FilterValueButton
                    label={row.label}
                    filterLabel={csatGroupingLabel(grouping)}
                    onClick={() => onValueSelect(grouping, row.value)}
                  />
                </th>
                <td className={styles.numeric}>
                  {formatCount(row.ticket_count)}
                  {row.ticket_count < PERCENTAGE_SAMPLE_MINIMUM ? (
                    <span className={csatStyles.sampleLabel}>Mẫu nhỏ</span>
                  ) : null}
                </td>
                <td className={styles.numeric}>
                  {ratingCell(row.positive, row.ticket_count)}
                </td>
                <td className={styles.numeric}>
                  {ratingCell(row.neutral, row.ticket_count)}
                </td>
                <td className={styles.numeric}>
                  {ratingCell(row.negative, row.ticket_count)}
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
          aria-controls="csat-breakdown-table"
          onClick={() => setExpanded((current) => !current)}
        >
          {showAll ? "Thu gọn" : `Xem tất cả ${formatCount(rows.length)} nhóm`}
        </button>
      ) : null}
    </div>
  );
}
