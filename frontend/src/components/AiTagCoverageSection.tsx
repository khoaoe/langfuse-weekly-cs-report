import { useMemo, useState } from "react";

import type { AiTagCoverage, AiTagCoverageBucket } from "../lib/dashboard-schema";
import { formatCount, formatRate, formatUpdatedAt, share } from "../lib/format";
import { selectScopeDays } from "../lib/report-scope";
import type { DayRangeScope } from "../lib/report-scope";
import { FreshdeskTicketLink } from "./FreshdeskTicketLink";
import styles from "./dashboard.module.css";
import entryStyles from "./entry-coverage.module.css";

interface AiTagCoverageSectionProps {
  readonly aiTagCoverage: AiTagCoverage | null;
  /** Day-range mode: a sentence naming the scope actually being counted (§5.15). */
  readonly scopeNote?: string;
  /** Day-range mode: the inclusive range the reader picked. */
  readonly dayRange?: DayRangeScope;
}

type Panel = "missed" | "untagged" | null;

function percentage(count: number, total: number): string {
  return total === 0 ? "—" : formatRate(share(count, total));
}

/** Combines disjoint per-bucket rows into one range total; a ticket belongs to exactly one week/day. */
function combineBuckets(buckets: readonly AiTagCoverageBucket[]): {
  aiTaggedCount: number;
  missedIds: readonly string[];
  untaggedIds: readonly string[];
  unionCount: number;
} {
  const aiTaggedCount = buckets.reduce((sum, bucket) => sum + bucket.ai_tagged_count, 0);
  const byTicketId = (a: string, b: string) => Number(a) - Number(b);
  const missedIds = [...new Set(buckets.flatMap((bucket) => bucket.missed_ticket_ids))].sort(
    byTicketId,
  );
  const untaggedIds = [
    ...new Set(buckets.flatMap((bucket) => bucket.untagged_ticket_ids)),
  ].sort(byTicketId);
  return {
    aiTaggedCount,
    missedIds,
    untaggedIds,
    unionCount: aiTaggedCount + untaggedIds.length,
  };
}

export function AiTagCoverageSection({
  aiTagCoverage,
  scopeNote,
  dayRange,
}: AiTagCoverageSectionProps) {
  const [openPanel, setOpenPanel] = useState<Panel>(null);
  const weeks = useMemo(
    () => (aiTagCoverage === null ? [] : Object.keys(aiTagCoverage.by_week).sort()),
    [aiTagCoverage],
  );
  const scopeDays = useMemo(
    () =>
      aiTagCoverage === null || dayRange === undefined
        ? null
        : selectScopeDays(aiTagCoverage.by_day, dayRange),
    [aiTagCoverage, dayRange],
  );
  const bucketKeys = scopeDays ?? weeks;

  if (aiTagCoverage === null || bucketKeys.length === 0) {
    return (
      <section
        id="ai-tag-coverage"
        className={styles.section}
        aria-labelledby="ai-tag-coverage-title"
      >
        <h2 id="ai-tag-coverage-title" className={styles.sectionTitle}>
          Độ phủ #AI từ Freshdesk
        </h2>
        <p className={entryStyles.empty}>
          {aiTagCoverage === null
            ? "Chưa có dữ liệu tag #AI từ Freshdesk."
            : "Chưa có dữ liệu tag #AI từ Freshdesk trong phạm vi đang chọn."}
        </p>
        {scopeNote === undefined ? null : (
          <p id="ai-tag-coverage-scope" className={styles.sectionNote}>
            {scopeNote}
          </p>
        )}
      </section>
    );
  }

  const source = scopeDays === null ? aiTagCoverage.by_week : aiTagCoverage.by_day;
  const { missedIds, untaggedIds, unionCount } = useMemo(() => {
    const rows = bucketKeys.flatMap((key) => (source[key] === undefined ? [] : [source[key]]));
    return combineBuckets(rows);
  }, [bucketKeys, source]);

  const metricRows: readonly {
    readonly key: Panel;
    readonly label: string;
    readonly count: number;
    readonly ids: readonly string[] | null;
  }[] = [
    { key: null, label: "Tổng (hợp #AI và Langfuse)", count: unionCount, ids: null },
    {
      key: "missed",
      label: "AI agent xử lý nhưng Langfuse chưa ghi nhận",
      count: missedIds.length,
      ids: missedIds,
    },
    {
      key: "untagged",
      label: "Có trace nhưng thiếu tag #AI trên Freshdesk",
      count: untaggedIds.length,
      ids: untaggedIds,
    },
  ];
  const panelIds = openPanel === "missed" ? missedIds : openPanel === "untagged" ? untaggedIds : [];
  const panelLabel = metricRows.find((row) => row.key === openPanel)?.label ?? "";

  return (
    <section
      id="ai-tag-coverage"
      className={styles.section}
      aria-labelledby="ai-tag-coverage-title"
    >
      <div className={styles.sectionHead}>
        <h2 id="ai-tag-coverage-title" className={styles.sectionTitle}>
          Độ phủ #AI từ Freshdesk
        </h2>
        <span className={entryStyles.fetchedAt}>
          Cập nhật {formatUpdatedAt(aiTagCoverage.fetched_at)}
        </span>
      </div>
      <p className={styles.sectionNote}>
        So khớp tập ticket gắn tag #AI trên Freshdesk với tập ticket Langfuse đã ghi nhận, mỗi
        bên xét theo tuần của chính nó để tránh lệch tuần giữa hai nguồn.
      </p>
      {scopeNote === undefined ? null : (
        <p id="ai-tag-coverage-scope" className={styles.sectionNote}>
          {scopeNote}
        </p>
      )}
      <div className={entryStyles.flow} role="list" aria-label="Độ phủ #AI Freshdesk">
        {metricRows.map((metric) => (
          <div key={metric.label} className={entryStyles.flowRow} role="listitem">
            <span className={entryStyles.flowLabel}>{metric.label}</span>
            <span className={entryStyles.flowValue}>{formatCount(metric.count)}</span>
            <span className={entryStyles.flowShare}>{percentage(metric.count, unionCount)}</span>
            {metric.key === null ? null : (
              <button
                type="button"
                className={entryStyles.investigateButton}
                aria-pressed={openPanel === metric.key}
                disabled={metric.count === 0}
                onClick={() =>
                  setOpenPanel((current) => (current === metric.key ? null : metric.key))
                }
              >
                Xem ticket
              </button>
            )}
          </div>
        ))}
      </div>
      {openPanel === null ? null : (
        <div className={entryStyles.detail} aria-live="polite">
          <h3 className={entryStyles.detailTitle}>{panelLabel}</h3>
          {panelIds.length === 0 ? (
            <p className={entryStyles.empty}>Không có ticket trong phạm vi đang chọn.</p>
          ) : (
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Ticket</th>
                  </tr>
                </thead>
                <tbody>
                  {panelIds.map((ticketId) => (
                    <tr key={ticketId}>
                      <td>
                        <FreshdeskTicketLink ticketId={ticketId} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
