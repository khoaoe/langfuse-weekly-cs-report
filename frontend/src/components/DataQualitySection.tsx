import type {
  DashboardSnapshot,
} from "../lib/dashboard-schema";
import {
  calculateDataQualityScore,
  formatDataAge,
} from "../lib/data-quality-score";
import {
  formatCount,
  formatRate,
  formatUpdatedAt,
} from "../lib/format";
import { selectWeakestCoverage } from "../lib/selectors";
import styles from "./dashboard.module.css";

interface DataQualitySectionProps {
  readonly snapshot: DashboardSnapshot;
  readonly qualityExpanded: boolean;
  readonly onQualityExpandedChange: (expanded: boolean) => void;
}

export function DataQualitySection({
  snapshot,
  qualityExpanded,
  onQualityExpandedChange,
}: DataQualitySectionProps) {
  const qualityScore = calculateDataQualityScore(snapshot);
  const weakest = selectWeakestCoverage(snapshot);
  const allPeriod = snapshot.views.mon_sun;
  const allPeriodWeekCount = allPeriod.weekly.filter(
    (week) => week.has_data,
  ).length;

  return (
    <section id="quality" className={styles.section} aria-labelledby="quality-title">
      <details
        id="coveragePanel"
        className={styles.qualityDisclosure}
        open={qualityExpanded}
        onToggle={(event) => {
          if (event.currentTarget.open !== qualityExpanded) {
            onQualityExpandedChange(event.currentTarget.open);
          }
        }}
      >
        <summary id="qualitySummary" className={styles.qualitySummary}>
          <span
            id="quality-title"
            className={styles.sectionTitle}
            role="heading"
            aria-level={2}
          >
            Số liệu này đáng tin tới đâu
          </span>
          <span className={styles.disclosureHint}>
            {qualityExpanded ? "Thu gọn" : "Mở chi tiết"}
          </span>
        </summary>

        <div className={styles.qualityContent}>
          <p className={styles.sectionNote}>
            {`Cập nhật ${formatUpdatedAt(
              snapshot.generated_at,
            )}, cách đây ${formatDataAge(
              qualityScore.ageMs,
            )}.`}
          </p>

          {weakest === null ? null : (
            <p className={styles.sectionNote}>
              {`${weakest.label}: ${formatRate(
                1 - weakest.missingShare,
              )} ticket có dữ liệu ${weakest.label} để phân nhóm. ${formatRate(
                weakest.missingShare,
              )} còn lại không lọc theo ${
                weakest.label
              } được — đây là độ đầy đủ dữ liệu, không phải tỷ lệ ticket không được xử lý. Tính trên toàn bộ ${formatCount(
                allPeriod.totals.eligible_ticket_count,
              )} ticket trong ${formatCount(
                allPeriodWeekCount,
              )} tuần, không phải riêng tuần đang xem.`}
            </p>
          )}
        </div>
      </details>
    </section>
  );
}
