import { useCallback, useMemo, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";

import type {
  DashboardSnapshot,
  WeekDefinition,
  WeeklyReportRow,
} from "../lib/dashboard-schema";
import { formatUpdatedAt } from "../lib/format";
import { COHORT_LABELS, selectView, selectWeekly } from "../lib/selectors";
import {
  stableSortRows,
  toggleTableSort,
  type SortDirection,
  type SortValue,
  type TableSort,
} from "../lib/table-sort";
import {
  EMPTY_WEEK_LABEL,
  WEEKLY_EXPORT_COLUMNS,
  buildWeeklyCsv,
  buildWeeklyTsv,
  weeklyExportCells,
} from "../lib/weekly-export";
import { DataTableSortButton } from "./DataTableSortButton";
import styles from "./dashboard.module.css";

interface WeeklyTableRow {
  readonly key: string;
  readonly cells: readonly string[];
  readonly isCurrentWeek: boolean;
  readonly source: WeeklyReportRow;
}

const columnHelper = createColumnHelper<WeeklyTableRow>();

type WeeklySortKey =
  | "cohort_week"
  | "total_tickets"
  | "ai_first_count"
  | "ai_first_rate"
  | "ai_end_to_end_count"
  | "ai_then_cs_count"
  | "direct_cs_count"
  | "transfer_total"
  | "reopen_lifetime_numerator"
  | "reopen_lifetime_rate"
  | "ai_reply_mean_ai_first"
  | "gt4_turn_with_cs"
  | "gt4_turn_without_cs";

interface WeeklySortColumn {
  readonly key: WeeklySortKey;
  readonly label: (typeof WEEKLY_EXPORT_COLUMNS)[number];
  readonly exportIndex: number;
  readonly initialDirection: SortDirection;
  readonly value: (row: WeeklyReportRow) => SortValue;
}

function observedValue(row: WeeklyReportRow, value: SortValue): SortValue {
  return row.total_tickets === 0 ? null : value;
}

const WEEKLY_SORT_COLUMNS: readonly WeeklySortColumn[] = [
  {
    key: "cohort_week",
    label: WEEKLY_EXPORT_COLUMNS[0],
    exportIndex: 0,
    initialDirection: "asc",
    value: (row) => row.cohort_week,
  },
  {
    key: "total_tickets",
    label: WEEKLY_EXPORT_COLUMNS[1],
    exportIndex: 1,
    initialDirection: "desc",
    value: (row) => observedValue(row, row.total_tickets),
  },
  {
    key: "ai_first_count",
    label: WEEKLY_EXPORT_COLUMNS[2],
    exportIndex: 2,
    initialDirection: "desc",
    value: (row) => observedValue(row, row.ai_first_count),
  },
  {
    key: "ai_first_rate",
    label: WEEKLY_EXPORT_COLUMNS[3],
    exportIndex: 3,
    initialDirection: "desc",
    value: (row) => observedValue(row, row.ai_first_rate),
  },
  {
    key: "direct_cs_count",
    label: WEEKLY_EXPORT_COLUMNS[6],
    exportIndex: 6,
    initialDirection: "desc",
    value: (row) => observedValue(row, row.direct_cs_count),
  },
  {
    key: "ai_end_to_end_count",
    label: WEEKLY_EXPORT_COLUMNS[4],
    exportIndex: 4,
    initialDirection: "desc",
    value: (row) => observedValue(row, row.ai_end_to_end_count),
  },
  {
    key: "ai_then_cs_count",
    label: WEEKLY_EXPORT_COLUMNS[5],
    exportIndex: 5,
    initialDirection: "desc",
    value: (row) => observedValue(row, row.ai_then_cs_count),
  },
  {
    key: "transfer_total",
    label: WEEKLY_EXPORT_COLUMNS[7],
    exportIndex: 7,
    initialDirection: "desc",
    value: (row) =>
      observedValue(row, row.ai_then_cs_count + row.direct_cs_count),
  },
  {
    key: "reopen_lifetime_numerator",
    label: WEEKLY_EXPORT_COLUMNS[8],
    exportIndex: 8,
    initialDirection: "desc",
    value: (row) => observedValue(row, row.reopen_lifetime_numerator),
  },
  {
    key: "reopen_lifetime_rate",
    label: WEEKLY_EXPORT_COLUMNS[9],
    exportIndex: 9,
    initialDirection: "desc",
    value: (row) => observedValue(row, row.reopen_lifetime_rate),
  },
  {
    key: "ai_reply_mean_ai_first",
    label: WEEKLY_EXPORT_COLUMNS[10],
    exportIndex: 10,
    initialDirection: "desc",
    value: (row) => observedValue(row, row.ai_reply_mean_ai_first),
  },
  {
    key: "gt4_turn_with_cs",
    label: WEEKLY_EXPORT_COLUMNS[11],
    exportIndex: 11,
    initialDirection: "desc",
    value: (row) => observedValue(row, row.gt4_turn_with_cs),
  },
  {
    key: "gt4_turn_without_cs",
    label: WEEKLY_EXPORT_COLUMNS[12],
    exportIndex: 12,
    initialDirection: "desc",
    value: (row) => observedValue(row, row.gt4_turn_without_cs),
  },
];

/**
 * The compact view keeps the two first-response branches together, followed
 * by their transfer outcome. The full table still exposes every metric.
 */
const MOBILE_CORE_COLUMNS = new Set<WeeklySortKey>([
  "cohort_week",
  "total_tickets",
  "ai_first_count",
  "ai_first_rate",
  "direct_cs_count",
  "transfer_total",
]);

const WEEKLY_COLUMN_GROUPS = [
  { label: "Phạm vi", span: 2 },
  { label: "Phản hồi đầu tiên", span: 3 },
  { label: "Sau AI First", span: 2 },
  { label: "Kết quả xử lý", span: 6 },
] as const;

const DEFAULT_WEEKLY_SORT: TableSort<WeeklySortKey> = {
  key: "cohort_week",
  direction: "desc",
};

export interface WeeklyReportProps {
  readonly snapshot: DashboardSnapshot;
  readonly weekDefinition: WeekDefinition;
}

function download(filename: string, content: string, mediaType: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mediaType }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.click();
  URL.revokeObjectURL(url);
}

