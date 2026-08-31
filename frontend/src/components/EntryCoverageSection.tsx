import { useEffect, useMemo, useState } from "react";

import { fetchEntryCoverageTicketPage } from "../lib/api";
import type {
  EntryCoverage,
  EntryCoverageStatus,
  EntryCoverageTicketPage,
  WeekDefinition,
} from "../lib/dashboard-schema";
import { parseEntryCoverageTicketPage } from "../lib/dashboard-schema";
import { formatCount, formatRate, formatUpdatedAt } from "../lib/format";
import { selectScopeDays } from "../lib/report-scope";
import type { DayRangeScope } from "../lib/report-scope";
import { FreshdeskTicketLink } from "./FreshdeskTicketLink";
import styles from "./dashboard.module.css";
import entryStyles from "./entry-coverage.module.css";

const STATUS_LABELS: Readonly<Record<EntryCoverageStatus, string>> = {
  ai_replied_only: "AI đã phản hồi",
  ai_replied_then_transferred: "AI phản hồi rồi chuyển CS",
  transferred_without_ai_reply: "Chuyển CS không có AI First",
  invoked_no_result: "Đã gọi nhưng không có phản hồi/chuyển CS",
  not_observed_invoked: "Không thấy lần gọi CS-agent",
  unresolved: "Chưa xác định",
};

interface EntryCoverageSectionProps {
  readonly entryCoverage: EntryCoverage | null;
  readonly weekDefinition: WeekDefinition;
  /**
   * Day-range mode: a sentence naming the scope actually being counted —
   * the exact days when the snapshot carries day grain, or the full weeks it
   * had to widen to when it does not (§5.15).
   */
  readonly scopeNote?: string;
  /**
   * Day-range mode: the inclusive range the reader picked. Coverage is cut to
   * exactly these days whenever the snapshot carries `by_day`, matching every
   * other metric on the page.
   */
  readonly dayRange?: DayRangeScope;
}

function percentage(count: number, total: number): string {
  return total === 0 ? "—" : formatRate(count / total);
}

