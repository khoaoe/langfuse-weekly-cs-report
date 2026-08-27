import { useRef, useState } from "react";

import type { WeekDefinition, WeeklyReportRow } from "../lib/dashboard-schema";
import { formatCount, formatDateRangeLabel, formatWeekRange } from "../lib/format";
import { resolveDateRangeToWeeks } from "../lib/report-scope";
import { DateRangeField } from "./DateRangeField";
import styles from "./dashboard.module.css";

export interface ReportScopePickerProps {
  readonly reportWindow: readonly WeeklyReportRow[];
  readonly selectedWeeks: readonly string[];
  readonly allWeeksSelected: boolean;
  readonly weekDefinition: WeekDefinition;
  readonly onChange: (value: "all" | readonly string[]) => void;
  readonly activeRange?: { readonly from: string; readonly to: string } | null;
  readonly onRangeChange?: (from: string, to: string) => void;
}

export function ReportScopePicker({
  reportWindow,
  selectedWeeks,
  allWeeksSelected,
  weekDefinition,
  onChange,
  activeRange = null,
  onRangeChange = () => {},
}: ReportScopePickerProps) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const [mode, setMode] = useState<"weeks" | "range">(
    activeRange != null ? "range" : "weeks",
  );
  const [rangeError, setRangeError] = useState<string | null>(null);
  const observed = reportWindow
    .filter((week) => week.has_data)
    .toSorted((left, right) =>
      right.cohort_week.localeCompare(left.cohort_week),
    );
  const selected = new Set(
    allWeeksSelected ? observed.map((week) => week.cohort_week) : selectedWeeks,
  );
  const selectedRows = observed.filter((week) => selected.has(week.cohort_week));
  const currentWeek = observed.find((week) => week.cohort_status === "wtd");
  const isOnlyCurrentWeek =
    currentWeek !== undefined &&
    selected.size === 1 &&
    selected.has(currentWeek.cohort_week);
  const summary =
    activeRange != null
      ? `${formatDateRangeLabel(activeRange.from, activeRange.to)} · ${formatCount(selectedRows.length)} tuần`
      : allWeeksSelected
        ? `Toàn bộ kỳ báo cáo (${formatCount(reportWindow.length)} tuần)`
        : selectedRows.length === 1 && selectedRows[0] !== undefined
          ? `${formatWeekRange(
              selectedRows[0].cohort_week,
              weekDefinition,
            )}${selectedRows[0].cohort_status === "wtd" ? " · WTD" : ""}`
          : `${formatCount(selectedRows.length)} tuần đã chọn`;

  const toggleWeek = (cohortWeek: string) => {
    const next = observed
      .map((week) => week.cohort_week)
      .filter((week) =>
        week === cohortWeek ? !selected.has(week) : selected.has(week),
      );
    if (next.length > 0) {
      onChange(next);
    }
  };

  return (
    <div className={styles.reportScopeField}>
      <span>Phạm vi báo cáo</span>
      <details
        ref={detailsRef}
        className={styles.reportScopeDetails}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            detailsRef.current?.removeAttribute("open");
            detailsRef.current?.querySelector("summary")?.focus();
          }
        }}
      >
        <summary
          className={styles.reportScopeSummary}
          aria-label={`Phạm vi báo cáo: ${summary}`}
        >
          <strong>{summary}</strong>
        </summary>
        <div
          className={styles.reportScopePanel}
          role="group"
          aria-label="Chọn tuần cho báo cáo"
        >
          <div
            id="reportScopeModeToggle"
            className={styles.segmented}
            role="group"
            aria-label="Chọn theo tuần hay theo khoảng ngày"
          >
            <button
              type="button"
              className={styles.segmentedButton}
              aria-pressed={mode === "weeks"}
              onClick={() => setMode("weeks")}
            >
              Theo tuần
            </button>
            <button
              type="button"
              className={styles.segmentedButton}
              aria-pressed={mode === "range"}
              onClick={() => setMode("range")}
            >
              Theo khoảng ngày
            </button>
          </div>
          {mode === "weeks" ? (
            <>
              <button
                type="button"
                className={styles.reportScopeAll}
                aria-pressed={allWeeksSelected}
                onClick={() => onChange("all")}
              >
                {`Toàn bộ kỳ báo cáo (${formatCount(reportWindow.length)} tuần)`}
              </button>
              {currentWeek !== undefined && !isOnlyCurrentWeek ? (
                <button
                  type="button"
                  className={styles.reportScopeCurrent}
                  onClick={() => onChange([currentWeek.cohort_week])}
                >
                  {`Về tuần hiện tại · ${formatWeekRange(
                    currentWeek.cohort_week,
                    weekDefinition,
                  )} · WTD`}
                </button>
              ) : null}
              <div className={styles.reportScopeOptions}>
                {observed.map((week) => {
                  const checked = selected.has(week.cohort_week);
                  return (
                    <label
                      key={week.cohort_week}
                      className={styles.reportScopeOption}
                      htmlFor={`reportScope-${week.cohort_week}`}
                    >
                      <input
                        id={`reportScope-${week.cohort_week}`}
                        type="checkbox"
                        checked={checked}
                        disabled={checked && selected.size === 1}
                        onChange={() => toggleWeek(week.cohort_week)}
                      />
                      <span>
                        {formatWeekRange(week.cohort_week, weekDefinition)}
                        {week.cohort_status === "wtd" ? " · WTD" : ""}
                      </span>
                    </label>
                  );
                })}
              </div>
            </>
          ) : (
            <>
              <DateRangeField
                value={activeRange ?? { from: "", to: "" }}
                onChange={({ from, to }) => {
                  if (from === "" && to === "") {
                    setRangeError(null);
                    onRangeChange("", "");
                    return;
                  }
                  const weeks = resolveDateRangeToWeeks(
                    reportWindow,
                    weekDefinition,
                    from,
                    to,
                  );
                  if (weeks.length === 0) {
                    setRangeError(
                      "Không có tuần nào có dữ liệu trong khoảng ngày này. Phạm vi báo cáo giữ nguyên như trước.",
                    );
                    return;
                  }
                  setRangeError(null);
                  onRangeChange(from, to);
                }}
                label="Khoảng ngày báo cáo"
                idPrefix="reportRange"
                clearLabel="Toàn bộ kỳ báo cáo"
              />
              {rangeError !== null ? (
                <p id="reportRangeError" role="status" className={styles.reportScopeError}>
                  {rangeError}
                </p>
              ) : activeRange != null ? (
                <p id="reportRangeSummary" className={styles.reportScopeSummaryLine}>
                  {`${formatDateRangeLabel(activeRange.from, activeRange.to)} → ${selectedRows.length} tuần: ${selectedRows
                    .map((row) => formatWeekRange(row.cohort_week, weekDefinition))
                    .join(", ")}`}
                </p>
              ) : null}
            </>
          )}
        </div>
      </details>
    </div>
  );
}