/**
 * The weekly report — the deliverable of this product.
 *
 * Screen cells and both exports come from the same `weeklyExportCells` call,
 * so the fourteen-column contract cannot drift between what an operator reads
 * and what they paste into a report.
 */
export function WeeklyReport({ snapshot, weekDefinition }: WeeklyReportProps) {
  const [allColumns, setAllColumns] = useState(false);
  const [exportNotice, setExportNotice] = useState("");
  const [sort, setSort] =
    useState<TableSort<WeeklySortKey>>(DEFAULT_WEEKLY_SORT);
  const [showEmptyWeeks, setShowEmptyWeeks] = useState(false);

  const view = selectView(snapshot, weekDefinition);
  const weekly = useMemo(() => selectWeekly(view), [view]);
  const cohortLabel = COHORT_LABELS[weekDefinition];
  const updatedAt = formatUpdatedAt(snapshot.generated_at);
  const currentWeek = weekly.reduce(
    (latest, row) => row.cohort_week > latest ? row.cohort_week : latest,
    "",
  );

  const sourceRows = useMemo<WeeklyTableRow[]>(
    () =>
      weekly.map((row) => ({
        key: row.cohort_week,
        cells: weeklyExportCells(row, weekDefinition),
        isCurrentWeek: row.cohort_week === currentWeek,
        source: row,
      })),
    [currentWeek, weekly, weekDefinition],
  );

  const rows = useMemo(() => {
    const column =
      WEEKLY_SORT_COLUMNS.find((item) => item.key === sort.key) ??
      WEEKLY_SORT_COLUMNS[0];
    const deterministic = stableSortRows(
      sourceRows,
      (row) => row.source.cohort_week,
      "desc",
    );
    return stableSortRows(
      deterministic,
      (row) => column?.value(row.source),
      sort.direction,
    );
  }, [sort, sourceRows]);

  const columns = useMemo(
    () =>
      WEEKLY_SORT_COLUMNS.map((column) =>
        columnHelper.accessor((row) => row.cells[column.exportIndex] ?? "—", {
          id: column.key,
          header: column.label,
        }),
      ),
    [],
  );

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const exportOptions = useMemo(
    () => ({ cohortLabel, updatedAt, weekDefinition }),
    [cohortLabel, updatedAt, weekDefinition],
  );
  const emptyWeekCount = rows.filter((row) => !row.source.has_data).length;
  const isCustomSort =
    sort.key !== DEFAULT_WEEKLY_SORT.key ||
    sort.direction !== DEFAULT_WEEKLY_SORT.direction;

  const toggleColumns = useCallback(() => {
    setAllColumns((current) => {
      const next = !current;
      if (!next && !MOBILE_CORE_COLUMNS.has(sort.key)) {
        setSort(DEFAULT_WEEKLY_SORT);
      }
      return next;
    });
  }, [sort.key]);

  const copyTsv = useCallback(() => {
    const tsv = buildWeeklyTsv(weekly, exportOptions);
    const clipboard = navigator.clipboard;
    if (clipboard === undefined) {
      setExportNotice("Trình duyệt không cho phép chép tự động. Hãy tải CSV.");
      return;
    }
    void clipboard.writeText(tsv).then(
      () => setExportNotice("Đã chép bảng báo cáo tuần dạng TSV."),
      () => setExportNotice("Không chép được vào clipboard. Hãy tải CSV."),
    );
  }, [weekly, exportOptions]);

  const downloadCsv = useCallback(() => {
    download(
      `zalopay-bao-cao-tuan-${weekDefinition}.csv`,
      buildWeeklyCsv(weekly, exportOptions),
      "text/csv;charset=utf-8",
    );
    setExportNotice("Đã tải CSV báo cáo tuần.");
  }, [weekly, exportOptions, weekDefinition]);

  return (
    <section id="weekly" className={styles.section} aria-labelledby="weekly-title">
      <div className={styles.sectionHead}>
        <div>
          <h2 id="weekly-title" className={styles.sectionTitle}>
            Báo cáo tuần {cohortLabel}
          </h2>
        </div>
        <div className={styles.controls}>
          <button
            id="weeklyCopyButton"
            type="button"
            className={styles.action}
            onClick={copyTsv}
          >
            Chép TSV
          </button>
          <button
            id="weeklyCsvButton"
            type="button"
            className={styles.action}
            onClick={downloadCsv}
          >
            Tải CSV
          </button>
          <button
            type="button"
            className={`${styles.action} ${styles.columnsToggle}`}
            aria-pressed={allColumns}
            onClick={toggleColumns}
          >
            {allColumns ? "Rút gọn cột" : "Xem đủ cột"}
          </button>
        </div>
      </div>

      {/*
        The caption is the table's accessible name, so it says what the table is
        and how fresh it is. Column count is visible by looking, the WTD marker
        and empty-week label are visible in the rows, and the sort state is
        already carried by `aria-sort` on every header. None is repeated here.
      */}
      <p
        id="weekly-caption"
        className={styles.tableCaption}
        aria-live="polite"
      >
        {`Báo cáo tuần ${cohortLabel} · cập nhật ${updatedAt}`}
      </p>

      {/*
        Sorting the view does not reorder the export. Worth saying at the moment
        it becomes true, and silence otherwise.
      */}
      {isCustomSort ? (
        <p className={styles.sectionNote}>
          TSV và CSV vẫn giữ thứ tự tuần mới nhất.
        </p>
      ) : null}

      <div
        className={styles.tableScroll}
        tabIndex={0}
        role="region"
        aria-labelledby="weekly-caption"
      >
        <table
          className={`${styles.table} ${allColumns ? styles.allColumns : ""}`}
          aria-labelledby="weekly-caption"
        >
          <thead>
            <tr className={styles.weeklyGroupRow}>
              {WEEKLY_COLUMN_GROUPS.map((group) => (
                <th
                  key={group.label}
                  scope="colgroup"
                  colSpan={group.span}
                  className={styles.weeklyGroupHeader}
                >
                  {group.label}
                </th>
              ))}
            </tr>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className={styles.weeklyColumnRow}>
                {headerGroup.headers.map((header, index) => {
                  const sortColumn = WEEKLY_SORT_COLUMNS[index];
                  const active = sortColumn?.key === sort.key;
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      className={`${index === 0 ? styles.stickyColumn : styles.numeric} ${
                        sortColumn !== undefined && MOBILE_CORE_COLUMNS.has(sortColumn.key)
                          ? ""
                          : styles.optionalColumn
                      }`}
                      aria-sort={
                        active
                          ? sort.direction === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                      }
                    >
                      {sortColumn === undefined ? (
                        flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )
                      ) : (
                        <DataTableSortButton
                          label={sortColumn.label}
                          active={active}
                          direction={sort.direction}
                          align={index === 0 ? "start" : "end"}
                          onClick={() =>
                            setSort((current) =>
                              toggleTableSort(
                                current,
                                sortColumn.key,
                                sortColumn.initialDirection,
                              ),
                            )
                          }
                        />
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody id="weeklyRows">
            {table
              .getRowModel()
              .rows.filter(
                (row) => showEmptyWeeks || row.original.source.has_data,
              )
              .map((row) => (
              <tr
                key={row.original.key}
                className={
                  row.original.isCurrentWeek ? styles.currentWeekRow : undefined
                }
                data-current-week={row.original.isCurrentWeek ? "true" : undefined}
              >
                {row.getVisibleCells().map((cell, index) => {
                  const value = cell.getValue<string>();
                  const sortColumn = WEEKLY_SORT_COLUMNS[index];
                  const className = `${index === 0 ? styles.stickyColumn : styles.numeric} ${
                    sortColumn !== undefined && MOBILE_CORE_COLUMNS.has(sortColumn.key)
                      ? ""
                      : styles.optionalColumn
                  } ${value === EMPTY_WEEK_LABEL || value === "—" ? styles.emptyCell : ""}`;
                  return index === 0 ? (
                    <th
                      key={cell.id}
                      scope="row"
                      className={className}
                      aria-current={
                        row.original.isCurrentWeek ? "date" : undefined
                      }
                    >
                      {value}
                    </th>
                  ) : (
                    <td key={cell.id} className={className}>
                      {value}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {emptyWeekCount === 0 ? null : (
        <button
          type="button"
          className={styles.action}
          aria-pressed={showEmptyWeeks}
          onClick={() => setShowEmptyWeeks((current) => !current)}
        >
          {showEmptyWeeks
            ? "Ẩn tuần không có dữ liệu"
            : `+ ${emptyWeekCount} tuần không có dữ liệu`}
        </button>
      )}

      <p aria-live="polite" className={styles.caption}>
        {exportNotice}
      </p>
    </section>
  );
}
