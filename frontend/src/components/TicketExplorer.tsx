import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import langfuseIconUrl from "../../../assets/icons/langfuse-icon.svg";
import { fetchTicketPage } from "../lib/api";
import type {
  DashboardSnapshot,
  TicketRow,
  WeekDefinition,
} from "../lib/dashboard-schema";
import { parseTicketPage } from "../lib/dashboard-schema";
import { dataQualityLabel } from "../lib/data-quality";
import {
  CSAT_SATISFACTION_OPTIONS,
  csatSatisfactionLabel,
} from "../lib/csat-labels";
import {
  EMPTY_TICKET_FILTERS,
  OUTCOME_FILTER_LABELS,
  activeTicketFilterChips,
  type TicketFilters,
  updateTicketFilters,
} from "../lib/dashboard-filters";
import { formatCount, formatUpdatedAt, formatWeekRange } from "../lib/format";
import { selectLatestWeek, selectView } from "../lib/selectors";
import { csvCell } from "../lib/spreadsheet";
import { transferReasonLabel } from "../lib/transfer-copy";
import {
  DEFAULT_TICKET_COLUMNS,
  TICKET_COLUMNS,
  type TicketColumnKey,
  readVisibleTicketColumns,
  writeVisibleTicketColumns,
} from "../lib/ticket-columns";
import { DataTableSortButton } from "./DataTableSortButton";
import { SatisfactionBadge } from "./SatisfactionBadge";
import {
  FreshdeskTicketLink,
  isValidFreshdeskTicketId,
} from "./FreshdeskTicketLink";
import styles from "./dashboard.module.css";
import ticketStyles from "./ticket-explorer.module.css";

const PAGE_SIZE = 50;
const LANGFUSE_TRACES_URL =
  "https://langfuse.zalopay.vn/project/cmqubjzur000hz507ptubh2l9/traces";
const VALID_WEEK_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const VIETNAM_OFFSET_MILLISECONDS = 7 * 60 * 60 * 1_000;

/** The backend refuses a larger page, so a bulk export walks pages. */
export const TICKET_EXPORT_LIMIT = 1_000;
const EXPORT_PAGE_SIZE = 100;

interface TicketSort {
  readonly key: TicketColumnKey;
  readonly direction: "asc" | "desc";
}

const DEFAULT_SORT: TicketSort = { key: "cohort_week", direction: "desc" };

function vietnamDateForTimestamp(timestamp: number): string {
  return new Date(timestamp + VIETNAM_OFFSET_MILLISECONDS)
    .toISOString()
    .slice(0, 10);
}

function tracingDateRange(
  rangeStart: string,
  rangeEnd: string,
): string | null {
  if (!VALID_WEEK_PATTERN.test(rangeStart)) {
    return null;
  }
  const endTimestamp = Date.parse(rangeEnd);
  if (!Number.isFinite(endTimestamp)) {
    return null;
  }

  const startTimestamp = Date.parse(
    `${rangeStart}T00:00:00.000+07:00`,
  );
  const endDate = vietnamDateForTimestamp(endTimestamp);
  const endOfDayTimestamp = Date.parse(
    `${endDate}T23:59:59.999+07:00`,
  );
  if (
    !Number.isFinite(startTimestamp) ||
    !Number.isFinite(endOfDayTimestamp) ||
    startTimestamp > endOfDayTimestamp
  ) {
    return null;
  }
  return `${startTimestamp}-${endOfDayTimestamp}`;
}

function langfuseTracingUrl(
  ticketId: string,
  rangeStart: string,
  rangeEnd: string,
): string | null {
  const dateRange = tracingDateRange(rangeStart, rangeEnd);
  if (dateRange === null) {
    return null;
  }
  const filter = `sessionId;stringOptions;;any of;${ticketId}`;
  return `${LANGFUSE_TRACES_URL}?filter=${encodeURIComponent(filter)}&dateRange=${dateRange}`;
}

