import styles from "./filter-value-button.module.css";

export interface FilterValueButtonProps {
  readonly label: string;
  readonly filterLabel: string;
  readonly onClick: () => void;
}

/**
 * A table value that drills into Ticket Explorer.
 *
 * It deliberately reads like ordinary table text instead of a web link. The
 * quiet filter glyph communicates the action without turning every row label
 * blue or underlined, while the accessible name states the destination.
 */
export function FilterValueButton({
  label,
  filterLabel,
  onClick,
}: FilterValueButtonProps) {
  return (
    <button
      type="button"
      className={styles.button}
      aria-label={`Lọc Ticket Explorer theo ${filterLabel}: ${label}`}
      onClick={onClick}
    >
      <span>{label}</span>
      <svg
        className={styles.icon}
        viewBox="0 0 16 16"
        width="14"
        height="14"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M2 3h12L9.25 8.4v3.35L6.75 13V8.4L2 3Z" />
      </svg>
    </button>
  );
}
