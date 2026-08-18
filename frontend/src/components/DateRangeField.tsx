import { useRef, useState } from "react";

import { formatDateRangeLabel } from "../lib/format";
import styles from "./ticket-explorer.module.css";

export interface DateRangeValue {
  readonly opened_from: string;
  readonly opened_to: string;
}

export interface DateRangeFieldProps {
  readonly value: DateRangeValue;
  readonly onChange: (value: DateRangeValue) => void;
}

const WEEKDAY_LABELS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];

interface QuickRange {
  readonly label: string;
  readonly days: number;
}

const QUICK_RANGES: readonly QuickRange[] = [
  { label: "7 ngày qua", days: 6 },
  { label: "14 ngày qua", days: 13 },
  { label: "30 ngày qua", days: 29 },
  { label: "90 ngày qua", days: 89 },
];

function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseIsoDateLocal(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return null;
  }
  const [year, month, day] = value.split("-").map(Number);
  if (year === undefined || month === undefined || day === undefined) {
    return null;
  }
  const parsed = new Date(year, month - 1, day);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}

function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function addDays(date: Date, amount: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + amount);
  return next;
}

function addMonths(date: Date, amount: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + amount, 1);
}

/** Calendar grid weeks (Monday-first) covering `month`, including the
 * leading/trailing days from adjacent months needed to fill full weeks. */
function calendarWeeks(month: Date): readonly (readonly Date[])[] {
  const first = startOfMonth(month);
  const firstWeekday = (first.getDay() + 6) % 7; // 0 = Monday
  const gridStart = addDays(first, -firstWeekday);
  const weeks: Date[][] = [];
  for (let week = 0; week < 6; week += 1) {
    const days: Date[] = [];
    for (let day = 0; day < 7; day += 1) {
      days.push(addDays(gridStart, week * 7 + day));
    }
    weeks.push(days);
  }
  return weeks;
}

/**
 * Ticket Explorer's calendar date-range filter, mutually exclusive with the
 * week filter (enforced by the caller via `updateTicketFilters`). No new
 * dependency: the calendar grid and quick presets are plain date arithmetic,
 * matching the repo's zero-added-dependency budget.
 */
export function DateRangeField({ value, onChange }: DateRangeFieldProps) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const initialMonth = startOfMonth(
    parseIsoDateLocal(value.opened_to) ??
      parseIsoDateLocal(value.opened_from) ??
      new Date(),
  );
  const [visibleMonth, setVisibleMonth] = useState(initialMonth);
  const [pendingStart, setPendingStart] = useState<Date | null>(
    parseIsoDateLocal(value.opened_from),
  );
  const [pendingEnd, setPendingEnd] = useState<Date | null>(
    parseIsoDateLocal(value.opened_to),
  );

  const close = () => {
    detailsRef.current?.removeAttribute("open");
  };

  const applyRange = (from: Date, to: Date) => {
    const [start, end] = from.getTime() <= to.getTime() ? [from, to] : [to, from];
    onChange({ opened_from: toIsoDate(start), opened_to: toIsoDate(end) });
    close();
  };

  const applyQuickRange = (days: number) => {
    const today = new Date();
    applyRange(addDays(today, -days), today);
  };

  const clearRange = () => {
    setPendingStart(null);
    setPendingEnd(null);
    onChange({ opened_from: "", opened_to: "" });
    close();
  };

  const pickDay = (day: Date) => {
    if (pendingStart === null || pendingEnd !== null) {
      setPendingStart(day);
      setPendingEnd(null);
      return;
    }
    const start = day.getTime() <= pendingStart.getTime() ? day : pendingStart;
    const end = day.getTime() <= pendingStart.getTime() ? pendingStart : day;
    setPendingStart(start);
    setPendingEnd(end);
    applyRange(start, end);
  };

  const summary =
    value.opened_from === "" && value.opened_to === ""
      ? "Tất cả ngày"
      : formatDateRangeLabel(value.opened_from, value.opened_to);

  const rangeStart = pendingStart;
  const rangeEnd = pendingEnd;
  const inRange = (day: Date): boolean =>
    rangeStart !== null &&
    rangeEnd !== null &&
    day.getTime() >= rangeStart.getTime() &&
    day.getTime() <= rangeEnd.getTime();

  return (
    <div className={styles.field}>
      <span id="openedDateRangeLabel">Khoảng ngày mở</span>
      <details
        ref={detailsRef}
        className={styles.dateRangeDetails}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            close();
            detailsRef.current?.querySelector("summary")?.focus();
          }
        }}
      >
        <summary
          id="openedDateRangeButton"
          className={styles.dateRangeSummary}
          aria-label={`Khoảng ngày mở: ${summary}`}
        >
          {summary}
        </summary>
        <div
          className={styles.dateRangePanel}
          role="group"
          aria-labelledby="openedDateRangeLabel"
        >
          <div className={styles.dateRangeQuick}>
            {QUICK_RANGES.map((range) => (
              <button
                key={range.label}
                type="button"
                className={styles.dateRangeQuickButton}
                onClick={() => applyQuickRange(range.days)}
              >
                {range.label}
              </button>
            ))}
            <button
              type="button"
              className={styles.dateRangeQuickButton}
              onClick={clearRange}
            >
              Tất cả ngày
            </button>
          </div>
          <div className={styles.dateRangeCalendar}>
            <div className={styles.dateRangeCalendarHeader}>
              <button
                type="button"
                aria-label="Tháng trước"
                onClick={() => setVisibleMonth(addMonths(visibleMonth, -1))}
              >
                ‹
              </button>
              <span>
                {visibleMonth.toLocaleDateString("vi-VN", {
                  month: "long",
                  year: "numeric",
                })}
              </span>
              <button
                type="button"
                aria-label="Tháng sau"
                onClick={() => setVisibleMonth(addMonths(visibleMonth, 1))}
              >
                ›
              </button>
            </div>
            <div className={styles.dateRangeWeekdays}>
              {WEEKDAY_LABELS.map((label) => (
                <span key={label}>{label}</span>
              ))}
            </div>
            {calendarWeeks(visibleMonth).map((week) => (
              <div key={week[0]?.getTime()} className={styles.dateRangeWeek}>
                {week.map((day) => {
                  const outsideMonth = day.getMonth() !== visibleMonth.getMonth();
                  const isStart =
                    rangeStart !== null && day.getTime() === rangeStart.getTime();
                  const isEnd =
                    rangeEnd !== null && day.getTime() === rangeEnd.getTime();
                  return (
                    <button
                      key={day.getTime()}
                      type="button"
                      className={styles.dateRangeDay}
                      data-outside={outsideMonth ? "true" : undefined}
                      data-selected={isStart || isEnd ? "true" : undefined}
                      data-in-range={inRange(day) ? "true" : undefined}
                      onClick={() => pickDay(day)}
                    >
                      {day.getDate()}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </details>
    </div>
  );
}
