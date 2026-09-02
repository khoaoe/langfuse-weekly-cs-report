import { useMemo, useState } from "react";

import type {
  DashboardView,
  TransferReasons,
  WeekDefinition,
  WeeklyReportRow,
} from "../lib/dashboard-schema";
import type { TicketFilters } from "../lib/dashboard-filters";
import {
  PERCENTAGE_SAMPLE_MINIMUM,
  formatCount,
  formatRate,
  formatWeekRange,
} from "../lib/format";
import { transferReasonLabel } from "../lib/transfer-copy";
import {
  stableSortRows,
  toggleTableSort,
  type SortDirection,
  type SortValue,
  type TableSort,
} from "../lib/table-sort";
import { DataTableSortButton } from "./DataTableSortButton";
import { FilterValueButton } from "./FilterValueButton";
import belowFoldStyles from "./below-fold.module.css";
import styles from "./dashboard.module.css";

type TpeReason = TransferReasons["tpe"][number];
type TransferTrigger = TransferReasons["triggers"][number];
type TpeSortKey = "status" | "transstatus" | "step_result" | "count" | "share";
type TransferReasonSortKey =
  | "reason"
  | "rule"
  | "source"
  | "skill"
  | "count"
  | "share";
type RuleGt4 = DashboardView["rule_gt4"];

interface TpeSortColumn {
  readonly key: TpeSortKey;
  readonly label: string;
  readonly initialDirection: SortDirection;
  readonly value: (item: TpeReason, denominator: number) => SortValue;
}

/**
 * `denominator` here is `observed_transfer_denominator` — the whole table's
 * transferred-ticket total, not a per-row sample size like CSAT's. Gating on
 * it would almost never trigger, so the small-sample guard instead checks
 * `count`, the numerator for this specific transstatus/step_result or
 * transfer-reason row.
 */
function formatTransferShare(count: number, denominator: number): string {
  if (denominator === 0) return "—";
  return count < PERCENTAGE_SAMPLE_MINIMUM ? "—" : formatRate(count / denominator);
}

const TPE_UNCLASSIFIED_LABEL = "Chưa phân loại";

function tpeStatusLabel(status: string | null): string {
  return status === null ? TPE_UNCLASSIFIED_LABEL : status;
}

const TPE_SORT_COLUMNS: readonly TpeSortColumn[] = [
  {
    key: "status",
    label: "Trạng thái",
    initialDirection: "asc",
    value: (item) => item.status,
  },
  {
    key: "transstatus",
    label: "Transstatus",
    initialDirection: "asc",
    value: (item) => Number(item.transstatus),
  },
  {
    key: "step_result",
    label: "Step result",
    initialDirection: "asc",
    value: (item) =>
      item.step_result === null ? null : Number(item.step_result),
  },
  {
    key: "count",
    label: "Ticket",
    initialDirection: "desc",
    value: (item) => item.count,
  },
  {
    key: "share",
    label: "Tỷ lệ ticket có mã này",
    initialDirection: "desc",
    value: (item, denominator) =>
      denominator === 0 ? null : item.count / denominator,
  },
];

const DEFAULT_TPE_SORT: TableSort<TpeSortKey> = {
  key: "count",
  direction: "desc",
};