export function EntryCoverageSection({
  entryCoverage,
  weekDefinition,
  scopeNote,
  dayRange,
}: EntryCoverageSectionProps) {
  const [selectedStatus, setSelectedStatus] =
    useState<EntryCoverageStatus | null>(null);
  const [page, setPage] = useState(1);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [ticketPage, setTicketPage] = useState<EntryCoverageTicketPage | null>(null);
  const [ticketLoading, setTicketLoading] = useState(false);
  const [ticketError, setTicketError] = useState(false);
  const weeks = useMemo(
    () => (entryCoverage === null ? [] : Object.keys(entryCoverage.by_week).sort()),
    [entryCoverage],
  );
  // `null` means this snapshot carries no day grain at all, which is the only
  // case that still has to widen to whole weeks. An empty array is a real
  // answer: no ticket opened in the picked range.
  const scopeDays = useMemo(
    () =>
      entryCoverage === null || dayRange === undefined
        ? null
        : selectScopeDays(entryCoverage.by_day, dayRange),
    [entryCoverage, dayRange],
  );
  const bucketKeys = scopeDays ?? weeks;
  useEffect(() => {
    setPage(1);
  }, [selectedStatus, sortDir, bucketKeys.join(",")]);

  useEffect(() => {
    if (entryCoverage === null || selectedStatus === null) {
      setTicketPage(null);
      setTicketLoading(false);
      setTicketError(false);
      return;
    }

    const controller = new AbortController();
    let current = true;
    setTicketLoading(true);
    setTicketError(false);
    void fetchEntryCoverageTicketPage(
      {
        week_definition: weekDefinition,
        cohort_weeks: weeks.join(","),
        // The drill-down has to answer for the same population as the counts
        // above it. In day grain the weeks are only a superset, so the exact
        // window goes down with the request.
        ...(scopeDays === null || dayRange === undefined
          ? {}
          : { opened_from: dayRange.from, opened_to: dayRange.to }),
        status: selectedStatus,
        page,
        page_size: 10,
        sort_by: "opened_at",
        sort_dir: sortDir,
      },
      controller.signal,
    )
      .then((raw) => {
        const parsed = parseEntryCoverageTicketPage(raw);
        if (!parsed.ok) {
          throw new Error(parsed.message);
        }
        if (current) {
          setTicketPage(parsed.data);
        }
      })
      .catch((error: unknown) => {
        if (current && !(error instanceof DOMException && error.name === "AbortError")) {
          setTicketError(true);
          setTicketPage(null);
        }
      })
      .finally(() => {
        if (current) {
          setTicketLoading(false);
        }
      });

    return () => {
      current = false;
      controller.abort();
    };
  }, [
    dayRange,
    entryCoverage,
    page,
    scopeDays,
    selectedStatus,
    sortDir,
    weekDefinition,
    weeks,
  ]);

  if (entryCoverage === null || bucketKeys.length === 0) {
    return (
      <section
        id="entry-coverage"
        className={styles.section}
        aria-labelledby="entry-coverage-title"
      >
        <h2 id="entry-coverage-title" className={styles.sectionTitle}>
          Độ phủ xử lý từ Freshdesk
        </h2>
        <p className={entryStyles.empty}>
          {entryCoverage === null
            ? "Chưa có dữ liệu đối chiếu từ Freshdesk."
            : "Chưa có dữ liệu đối chiếu từ Freshdesk trong phạm vi đang chọn."}
        </p>
        {scopeNote === undefined ? null : (
          <p id="entry-coverage-scope" className={styles.sectionNote}>
            {scopeNote}
          </p>
        )}
      </section>
    );
  }

  // One shape, two grains: the totals below never learn which key selected a
  // bucket, so a day view and a week view can only ever differ in membership.
  const source =
    scopeDays === null ? entryCoverage.by_week : (entryCoverage.by_day ?? {});
  const rows = bucketKeys.flatMap((key) => {
    const value = source[key];
    return value === undefined ? [] : [{ week: key, value }];
  });
  const total = rows.reduce(
    (sum, row) => sum + row.value.freshdesk_ticket_count,
    0,
  );
  const totalFor = (key: keyof (typeof rows)[number]["value"]) =>
    rows.reduce((sum, row) => sum + Number(row.value[key]), 0);

  const metricRows: readonly {
    readonly key: EntryCoverageStatus | "freshdesk_ticket_count";
    readonly label: string;
    readonly investigation: boolean;
  }[] = [
    { key: "freshdesk_ticket_count", label: "Ticket Freshdesk", investigation: false },
    { key: "ai_replied_only", label: STATUS_LABELS.ai_replied_only, investigation: false },
    {
      key: "ai_replied_then_transferred",
      label: STATUS_LABELS.ai_replied_then_transferred,
      investigation: false,
    },
    {
      key: "transferred_without_ai_reply",
      label: STATUS_LABELS.transferred_without_ai_reply,
      investigation: false,
    },
    {
      key: "invoked_no_result",
      label: STATUS_LABELS.invoked_no_result,
      investigation: true,
    },
    {
      key: "not_observed_invoked",
      label: STATUS_LABELS.not_observed_invoked,
      investigation: true,
    },
    { key: "unresolved", label: STATUS_LABELS.unresolved, investigation: true },
  ];

  return (
    <section
      id="entry-coverage"
      className={styles.section}
      aria-labelledby="entry-coverage-title"
    >
      <div className={styles.sectionHead}>
        <h2 id="entry-coverage-title" className={styles.sectionTitle}>
          Độ phủ xử lý từ Freshdesk
        </h2>
        <span className={entryStyles.fetchedAt}>
          Cập nhật {formatUpdatedAt(entryCoverage.fetched_at)}
        </span>
      </div>
      <p className={styles.sectionNote}>
        Freshdesk là tập ticket gốc; đối chiếu từ 06/07/2026 với Langfuse và conversation công khai.
      </p>
      {scopeNote === undefined ? null : (
        <p id="entry-coverage-scope" className={styles.sectionNote}>
          {scopeNote}
        </p>
      )}
      <div className={entryStyles.flow} role="list" aria-label="Độ phủ xử lý Freshdesk">
        {metricRows.map((metric) => {
          const count = totalFor(metric.key);
          const clickable = metric.investigation;
          return (
            <div key={metric.key} className={entryStyles.flowRow} role="listitem">
              <span className={entryStyles.flowLabel}>{metric.label}</span>
              <span className={entryStyles.flowValue}>{formatCount(count)}</span>
              <span className={entryStyles.flowShare}>
                {percentage(count, total)}
              </span>
              {clickable ? (
                <button
                  type="button"
                  className={entryStyles.investigateButton}
                  aria-pressed={selectedStatus === metric.key}
                  onClick={() => {
                    setSelectedStatus(
                      selectedStatus === metric.key
                        ? null
                        : (metric.key as EntryCoverageStatus),
                    );
                  }}
                >
                  Xem ticket
                </button>
              ) : null}
            </div>
          );
        })}
      </div>
      <div className={entryStyles.subcounts}>
        <span>
          CS người đã phản hồi trực tiếp: {formatCount(totalFor("not_observed_human_replied"))}
        </span>
        <span>
          Chưa thấy CS người phản hồi: {formatCount(totalFor("not_observed_no_human_reply"))}
        </span>
      </div>
      {selectedStatus !== null ? (
        <div className={entryStyles.detail} aria-live="polite">
          <div className={styles.sectionHead}>
            <h3 className={entryStyles.detailTitle}>{STATUS_LABELS[selectedStatus]}</h3>
            <button
              type="button"
              className={entryStyles.sortButton}
              onClick={() => setSortDir((current) => (current === "desc" ? "asc" : "desc"))}
            >
              {sortDir === "desc" ? "Mới nhất trước" : "Cũ nhất trước"}
            </button>
          </div>
          {ticketError ? (
            <p className={entryStyles.empty}>Không tải được danh sách ticket Freshdesk.</p>
          ) : ticketLoading ? (
            <p className={entryStyles.empty}>Đang tải danh sách ticket…</p>
          ) : ticketPage?.items.length === 0 ? (
            <p className={entryStyles.empty}>
              Không có ticket trong trạng thái này ở phạm vi đang chọn.
            </p>
          ) : ticketPage === null ? (
            <p className={entryStyles.empty}>Đang tải danh sách ticket…</p>
          ) : (
            <>
              <div className={styles.tableScroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Ticket</th>
                      <th>Thời gian tạo</th>
                      <th>Trạng thái</th>
                      <th>CS người phản hồi trực tiếp</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ticketPage.items.map((item) => (
                      <tr key={item.ticket_id}>
                        <td><FreshdeskTicketLink ticketId={item.ticket_id} /></td>
                        <td><time dateTime={item.opened_at}>{formatUpdatedAt(item.opened_at)}</time></td>
                        <td>{STATUS_LABELS[item.status]}</td>
                        <td>{item.human_replied === null ? "Chưa xác định" : item.human_replied ? "Có" : "Không"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className={entryStyles.pagination}>
                <button
                  type="button"
                  className={entryStyles.pageButton}
                  disabled={page <= 1}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                >
                  Trang trước
                </button>
                <span>{`Trang ${formatCount(ticketPage.page)} · ${formatCount(ticketPage.total)} ticket`}</span>
                <button
                  type="button"
                  className={entryStyles.pageButton}
                  disabled={page * ticketPage.page_size >= ticketPage.total}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Trang sau
                </button>
              </div>
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}
