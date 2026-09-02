import type { DashboardSnapshot } from "../lib/dashboard-schema";
import { formatRate } from "../lib/format";
import { selectCoverage } from "../lib/selectors";
import { calculateDataQualityScore, formatDataAge } from "../lib/data-quality-score";
import styles from "./dashboard.module.css";
import belowFoldStyles from "./below-fold.module.css";

/**
 * §7 of the layout: the only place that answers "can I trust these numbers?".
 *
 * SPEC-v2 §5.13 rules out a blended score, a gauge and a header badge: a
 * single number mixing freshness with five coverage dimensions cannot be
 * explained, and coverage is measured over the whole period while the page
 * shows one week. So this panel states the facts it can defend and nothing
 * else -- when the snapshot was taken, how complete each grouping dimension
 * is, and what the missing share does and does not mean.
 */
export function DataTrustSection({
  snapshot,
}: {
  readonly snapshot: DashboardSnapshot;
}) {
  const coverage = selectCoverage(snapshot);
  const belowFloor = coverage.filter((item) => item.belowFloor);
  const weakest = coverage[0];
  const { ageMs } = calculateDataQualityScore(snapshot);
  const snapshotTime = new Date(snapshot.generated_at).toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
  });
  // A dimension under its P0 floor outranks a merely low one: Intent is
  // routinely the thinnest column and carries no floor, so leading with it
  // would bury the only line here that changes what a reader may conclude.
  const headlined = belowFloor.length > 0 ? belowFloor : weakest === undefined ? [] : [weakest];
  const named = headlined
    .map((item) => `${item.label} ${formatRate(item.value)}`)
    .join(", ");
  const summary =
    headlined.length === 0
      ? `Bản dữ liệu lúc ${snapshotTime}`
      : belowFloor.length > 0
        ? `Bản dữ liệu lúc ${snapshotTime} · dưới sàn P0: ${named}`
        : `Bản dữ liệu lúc ${snapshotTime} · chiều phủ thấp nhất: ${named}`;

  return (
    <section
      id="data-trust"
      className={styles.section}
      aria-labelledby="data-trust-title"
    >
      <div className={styles.sectionHead}>
        <div>
          <h2 id="data-trust-title" className={styles.sectionTitle}>
            Dữ liệu này đáng tin tới đâu
          </h2>
        </div>
      </div>
      <details className={styles.qualityDisclosure}>
        <summary className={styles.qualitySummary}>
          <span>{summary}</span>
          <span className={styles.disclosureHint}>Chi tiết</span>
        </summary>
        <div className={styles.qualityContent}>
          <p className={styles.sectionNote}>
            {`Snapshot Langfuse lấy lúc ${snapshotTime}, cách đây ${formatDataAge(ageMs)}.`}
          </p>
          <div
            className={styles.tableScroll}
            tabIndex={0}
            role="region"
            aria-label="Độ phủ theo chiều phân nhóm"
          >
            <table className={styles.table} aria-labelledby="data-trust-title">
              <thead>
                <tr>
                  <th scope="col" className={styles.stickyColumn}>
                    Chiều phân nhóm
                  </th>
                  <th scope="col" className={styles.numeric}>
                    Ticket có dữ liệu
                  </th>
                  <th scope="col">Sàn P0</th>
                </tr>
              </thead>
              <tbody>
                {coverage.map((item) => (
                  <tr key={item.key}>
                    <th scope="row" className={styles.stickyColumn}>
                      {item.label}
                    </th>
                    <td className={styles.numeric}>{formatRate(item.value)}</td>
                    <td>
                      {item.floor === null
                        ? "—"
                        : item.belowFloor
                          ? `Dưới sàn ${formatRate(item.floor)}`
                          : `Đạt sàn ${formatRate(item.floor)}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {weakest === undefined ? null : (
            <p className={belowFoldStyles.diagnosticFacts}>
              {`${formatRate(1 - weakest.value)} ticket không có dữ liệu ${weakest.label} nên không lọc được theo chiều đó. Đây là mức đầy đủ của instrumentation, không phải tỷ lệ ticket chưa được xử lý.`}
            </p>
          )}
          <p className={styles.sectionNote}>
            Mẫu số của mọi tỷ lệ trên là toàn bộ ticket T2–CN trong toàn kỳ,
            không cùng phạm vi với tuần và cohort đang xem ở trên.
          </p>
        </div>
      </details>
    </section>
  );
}