function TpeZone({
  transfer,
  onTicketFilterSelect,
}: {
  readonly transfer: TransferReasons;
  readonly onTicketFilterSelect: (patch: Partial<TicketFilters>) => void;
}) {
  const [sort, setSort] = useState<TableSort<TpeSortKey>>(DEFAULT_TPE_SORT);
  const rows = useMemo(() => {
    const deterministic = stableSortRows(
      transfer.tpe,
      (item) => Number(item.transstatus),
      "asc",
    );
    const column =
      TPE_SORT_COLUMNS.find((item) => item.key === sort.key) ??
      TPE_SORT_COLUMNS[0];
    return stableSortRows(
      deterministic,
      (item) =>
        column?.value(item, transfer.observed_transfer_denominator),
      sort.direction,
    );
  }, [sort, transfer.observed_transfer_denominator, transfer.tpe]);
  return (
    <section
      id="tpeDistribution"
      className={belowFoldStyles.diagnosticZone}
      aria-labelledby="tpe-diagnostic-title"
    >
      <details className={styles.qualityDisclosure}>
        <summary className={styles.qualitySummary}>
          <span
            id="tpe-diagnostic-title"
            className={belowFoldStyles.diagnosticTitle}
            role="heading"
            aria-level={3}
          >
            Transstatus và Step result
          </span>
        </summary>
        <div className={styles.qualityContent}>
          <div
            className={styles.tableScroll}
            tabIndex={0}
            role="region"
            aria-label="Bảng Transstatus và Step result"
          >
            <table
              className={styles.table}
              aria-labelledby="tpe-diagnostic-title"
              aria-describedby="transferScope"
            >
              <thead>
                <tr>
                  {TPE_SORT_COLUMNS.map((column, index) => {
                    const active = sort.key === column.key;
                    const numeric = index >= 3;
                    return (
                      <th
                        key={column.key}
                        scope="col"
                        className={
                          index === 0
                            ? styles.stickyColumn
                            : numeric
                              ? styles.numeric
                              : undefined
                        }
                        aria-sort={
                          active
                            ? sort.direction === "asc"
                              ? "ascending"
                              : "descending"
                            : "none"
                        }
                      >
                        <DataTableSortButton
                          label={column.label}
                          active={active}
                          direction={sort.direction}
                          align={numeric ? "end" : "start"}
                          onClick={() =>
                            setSort((current) =>
                              toggleTableSort(
                                current,
                                column.key,
                                column.initialDirection,
                              ),
                            )
                          }
                        />
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {transfer.tpe.length === 0 ? (
                  <tr>
                    <td className={styles.emptyCell} colSpan={5}>
                      Không có Transstatus trong phạm vi đang chọn.
                    </td>
                  </tr>
                ) : null}
                {rows.map((item) => (
                  <tr
                    key={`tpe-${item.transstatus}-${item.step_result ?? "missing"}`}
                  >
                    <th scope="row" className={styles.stickyColumn}>
                      {tpeStatusLabel(item.status)}
                    </th>
                    <td>
                      <FilterValueButton
                        label={item.transstatus}
                        filterLabel="Transstatus"
                        onClick={() =>
                          onTicketFilterSelect({ tpe_code: item.transstatus })
                        }
                      />
                    </td>
                    <td>
                      {item.step_result === null
                        ? "Không có Step result"
                        : item.step_result}
                    </td>
                    <td className={styles.numeric}>{formatCount(item.count)}</td>
                    <td className={styles.numeric}>
                      {formatTransferShare(
                        item.count,
                        transfer.observed_transfer_denominator,
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </details>
    </section>
  );
}

function formatTriggerSource(item: TransferTrigger): string {
  if (item.source === null) return "—";
  if (item.source === "skill_guardrail_checked" && item.stage !== null) {
    return `${item.source} · stage=${item.stage}`;
  }
  return item.source;
}

interface TransferReasonSortColumn {
  readonly key: TransferReasonSortKey;
  readonly label: string;
  readonly initialDirection: SortDirection;
  readonly value: (item: TransferTrigger, denominator: number) => SortValue;
}

const TRANSFER_REASON_SORT_COLUMNS: readonly TransferReasonSortColumn[] = [
  {
    key: "reason",
    label: "Lý do chuyển CS",
    initialDirection: "asc",
    value: (item) => transferReasonLabel(item.reason),
  },
  {
    key: "rule",
    label: "Giá trị nguồn",
    initialDirection: "asc",
    value: (item) => item.rule,
  },
  {
    key: "source",
    label: "Nguồn phát hiện",
    initialDirection: "asc",
    value: (item) => item.source === null ? null : formatTriggerSource(item),
  },
  {
    key: "skill",
    label: "Skill",
    initialDirection: "asc",
    value: (item) => item.skill,
  },
  {
    key: "count",
    label: "Ticket",
    initialDirection: "desc",
    value: (item) => item.count,
  },
  {
    key: "share",
    label: "Tỷ lệ",
    initialDirection: "desc",
    value: (item, denominator) =>
      denominator === 0 ? null : item.count / denominator,
  },
];

const DEFAULT_TRANSFER_REASON_SORT: TableSort<TransferReasonSortKey> = {
  key: "count",
  direction: "desc",
};

function TransferReasonZone({
  transfer,
  onTicketFilterSelect,
}: {
  readonly transfer: TransferReasons;
  readonly onTicketFilterSelect: (patch: Partial<TicketFilters>) => void;
}) {
  const [sort, setSort] = useState<TableSort<TransferReasonSortKey>>(
    DEFAULT_TRANSFER_REASON_SORT,
  );
  const rows = useMemo(() => {
    const deterministic = stableSortRows(
      transfer.triggers,
      (item) => `${item.reason}\u0000${item.rule ?? ""}\u0000${item.source ?? ""}\u0000${item.stage ?? ""}\u0000${item.skill ?? ""}`,
      "asc",
    );
    const column =
      TRANSFER_REASON_SORT_COLUMNS.find((item) => item.key === sort.key) ??
      TRANSFER_REASON_SORT_COLUMNS[0];
    return stableSortRows(
      deterministic,
      (item) =>
        column?.value(item, transfer.observed_transfer_denominator),
      sort.direction,
    );
  }, [sort, transfer.observed_transfer_denominator, transfer.triggers]);
  if (rows.length === 0) {
    return null;
  }

  return (
    <section
      id="guardrailDistribution"
      className={belowFoldStyles.diagnosticZone}
      aria-labelledby="system-condition-title"
    >
      <h3
        id="system-condition-title"
        className={belowFoldStyles.diagnosticTitle}
      >
        Lý do chuyển CS
      </h3>
      <div
        className={styles.tableScroll}
        tabIndex={0}
        role="region"
        aria-label="Bảng lý do chuyển CS"
      >
        <table
          className={styles.table}
          aria-labelledby="system-condition-title"
          aria-describedby="transferScope"
        >
          <thead>
            <tr>
              {TRANSFER_REASON_SORT_COLUMNS.map((column, index) => {
                const active = sort.key === column.key;
                const numeric = index >= 4;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    className={
                      index === 0
                        ? styles.stickyColumn
                        : numeric
                          ? styles.numeric
                          : undefined
                    }
                    aria-sort={
                      active
                        ? sort.direction === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <DataTableSortButton
                      label={column.label}
                      active={active}
                      direction={sort.direction}
                      align={numeric ? "end" : "start"}
                      onClick={() =>
                        setSort((current) =>
                          toggleTableSort(
                            current,
                            column.key,
                            column.initialDirection,
                          ),
                        )
                      }
                    />
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr
                key={`${item.reason}-${item.rule ?? "unknown"}-${item.source ?? "unknown"}-${item.stage ?? "none"}-${item.skill ?? "none"}`}
              >
                <th scope="row" className={styles.stickyColumn}>
                  <FilterValueButton
                    label={transferReasonLabel(item.reason)}
                    filterLabel="Lý do chuyển CS"
                    onClick={() =>
                      onTicketFilterSelect({
                        transfer_reason: item.reason,
                        ...(item.skill === null ? {} : { skill: item.skill }),
                      })
                    }
                  />
                </th>
                <td>
                  {item.rule === null ? (
                    "—"
                  ) : (
                    <code className={belowFoldStyles.sourceCode}>{item.rule}</code>
                  )}
                </td>
                <td>
                  {item.source === null ? (
                    "—"
                  ) : (
                    <code className={belowFoldStyles.sourceCode}>
                      {formatTriggerSource(item)}
                    </code>
                  )}
                </td>
                <td>
                  {item.skill === null ? (
                    "—"
                  ) : (
                    <code className={belowFoldStyles.sourceCode}>{item.skill}</code>
                  )}
                </td>
                <td className={styles.numeric}>{formatCount(item.count)}</td>
                <td className={styles.numeric}>
                  {formatTransferShare(
                    item.count,
                    transfer.observed_transfer_denominator,
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Gt4Zone({
  rule,
  onShowStuckTickets,
  onTicketFilterSelect,
}: {
  readonly rule: RuleGt4;
  readonly onShowStuckTickets: () => void;
  readonly onTicketFilterSelect: (patch: Partial<TicketFilters>) => void;
}) {
  return (
    <section
      id="ruleGt4Panel"
      className={belowFoldStyles.diagnosticZone}
      aria-labelledby="gt4-title"
    >
      <h3 id="gt4-title" className={belowFoldStyles.diagnosticTitle}>
        Ticket có hơn 3 lượt xử lý
      </h3>
      <div
        className={styles.tableScroll}
        tabIndex={0}
        role="region"
        aria-label="Bảng ticket có hơn 3 lượt xử lý"
      >
        <table className={styles.table} aria-labelledby="gt4-title">
          <thead>
            <tr>
              <th scope="col" className={styles.stickyColumn}>
                Trạng thái
              </th>
              <th scope="col" className={styles.numeric}>
                Ticket
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row" className={styles.stickyColumn}>
                {rule.gt4_turn_total === 0 ? (
                  "Tổng"
                ) : (
                  <FilterValueButton
                    label="Tổng"
                    filterLabel="Trạng thái"
                    onClick={() =>
                      onTicketFilterSelect({
                        gt4_turn: "true",
                        transferred: "",
                      })
                    }
                  />
                )}
              </th>
              <td className={styles.numeric}>
                {formatCount(rule.gt4_turn_total)}
              </td>
            </tr>
            <tr>
              <th scope="row" className={styles.stickyColumn}>
                {rule.gt4_turn_with_cs === 0 ? (
                  "Đã chuyển CS"
                ) : (
                  <FilterValueButton
                    label="Đã chuyển CS"
                    filterLabel="Trạng thái"
                    onClick={() =>
                      onTicketFilterSelect({
                        gt4_turn: "true",
                        transferred: "true",
                      })
                    }
                  />
                )}
              </th>
              <td className={styles.numeric}>
                {formatCount(rule.gt4_turn_with_cs)}
              </td>
            </tr>
            <tr>
              <th scope="row" className={styles.stickyColumn}>
                {rule.gt4_turn_without_cs === 0 ? (
                  "Chưa chuyển CS"
                ) : (
                  <FilterValueButton
                    label="Chưa chuyển CS"
                    filterLabel="Trạng thái"
                    onClick={() =>
                      onTicketFilterSelect({
                        gt4_turn: "true",
                        transferred: "false",
                      })
                    }
                  />
                )}
              </th>
              <td className={styles.numeric}>
                <span>{formatCount(rule.gt4_turn_without_cs)}</span>
                {rule.gt4_turn_without_cs > 0 ? (
                  <button
                    id="ruleGt4Alert"
                    type="button"
                    className={belowFoldStyles.inlineAction}
                    onClick={onShowStuckTickets}
                  >
                    {`Xem ${formatCount(
                      rule.gt4_turn_without_cs,
                    )} ticket chưa chuyển CS`}
                  </button>
                ) : (
                  <span id="ruleGt4Alert" hidden aria-hidden="true" />
                )}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <span id="ruleScope" hidden aria-hidden="true" />
    </section>
  );
}

export function TransferDiagnostics({
  transfer,
  rule,
  selectedWeek,
  weekDefinition,
  dayModeNote = null,
  onShowStuckTickets,
  onTicketFilterSelect,
}: {
  readonly transfer: TransferReasons;
  readonly rule: RuleGt4;
  readonly selectedWeek: WeeklyReportRow | undefined;
  readonly weekDefinition: WeekDefinition;
  /** §6: set only when the dashboard is scoped to a day range — this whole
   * panel still reads by full week, so the user must be told explicitly. */
  readonly dayModeNote?: string | null;
  readonly onShowStuckTickets: () => void;
  readonly onTicketFilterSelect: (patch: Partial<TicketFilters>) => void;
}) {
  const hasNoTransferSignals =
    transfer.tpe.length === 0 && transfer.triggers.length === 0;

  return (
    <section
      id="diagnostics"
      className={styles.section}
      aria-labelledby="diagnostics-title"
    >
      <div className={styles.sectionHead}>
        <div>
          <h2 id="diagnostics-title" className={styles.sectionTitle}>
            Tín hiệu chuyển CS và ticket có hơn 3 lượt xử lý
          </h2>
        </div>
      </div>
      <p id="transferScope" className={styles.tableCaption}>
        {`${formatCount(
          transfer.observed_transfer_denominator,
        )} ticket đã chuyển CS${
          selectedWeek === undefined
            ? " trong toàn kỳ"
            : ` trong tuần ${formatWeekRange(
                selectedWeek.cohort_week,
                weekDefinition,
              )}`
        }. Dòng có dưới ${formatCount(
          PERCENTAGE_SAMPLE_MINIMUM,
        )} ticket để trống cột tỷ lệ (“—”) vì mẫu quá nhỏ để đọc thành tỷ lệ.`}
      </p>
      {dayModeNote === null ? null : (
        <p id="diagnosticsDayModeNote" className={styles.sectionNote}>
          {dayModeNote}
        </p>
      )}
      {hasNoTransferSignals ? (
        <p className={belowFoldStyles.diagnosticEmpty}>
          Không có tín hiệu nào trong phạm vi đang chọn.
        </p>
      ) : null}

      <div className={belowFoldStyles.diagnosticZones}>
        <TpeZone
          transfer={transfer}
          onTicketFilterSelect={onTicketFilterSelect}
        />
        <TransferReasonZone
          transfer={transfer}
          onTicketFilterSelect={onTicketFilterSelect}
        />
        <Gt4Zone
          rule={rule}
          onShowStuckTickets={onShowStuckTickets}
          onTicketFilterSelect={onTicketFilterSelect}
        />
      </div>
      <span id="escalationPanel" hidden aria-hidden="true" />
    </section>
  );
}
