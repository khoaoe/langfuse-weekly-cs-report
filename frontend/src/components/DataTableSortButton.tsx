import type { SortDirection } from "../lib/table-sort";
import styles from "./data-table-sort-button.module.css";

export interface DataTableSortButtonProps {
  readonly label: string;
  readonly active: boolean;
  readonly direction: SortDirection;
  readonly align?: "start" | "end";
  readonly onClick: () => void;
}

/**
 * Shared, keyboard-native table-header control.
 *
 * `aria-sort` belongs on the parent `<th>`; this button supplies the visible
 * non-colour indicator and the same accessible name used by Ticket Explorer.
 */
export function DataTableSortButton({
  label,
  active,
  direction,
  align = "start",
  onClick,
}: DataTableSortButtonProps) {
  const directionLabel = direction === "asc" ? "tăng dần" : "giảm dần";
  const nextDirectionLabel = direction === "asc" ? "giảm dần" : "tăng dần";
  const description = active
    ? `Đang ${directionLabel}; nhấn để chuyển sang ${nextDirectionLabel}.`
    : "Chưa là cột sắp xếp; nhấn để sắp xếp cột này.";
  const accessibleLabel = active
    ? `Sắp xếp theo ${label}; hiện ${directionLabel}, bấm để ${nextDirectionLabel}`
    : `Sắp xếp theo ${label}`;

  return (
    <button
      type="button"
      className={`${styles.button} ${align === "end" ? styles.end : ""}`}
      aria-label={accessibleLabel}
      aria-description={description}
      aria-pressed={active}
      onClick={onClick}
    >
      <span>{label}</span>
      <span
        className={`${styles.indicator} ${active ? styles.active : ""} ${
          active ? styles[direction] : styles.unsorted
        }`}
        aria-hidden="true"
      />
    </button>
  );
}
