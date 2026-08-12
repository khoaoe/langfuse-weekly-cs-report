import { formatCount } from "../lib/format";
import styles from "./pagination.module.css";

type PaginationItem = number | "gap-before" | "gap-after";

function paginationItems(
  currentPage: number,
  pageCount: number,
): readonly PaginationItem[] {
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }
  if (currentPage <= 4) {
    return [1, 2, 3, 4, 5, "gap-after", pageCount];
  }
  if (currentPage >= pageCount - 3) {
    return [
      1,
      "gap-before",
      pageCount - 4,
      pageCount - 3,
      pageCount - 2,
      pageCount - 1,
      pageCount,
    ];
  }
  return [
    1,
    "gap-before",
    currentPage - 1,
    currentPage,
    currentPage + 1,
    "gap-after",
    pageCount,
  ];
}

/**
 * Numbered page buttons with an ellipsis window, shared by every list in the
 * dashboard that paginates (CSAT feedback, Ticket Explorer, ...). Collapses
 * to "Trang trước / Trang X / Y / Trang sau" under 700px so it never wraps.
 */
export function Pagination({
  currentPage,
  pageCount,
  onPageChange,
  ariaLabel,
}: {
  readonly currentPage: number;
  readonly pageCount: number;
  readonly onPageChange: (page: number) => void;
  readonly ariaLabel: string;
}) {
  if (pageCount <= 1) {
    return null;
  }

  return (
    <nav className={styles.pagination} aria-label={ariaLabel}>
      {currentPage > 1 ? (
        <button
          type="button"
          className={styles.paginationStep}
          onClick={() => onPageChange(currentPage - 1)}
        >
          Trang trước
        </button>
      ) : null}
      <div className={styles.paginationNumbers}>
        {paginationItems(currentPage, pageCount).map((item) =>
          typeof item === "number" ? (
            <button
              key={item}
              type="button"
              className={`${styles.paginationPage} ${
                item === currentPage ? styles.paginationCurrent : ""
              }`}
              aria-label={`Trang ${item}`}
              aria-current={item === currentPage ? "page" : undefined}
              onClick={() => onPageChange(item)}
            >
              {item}
            </button>
          ) : (
            <span key={item} className={styles.paginationGap} aria-hidden="true">
              …
            </span>
          ),
        )}
      </div>
      <span className={styles.paginationCompact}>
        {`Trang ${formatCount(currentPage)} / ${formatCount(pageCount)}`}
      </span>
      {currentPage < pageCount ? (
        <button
          type="button"
          className={styles.paginationStep}
          onClick={() => onPageChange(currentPage + 1)}
        >
          Trang sau
        </button>
      ) : null}
    </nav>
  );
}
