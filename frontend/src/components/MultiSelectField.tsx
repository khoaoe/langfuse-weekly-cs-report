import { useRef } from "react";

import styles from "./ticket-explorer.module.css";

export interface MultiSelectOption {
  readonly value: string;
  readonly label: string;
}

export interface MultiSelectFieldProps {
  readonly id: string;
  readonly label: string;
  readonly options: readonly MultiSelectOption[];
  /** Comma-separated selected values, same convention as the `cohort_weeks` filter. */
  readonly value: string;
  readonly onChange: (value: string) => void;
}

function splitSelected(value: string): readonly string[] {
  return value === "" ? [] : value.split(",");
}

/**
 * Ticket Explorer's multi-select dimension filter: a native `<details>`
 * disclosure holding a checkbox per option, same zero-dependency pattern as
 * `DateRangeField`. The value stays a single comma-separated string so every
 * caller (query building, active-filter chips, URL-free component state)
 * keeps working with a bare single value exactly as before.
 */
export function MultiSelectField({
  id,
  label,
  options,
  value,
  onChange,
}: MultiSelectFieldProps) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const selected = splitSelected(value);

  const close = () => {
    detailsRef.current?.removeAttribute("open");
  };

  const toggle = (option: string) => {
    const next = selected.includes(option)
      ? selected.filter((item) => item !== option)
      : [...selected, option];
    onChange(next.join(","));
  };

  const summary =
    selected.length === 0
      ? "Tất cả"
      : selected.length === 1
        ? (options.find((option) => option.value === selected[0])?.label ??
          selected[0])
        : `${selected.length} đã chọn`;

  return (
    <div className={styles.field}>
      <span id={`${id}Label`}>{label}</span>
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
          id={`${id}Button`}
          role="button"
          className={styles.dateRangeSummary}
          aria-label={`${label}: ${summary}`}
        >
          {summary}
        </summary>
        <div
          id={id}
          className={styles.multiSelectPanel}
          role="group"
          aria-labelledby={`${id}Label`}
        >
          {selected.length === 0 ? null : (
            <button
              type="button"
              className={styles.dateRangeQuickButton}
              onClick={() => onChange("")}
            >
              Xoá lựa chọn
            </button>
          )}
          <div className={styles.multiSelectOptions}>
            {options.map((option) => (
              <label key={option.value} className={styles.multiSelectOption}>
                <input
                  type="checkbox"
                  checked={selected.includes(option.value)}
                  onChange={() => toggle(option.value)}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        </div>
      </details>
    </div>
  );
}
