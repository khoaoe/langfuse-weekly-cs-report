import { useRef, useState } from "react";

import styles from "./ticket-explorer.module.css";

export interface MultiSelectOption {
  readonly value: string;
  readonly label: string;
}

/** Reserved value meaning "any real value" for this dimension (C6) --
 * matches the server sentinel handled by `_parse_multi_ticket_filter`. */
const HAS_VALUE = "__has_value__";

export interface MultiSelectFieldProps {
  readonly id: string;
  readonly label: string;
  readonly options: readonly MultiSelectOption[];
  /** Comma-separated selected values, same convention as the `cohort_weeks` filter. */
  readonly value: string;
  readonly onChange: (value: string) => void;
  /**
   * When set, shows a "Tất cả" / `hasValueLabel` radio row above the
   * checkbox list (C6). The label must name the dimension's own noun (e.g.
   * "Chỉ ticket có lỗi") rather than a generic "Tất cả có giá trị" -- two
   * adjacent options that differ only by a trailing adjective invite the
   * exact mix-up this radio exists to prevent.
   */
  readonly hasValueLabel?: string;
}

/** From this many options the list outgrows its 260px panel (~9 rows) and
 * has to scroll, so a search box starts paying for itself. */
export const SEARCH_THRESHOLD = 10;

/** Case- and accent-insensitive, so "chuyen" finds "Chuyển CS". */
function fold(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/đ/gi, "d")
    .toLowerCase();
}

function splitSelected(value: string): readonly string[] {
  return value === "" || value === HAS_VALUE ? [] : value.split(",");
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
  hasValueLabel,
}: MultiSelectFieldProps) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const [query, setQuery] = useState("");
  const searchable = options.length >= SEARCH_THRESHOLD;
  const needle = fold(query.trim());
  const shown =
    needle === ""
      ? options
      : options.filter(
          (option) =>
            fold(option.label).includes(needle) ||
            fold(option.value).includes(needle),
        );
  const hasValueMode = value === HAS_VALUE;
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

  const summary = hasValueMode
    ? hasValueLabel
    : selected.length === 0
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
        onToggle={(event) => {
          if (!event.currentTarget.open) setQuery("");
        }}
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
          {/* A selected value can be far longer than the control (a
              `<tool>:<CODE>` pair runs to 64 characters), so the text is
              clipped to one line and the full value stays reachable via the
              tooltip and the active-filter chip below the form. */}
          <span className={styles.summaryText} title={summary}>
            {summary}
          </span>
        </summary>
        <div
          id={id}
          className={styles.multiSelectPanel}
          role="group"
          aria-labelledby={`${id}Label`}
        >
          {hasValueLabel === undefined ? null : (
            <div
              className={styles.hasValueRadioRow}
              role="radiogroup"
              aria-label={label}
            >
              <label className={styles.hasValueRadioOption}>
                <input
                  type="radio"
                  name={`${id}Mode`}
                  checked={!hasValueMode}
                  onChange={() => onChange("")}
                />
                <span>Tất cả</span>
              </label>
              <label className={styles.hasValueRadioOption}>
                <input
                  type="radio"
                  name={`${id}Mode`}
                  checked={hasValueMode}
                  onChange={() => onChange(HAS_VALUE)}
                />
                <span>{hasValueLabel}</span>
              </label>
            </div>
          )}
          {selected.length === 0 && !hasValueMode ? null : (
            <button
              type="button"
              className={styles.dateRangeQuickButton}
              onClick={() => onChange("")}
            >
              Xoá lựa chọn
            </button>
          )}
          {searchable ? (
            <input
              type="search"
              className={styles.multiSelectSearch}
              aria-label={`Tìm trong ${label}`}
              placeholder="Gõ để tìm…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          ) : null}
          <div className={styles.multiSelectOptions}>
            {shown.length === 0 ? (
              <span className={styles.multiSelectEmpty}>Không có lựa chọn khớp</span>
            ) : null}
            {shown.map((option) => (
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
