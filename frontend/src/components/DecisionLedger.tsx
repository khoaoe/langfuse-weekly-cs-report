import type { DashboardSnapshot, WeekDefinition } from "../lib/dashboard-schema";
import type { TicketFilters } from "../lib/dashboard-filters";
import { formatCount, formatWeekRange } from "../lib/format";
import { buildDeterministicNarrative } from "../lib/narrative";
import {
  COHORT_LABELS,
  buildNarrativeInput,
  selectAttentionItems,
  selectLedger,
  selectScope,
  selectView,
} from "../lib/selectors";
import styles from "./dashboard.module.css";

export interface DecisionLedgerProps {
  readonly snapshot: DashboardSnapshot;
  readonly weekDefinition: WeekDefinition;
  readonly activeWeek?: string;
  readonly onCellSelect?: (patch: Partial<TicketFilters>) => void;
}

const TONE_CLASS = {
  brand: styles.toneBrand,
  warning: styles.toneWarning,
  critical: styles.toneCritical,
  neutral: "",
} as const;

/**
 * The signature surface: dynamic title, deterministic narrative, the four-cell
 * ledger and only the warnings an operator can act on.
 */
export function DecisionLedger({
  snapshot,
  weekDefinition,
  activeWeek,
  onCellSelect,
}: DecisionLedgerProps) {
  const view = selectView(snapshot, weekDefinition);
  const scope = selectScope(snapshot, weekDefinition, activeWeek);
  const latest = scope.week;
  const groups = selectLedger(snapshot, weekDefinition, activeWeek);
  const attention = selectAttentionItems(snapshot, weekDefinition, activeWeek);
  const narrative = buildDeterministicNarrative(
    buildNarrativeInput(snapshot, weekDefinition, activeWeek),
  );

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
              : latest === null
                ? ""
                : ` · tuần ${formatWeekRange(latest.cohort_week, weekDefinition)}`}
            {` · ${formatCount(scope.eligible)} ticket`}
          </h1>
          <div
            id="narrativeSummary"
            className={styles.narrative}
            aria-live="polite"
          >
            {narrative.map((line) => (
              <p
                key={line}
                className={
                  line.includes("khách nhiều khả năng đang mắc kẹt") ||
                  line.startsWith("Lần đọc này chưa lấy đủ dữ liệu phụ")
                    ? styles.narrativeAlert
                    : undefined
                }
              >
                {line}
              </p>
            ))}
          </div>
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

          {groups.map((group) => (
            <div key={group.id} className={styles.ledgerGroupBlock}>
              <h3 id={group.id} className={styles.ledgerGroupHeading}>
                {group.label}
                <span className={styles.ledgerGroupDenominator}>
                  {group.denominator}
                </span>
              </h3>
              <div
                id={group.id === "ledger-group-ticket" ? "kpiGrid" : undefined}
                className={styles.ledger}
                role="group"
                aria-labelledby={group.id}
              >
                {group.cells.map((cell) =>
                  cell.filterPatch === null || onCellSelect === undefined ? (
                    <div
                      key={cell.id}
                      id={cell.id}
                      className={`${styles.ledgerCell} ${TONE_CLASS[cell.tone]}`}
                    >
                      <span className={styles.ledgerLabel}>{cell.label}</span>
                      <span className={styles.ledgerValue}>{cell.value}</span>
                      {cell.support === null ? null : (
                        <span className={styles.ledgerSupport}>{cell.support}</span>
                      )}
                    </div>
                  ) : (
                    <div
                      key={cell.id}
                      id={cell.id}
                      className={`${styles.ledgerCell} ${TONE_CLASS[cell.tone]}`}
                    >
                      <button
                        type="button"
                        className={styles.ledgerCellButton}
                        onClick={() => onCellSelect(cell.filterPatch as Partial<TicketFilters>)}
                      >
                        <span className={styles.ledgerLabel}>{cell.label}</span>
                        <span className={styles.ledgerValue}>{cell.value}</span>
                        {cell.support === null ? null : (
                          <span className={styles.ledgerSupport}>{cell.support}</span>
                        )}
                      </button>
                    </div>
                  ),
                )}
              </div>
            </div>
          ))}
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
                {item.headline}
              </p>
              <p className={styles.railAction}>{item.action}</p>
              <div className={styles.railActions}>
                {item.filterPatch === null || onCellSelect === undefined ? null : (
                  <button
                    type="button"
                    className={styles.railActionButton}
                    onClick={() => onCellSelect?.(item.filterPatch!)}
                  >
                    Xem ticket
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
