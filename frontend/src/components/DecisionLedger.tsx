import type { DashboardSnapshot, WeekDefinition } from "../lib/dashboard-schema";
import type { TicketFilters } from "../lib/dashboard-filters";
import {
  dateRangeSpanDays,
  formatCount,
  formatDateRangeLabel,
  formatWeekRange,
} from "../lib/format";
import {
  COHORT_LABELS,
  selectAttentionItems,
  selectLedger,
  selectScope,
  selectView,
  type LedgerCell,
  type ReportRangeScope,
} from "../lib/selectors";
import styles from "./dashboard.module.css";

export interface DecisionLedgerProps {
  readonly snapshot: DashboardSnapshot;
  readonly weekDefinition: WeekDefinition;
  readonly activeWeek?: string;
  readonly reportRange?: ReportRangeScope | null;
  readonly onCellSelect?: (patch: Partial<TicketFilters>) => void;
}

const TONE_CLASS = {
  brand: styles.toneBrand,
  warning: styles.toneWarning,
  critical: styles.toneCritical,
  neutral: "",
} as const;

/**
 * The signature surface: dynamic title, four headline cells with their deltas,
 * one secondary row and only the warnings an operator can act on.
 */
export function DecisionLedger({
  snapshot,
  weekDefinition,
  activeWeek,
  reportRange = null,
  onCellSelect,
}: DecisionLedgerProps) {
  const view = selectView(snapshot, weekDefinition);
  const scope = selectScope(snapshot, weekDefinition, activeWeek, reportRange);
  const latest = scope.week;
  const groups = selectLedger(snapshot, weekDefinition, activeWeek, reportRange);
  const attention = selectAttentionItems(
    snapshot,
    weekDefinition,
    activeWeek,
    reportRange,
  );
  const rangeSpanDays =
    scope.kind === "range"
      ? dateRangeSpanDays(scope.rangeFrom, scope.rangeTo)
      : null;

  const [primary, secondary] = groups;

  function cellBody(cell: LedgerCell) {
    return (
      <>
        <span className={styles.ledgerLabel}>{cell.label}</span>
        <span className={styles.ledgerValue}>
          {cell.value}
          {cell.unit === null ? null : (
            <>
              {" "}
              <span className={styles.ledgerUnit}>{cell.unit}</span>
            </>
          )}
        </span>
        {cell.support === null ? null : (
          <span className={styles.ledgerSupport}>{cell.support}</span>
        )}
        {cell.delta === null ? null : (
          <span
            className={`${styles.ledgerDelta} ${
              cell.delta.tone === "warning" ? styles.ledgerDeltaWarning : ""
            }`}
          >
            {cell.delta.text}
          </span>
        )}
      </>
    );
  }

  function renderCell(cell: LedgerCell, className: string | undefined) {
    return (
      <div
        key={cell.id}
        id={cell.id}
        className={`${className ?? ""} ${TONE_CLASS[cell.tone]}`}
      >
        {cell.filterPatch === null || onCellSelect === undefined ? (
          cellBody(cell)
        ) : (
          <button
            type="button"
            className={styles.ledgerCellButton}
            onClick={() => onCellSelect(cell.filterPatch as Partial<TicketFilters>)}
          >
            {cellBody(cell)}
          </button>
        )}
      </div>
    );
  }

  return (
    <section className={styles.decision} aria-labelledby="dynamicTitle">
      <div
        className={styles.decisionBand}
        role="group"
        aria-label="Tóm tắt quyết định"
      >
        <div className={styles.headline}>
          <h1 id="dynamicTitle" className={styles.title}>
            {COHORT_LABELS[weekDefinition]}
            {scope.kind === "all"
              ? " · toàn bộ kỳ báo cáo"
              : scope.kind === "selection"
                ? ` · ${formatCount(
                    view.weekly.filter((week) => week.has_data).length,
                  )} tuần đã chọn`
                : scope.kind === "range"
                  ? ` · ${formatDateRangeLabel(
                      scope.rangeFrom ?? "",
                      scope.rangeTo ?? "",
                    )}${
                      rangeSpanDays === null
                        ? ""
                        : ` · ${formatCount(rangeSpanDays)} ngày`
                    }`
                  : latest === null
                    ? ""
                    : ` · tuần ${formatWeekRange(latest.cohort_week, weekDefinition)}`}
            {` · ${formatCount(scope.eligible)} ticket`}
          </h1>
        </div>

        <div className={styles.ledgerGroup}>
          {scope.kind === "empty" ? (
            <p
              id="ledger-scope"
              className={`${styles.tableCaption} ${styles.ledgerScope}`}
            >
              {`Chưa có tuần nào có dữ liệu; các ô dưới đây là tổng ${formatCount(
                view.weekly.length,
              )} tuần trong phạm vi.`}
            </p>
          ) : null}

          {primary === undefined ? null : (
            <div className={styles.ledgerGroupBlock}>
              {/* A caption, not a heading: a heading here would sit at h3
                  straight under the h1 and break the outline. */}
              <p id={primary.id} className={styles.ledgerGroupHeading}>
                <span className={styles.ledgerGroupLabel}>{primary.label}</span>
                {primary.denominator === null ? null : (
                  <span className={styles.ledgerGroupDenominator}>
                    {primary.denominator}
                  </span>
                )}
                {primary.comparison === null ? null : (
                  <span className={styles.ledgerGroupDenominator}>
                    {primary.comparison}
                  </span>
                )}
              </p>
              <div
                id="kpiGrid"
                className={styles.ledger}
                role="group"
                aria-labelledby={primary.id}
              >
                {primary.cells.map((cell) => renderCell(cell, styles.ledgerCell))}
              </div>
            </div>
          )}

          {secondary === undefined ? null : (
            <div
              id="ledger-secondary"
              className={styles.ledgerSecondary}
              role="group"
              aria-label={secondary.label}
            >
              {secondary.cells.map((cell) =>
                renderCell(cell, styles.ledgerSecondaryCell),
              )}
            </div>
          )}
        </div>
      </div>

      {attention.length === 0 ? null : (
        <ul className={styles.rail} aria-label="Cần xem trong phạm vi này">
          {attention.map((item) => (
            <li
              key={item.id}
              className={`${styles.railItem} ${
                item.severity === "critical" ? styles.railCritical : styles.railWarning
              }`}
            >
              <p className={styles.railHeadline}>
                {item.severity === "critical" ? (
                  <span className={styles.railSeverity}>Cần xử lý</span>
                ) : null}
                {item.headline}
              </p>
              {item.action === null ? null : (
                <p className={styles.railAction}>{item.action}</p>
              )}
              {item.filterPatch === null || onCellSelect === undefined ? null : (
                <div className={styles.railActions}>
                  <button
                    type="button"
                    className={styles.railActionButton}
                    onClick={() => onCellSelect(item.filterPatch!)}
                  >
                    Xem ticket
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