export function TicketIdentifier({
  ticketId,
  traceRangeStart,
  traceRangeEnd,
}: {
  readonly ticketId: string;
  readonly traceRangeStart: string;
  readonly traceRangeEnd: string;
}) {
  if (!isValidFreshdeskTicketId(ticketId)) {
    return <>{ticketId}</>;
  }
  const langfuseHref = langfuseTracingUrl(
    ticketId,
    traceRangeStart,
    traceRangeEnd,
  );

  return (
    <span className={ticketStyles.ticketLinks}>
      <FreshdeskTicketLink
        ticketId={ticketId}
        className={ticketStyles.ticketLink}
      >
        {ticketId}
      </FreshdeskTicketLink>
      {langfuseHref === null ? null : (
        <a
          className={`${ticketStyles.ticketLink} ${ticketStyles.langfuseLink}`}
          href={langfuseHref}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Mở các trace của ticket ${ticketId} trên Langfuse trong thẻ mới`}
          title={`Mở Tracing của ticket ${ticketId} trên Langfuse`}
        >
          <img
            className={ticketStyles.langfuseIcon}
            src={langfuseIconUrl}
            width={16}
            height={16}
            alt=""
            aria-hidden="true"
          />
        </a>
      )}
    </span>
  );
}

function cellText(row: TicketRow, key: TicketColumnKey): string {
  const value = row[key];
  if (value === null) {
    return "—";
  }
  if (typeof value === "boolean") {
    return value ? "Có" : "Không";
  }
  if (key === "outcome") {
    return OUTCOME_FILTER_LABELS[String(value)] ?? String(value);
  }
  if (key === "csat_satisfaction") {
    return csatSatisfactionLabel(row.csat_satisfaction);
  }
  if (key === "transfer_reason" && row.transfer_reason !== null) {
    return transferReasonLabel(row.transfer_reason);
  }
  if (key === "opened_at") {
    return formatUpdatedAt(row.opened_at);
  }
  if (key === "cohort_status") {
    return value === "wtd" ? "Tuần chưa kết thúc" : "Tuần đầy đủ";
  }
  if (key === "data_quality") {
    return dataQualityLabel(row.data_quality);
  }
  if (typeof value === "number") {
    return formatCount(value);
  }
  return String(value);
}

export interface TicketExplorerProps {
  readonly snapshot: DashboardSnapshot;
  readonly weekDefinition: WeekDefinition;
  readonly enabled: boolean;
  readonly filters: TicketFilters;
  readonly onFiltersChange: (filters: TicketFilters) => void;
}

/**
 * Ticket-level drill-down over the sanitised projection.
 *
 * Only the allowlisted projection columns exist here: no customer text, raw
 * payload or additional per-ticket Langfuse identifier is requested, stored or
 * exported. The approved outbound Langfuse route reuses the numeric Ticket ID.
 */
export function TicketExplorer({
  snapshot,
  weekDefinition,
  enabled,
  filters,
  onFiltersChange,
}: TicketExplorerProps) {
  const [page, setPage] = useState(1);
  const [visible, setVisible] = useState<readonly TicketColumnKey[]>(() =>
    readVisibleTicketColumns(),
  );
  const [exportNotice, setExportNotice] = useState("");
  const [sort, setSort] = useState<TicketSort>(DEFAULT_SORT);
  const view = selectView(snapshot, weekDefinition);
  const observedWeeks = useMemo(
    () =>
      [...view.weekly]
        .filter((week) => week.has_data)
        .sort((left, right) => right.cohort_week.localeCompare(left.cohort_week)),
    [view.weekly],
  );

  const query = useMemo(
    () => ({
      week_definition: weekDefinition,
      sort_by: sort.key,
      sort_direction: sort.direction,
      page,
      page_size: PAGE_SIZE,
      outcome: filters.outcome,
      csat_satisfaction: filters.csat_satisfaction,
      gt4_turn: filters.gt4_turn,
      transferred: filters.transferred,
      ticket_id: filters.ticket_id.trim(),
      cohort_week: filters.cohort_week,
      cohort_weeks: filters.cohort_weeks,
      issue_category: filters.issue_category,
      app: filters.app,
      product_code: filters.product_code,
      skill: filters.skill,
      intent: filters.intent,
      tpe_code: filters.tpe_code,
      transfer_reason: filters.transfer_reason,
      is_weekend_start: filters.is_weekend_start,
    }),
    [weekDefinition, sort, page, filters],
  );

  const ticketQuery = useQuery({
    queryKey: ["tickets", query],
    enabled,
    retry: false,
    queryFn: async ({ signal }) => {
      const parsed = parseTicketPage(await fetchTicketPage(query, signal));
      if (!parsed.ok) {
        throw new Error(parsed.message);
      }
      return parsed.data;
    },
  });

  // A cohort with fewer weekend tickets has fewer pages, so a page number
  // carried across the toggle would silently render an empty result.
  useEffect(() => {
    setPage(1);
  }, [weekDefinition, filters]);

  const update = useCallback((patch: Partial<TicketFilters>) => {
    setPage(1);
    onFiltersChange(updateTicketFilters(filters, patch));
  }, [filters, onFiltersChange]);

  const toggleColumn = useCallback((key: TicketColumnKey) => {
    if (key === "ticket_id") {
      return;
    }
    const removing = visible.includes(key);
    const next = removing
      ? visible.filter((item) => item !== key)
      : [...visible, key];
    const nextVisible = writeVisibleTicketColumns(
      next.length === 0 ? DEFAULT_TICKET_COLUMNS : next,
    );
    setVisible(nextVisible);

    if (removing && sort.key === key) {
      setPage(1);
      setSort(
        nextVisible.includes(DEFAULT_SORT.key)
          ? DEFAULT_SORT
          : { key: "ticket_id", direction: "asc" },
      );
    }
  }, [sort.key, visible]);

  const exportCsv = useCallback(async () => {
    const rows: TicketRow[] = [];
    for (let current = 1; rows.length < TICKET_EXPORT_LIMIT; current += 1) {
      let payload: unknown;
      try {
        payload = await fetchTicketPage({
          ...query,
          page: current,
          page_size: EXPORT_PAGE_SIZE,
        });
      } catch {
        // The server status is deliberately not surfaced to the operator.
        setExportNotice("Không tải được dữ liệu để xuất. Hãy thử lại.");
        return;
      }
      const parsed = parseTicketPage(payload);
      if (!parsed.ok) {
        setExportNotice("Không tải được dữ liệu để xuất. Hãy thử lại.");
        return;
      }
      rows.push(...parsed.data.items);
      if (parsed.data.items.length === 0 || rows.length >= parsed.data.total) {
        break;
      }
    }

    const capped = rows.slice(0, TICKET_EXPORT_LIMIT);
    const exportKeys = new Set<TicketColumnKey>(["ticket_id", ...visible]);
    const exportColumns = TICKET_COLUMNS.filter((column) =>
      exportKeys.has(column.key),
    );
    const body = [
      exportColumns.map((column) => csvCell(column.label)).join(","),
      ...capped.map((row) =>
        exportColumns
          .map((column) => csvCell(cellText(row, column.key)))
          .join(","),
      ),
    ].join("\r\n");
    const url = URL.createObjectURL(
      new Blob([`\u{FEFF}${body}`], { type: "text/csv;charset=utf-8" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "zalopay-ticket-explorer.csv";
    anchor.rel = "noopener";
    anchor.click();
    URL.revokeObjectURL(url);
    setExportNotice(
      `Đã xuất ${formatCount(capped.length)} dòng (tối đa ${formatCount(
        TICKET_EXPORT_LIMIT,
      )}).`,
    );
  }, [query, visible]);

  const data = ticketQuery.data;
  const failed = ticketQuery.isError;
  const columns = TICKET_COLUMNS.filter((column) => visible.includes(column.key));
  const rows = data?.items ?? [];
  const lastPage = data === undefined ? 1 : Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const filterOptions = {
    issue_category: Object.keys(view.segments.issue_category),
    app: Object.keys(view.segments.app),
    product_code: Object.keys(view.segments.product_code),
    skill: Object.keys(view.segments.skill),
    intent: Object.keys(view.segments.intent),
    tpe_code: Array.from(
      new Set([
        ...Object.keys(view.segments.tpe),
        ...view.transfer_reasons.tpe.map((item) => item.transstatus),
      ]),
    ),
    transfer_reason: Array.from(
      new Set(view.transfer_reasons.triggers.map((item) => item.reason)),
    ).sort((left, right) =>
      transferReasonLabel(left).localeCompare(
        transferReasonLabel(right),
        "vi",
      ),
    ),
  } as const;

  const explorerActiveFilters = activeTicketFilterChips(filters, weekDefinition);
  const latestWeek = selectLatestWeek(view);

  const toggleSort = useCallback((key: TicketColumnKey) => {
    setPage(1);
    setSort((current) =>
      current.key === key
        ? {
            key,
            direction: current.direction === "asc" ? "desc" : "asc",
          }
        : { key, direction: "asc" },
    );
  }, []);

  return (
    <section id="tickets" className={styles.section} aria-labelledby="tickets-title">
      <div className={styles.sectionHead}>
        <div>
          <h2 id="tickets-title" className={styles.sectionTitle} tabIndex={-1}>
            Ticket Explorer
          </h2>
        </div>
        <div className={styles.controls}>
          <button
            id="ticketCsvButton"
            type="button"
            className={styles.action}
            onClick={() => void exportCsv()}
          >
            Tải CSV ticket
          </button>
          <button
            type="button"
            className={styles.action}
            onClick={() => {
              onFiltersChange(EMPTY_TICKET_FILTERS);
              setPage(1);
            }}
          >
            Xoá bộ lọc
          </button>
        </div>
      </div>

      <p className={styles.sectionNote}>
        Chỉ hiển thị dữ liệu dùng cho báo cáo, không có nội dung hội thoại hay
        thông tin khách hàng. Một số ticket không có mã số hợp lệ vẫn được tính
        trong KPI nhưng không xuất hiện trong bảng này.
      </p>

      <div
        id="ticketQuickFilters"
        className={styles.controls}
        role="group"
        aria-label="Lọc nhanh"
      >
        <button
          type="button"
          className={styles.action}
          disabled={latestWeek === null}
          onClick={() =>
            latestWeek !== null &&
            update({
              cohort_week: latestWeek.cohort_week,
              cohort_weeks: "",
            })
          }
        >
          Tuần này
        </button>
        <button
          type="button"
          className={styles.action}
          onClick={() => update({ gt4_turn: "true", transferred: "false" })}
        >
          &gt;3 lượt xử lý chưa chuyển
        </button>
      </div>

      {explorerActiveFilters.length === 0 ? null : (
        <div
          id="explorerActiveFilterChips"
          className={styles.filterChips}
          role="region"
          aria-label="Bộ lọc đang áp dụng trong Ticket Explorer"
        >
          {explorerActiveFilters.map((filter) => (
            <span key={filter.key} className={styles.filterChip}>
              {filter.label}
              <button
                type="button"
                aria-label={`Bỏ lọc ${filter.label} (Ticket Explorer)`}
                onClick={() => update({ [filter.key]: "" } as Partial<TicketFilters>)}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <div id="ticketFilters" className={ticketStyles.filters}>
        <label className={ticketStyles.field}>
          Tuần
          <select
            id="cohortWeekInput"
            value={
              filters.cohort_weeks === ""
                ? filters.cohort_week
                : "__multiple__"
            }
            onChange={(event) =>
              update({
                cohort_week: event.target.value,
                cohort_weeks: "",
              })
            }
          >
            <option value="">Tất cả tuần</option>
            {filters.cohort_weeks === "" ? null : (
              <option value="__multiple__">
                {`${filters.cohort_weeks.split(",").filter(Boolean).length} tuần từ phạm vi báo cáo`}
              </option>
            )}
            {observedWeeks.map((week) => (
              <option key={week.cohort_week} value={week.cohort_week}>
                {formatWeekRange(week.cohort_week, weekDefinition)}
              </option>
            ))}
          </select>
        </label>
        <label className={ticketStyles.field}>
          Mã ticket
          <input
            type="text"
            inputMode="numeric"
            value={filters.ticket_id}
            onChange={(event) => update({ ticket_id: event.target.value })}
          />
        </label>
        <label className={ticketStyles.field}>
          Kết quả
          <select
            value={filters.outcome}
            onChange={(event) => update({ outcome: event.target.value })}
          >
            <option value="">Tất cả</option>
            {Object.entries(OUTCOME_FILTER_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className={ticketStyles.field}>
          Mức độ hài lòng (CS Agent)
          <select
            value={filters.csat_satisfaction}
            onChange={(event) =>
              update({ csat_satisfaction: event.target.value })
            }
          >
            <option value="">Tất cả</option>
            {CSAT_SATISFACTION_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className={ticketStyles.field}>
          Category
          <select
            id="issueCategoryInput"
            value={filters.issue_category}
            onChange={(event) => update({ issue_category: event.target.value })}
          >
            <option value="">Tất cả</option>
            {filterOptions.issue_category.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className={ticketStyles.field}>
          App
          <select
            id="appInput"
            value={filters.app}
            onChange={(event) => update({ app: event.target.value })}
          >
            <option value="">Tất cả</option>
            {filterOptions.app.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className={ticketStyles.field}>
          Product Code
          <select
            id="productCodeInput"
            value={filters.product_code}
            onChange={(event) => update({ product_code: event.target.value })}
          >
            <option value="">Tất cả</option>
            {filterOptions.product_code.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className={ticketStyles.field}>
          Skill
          <select
            id="skillInput"
            value={filters.skill}
            onChange={(event) => update({ skill: event.target.value })}
          >
            <option value="">Tất cả</option>
            {filterOptions.skill.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className={ticketStyles.field}>
          Intent
          <input
            id="intentInput"
            type="text"
            list="intentOptions"
            value={filters.intent}
            onChange={(event) => update({ intent: event.target.value })}
            placeholder="Gõ để tìm"
          />
          <datalist id="intentOptions">
            {filterOptions.intent.map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
        </label>
        <label className={ticketStyles.field}>
          Transstatus
          <select
            id="tpeCodeInput"
            value={filters.tpe_code}
            onChange={(event) => update({ tpe_code: event.target.value })}
          >
            <option value="">Tất cả</option>
            {filterOptions.tpe_code.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className={ticketStyles.field}>
          Hơn 3 lượt xử lý
          <select
            id="gt4TurnInput"
            value={filters.gt4_turn}
            onChange={(event) => update({ gt4_turn: event.target.value })}
          >
            <option value="">Tất cả</option>
            <option value="true">Có</option>
            <option value="false">Không</option>
          </select>
        </label>
        <label className={ticketStyles.field}>
          Đã chuyển CS
          <select
            id="transferredInput"
            value={filters.transferred}
            onChange={(event) => update({ transferred: event.target.value })}
          >
            <option value="">Tất cả</option>
            <option value="true">Có</option>
            <option value="false">Không</option>
          </select>
        </label>
        <label className={ticketStyles.field}>
          Lý do chuyển CS
          <select
            id="transferReasonInput"
            value={filters.transfer_reason}
            onChange={(event) =>
              update({ transfer_reason: event.target.value })
            }
          >
            <option value="">Tất cả</option>
            {filterOptions.transfer_reason.map((value) => (
              <option key={value} value={value}>
                {transferReasonLabel(value)}
              </option>
            ))}
          </select>
        </label>
        <label className={ticketStyles.field}>
          Bắt đầu cuối tuần
          <select
            id="weekendInput"
            value={filters.is_weekend_start}
            onChange={(event) =>
              update({ is_weekend_start: event.target.value })
            }
          >
            <option value="">Tất cả</option>
            <option value="true">Có</option>
            <option value="false">Không</option>
          </select>
        </label>
      </div>

      <p
        id="tickets-caption"
        className={styles.tableCaption}
        aria-live="polite"
      >
        {failed
          ? "Không đọc được danh sách ticket."
          : data === undefined
            ? "Đang tải danh sách ticket."
            : `${formatCount(data.total)} ticket khớp bộ lọc.`}
      </p>

      <div
        className={styles.tableScroll}
        tabIndex={0}
        role="region"
        aria-labelledby="tickets-caption"
      >
        <table className={styles.table} aria-labelledby="tickets-caption">
          <thead>
            <tr>
              {columns.map((column, index) => (
                <th
                  key={column.key}
                  scope="col"
                  className={index === 0 ? styles.stickyColumn : ""}
                  aria-sort={
                    sort.key === column.key
                      ? sort.direction === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <DataTableSortButton
                    label={column.label}
                    active={sort.key === column.key}
                    direction={sort.direction}
                    onClick={() => toggleSort(column.key)}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody id="ticketRows">
            {failed ? (
              <tr>
                <td className={styles.emptyCell} colSpan={Math.max(1, columns.length)}>
                  Không đọc được danh sách ticket. Kiểm tra lại bộ lọc rồi thử lại.
                </td>
              </tr>
            ) : null}
            {!failed && data !== undefined && data.items.length === 0 ? (
              <tr>
                <td className={styles.emptyCell} colSpan={Math.max(1, columns.length)}>
                  Không có ticket nào khớp bộ lọc hiện tại.
                </td>
              </tr>
            ) : null}
            {rows.map((row) => (
              <tr key={row.ticket_id}>
                {columns.map((column, index) =>
                  column.key === "ticket_id" ? (
                    <th
                      key={column.key}
                      scope="row"
                      aria-label={row.ticket_id}
                      className={index === 0 ? styles.stickyColumn : ""}
                    >
                      <TicketIdentifier
                        ticketId={row.ticket_id}
                        traceRangeStart={
                          snapshot.data_range.first_week_with_data ??
                          row.cohort_week
                        }
                        traceRangeEnd={snapshot.generated_at}
                      />
                    </th>
                  ) : column.key === "opened_at" ? (
                    <td
                      key={column.key}
                      className={index === 0 ? styles.stickyColumn : ""}
                    >
                      <time dateTime={row.opened_at}>
                        {cellText(row, column.key)}
                      </time>
                    </td>
                  ) : column.key === "csat_satisfaction" ? (
                    <td
                      key={column.key}
                      className={index === 0 ? styles.stickyColumn : ""}
                    >
                      <SatisfactionBadge value={row.csat_satisfaction} />
                    </td>
                  ) : (
                    <td
                      key={column.key}
                      className={index === 0 ? styles.stickyColumn : ""}
                    >
                      {cellText(row, column.key)}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className={ticketStyles.pager}>
        <button
          type="button"
          className={styles.action}
          disabled={page <= 1}
          onClick={() => setPage((value) => Math.max(1, value - 1))}
        >
          Trang trước
        </button>
        <span>{`Trang ${formatCount(page)} / ${formatCount(lastPage)}`}</span>
        <button
          type="button"
          className={styles.action}
          disabled={page >= lastPage}
          onClick={() => setPage((value) => value + 1)}
        >
          Trang sau
        </button>
      </div>

      <details id="ticketColumnChooser" className={ticketStyles.columnPicker}>
        <summary>Chọn cột hiển thị</summary>
        <div id="ticketColumnOptions" className={ticketStyles.columnList}>
          <p className={ticketStyles.mandatoryColumnNote}>
            Cột Ticket luôn hiển thị để giữ định danh điều tra.
          </p>
          {TICKET_COLUMNS.filter((column) => column.key !== "ticket_id").map((column) => (
            <label key={column.key} className={ticketStyles.columnOption}>
              <input
                type="checkbox"
                checked={visible.includes(column.key)}
                onChange={() => toggleColumn(column.key)}
              />
              {column.label}
            </label>
          ))}
        </div>
      </details>

      <p aria-live="polite" className={styles.caption}>
        {exportNotice}
      </p>
    </section>
  );
}
