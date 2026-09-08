import { useMemo } from "react";

import type { AiReviewBucket, WeekDefinition } from "../lib/dashboard-schema";
import { formatCount } from "../lib/format";
import { Legend, SplitBar, TimeChart, guardedRate, type BucketDef } from "./CsatCharts";
import chartStyles from "./csat-charts.module.css";

type AiReviewRatingKey = "needs_edit_count" | "satisfied_with_edit_count" | "satisfied_count";

/**
 * Worst first, same convention as CSAT's `CSAT_BUCKETS` (see CsatCharts.tsx).
 * Exported: `AiReviewBreakdownTable`'s inline `Tỉ lệ` column draws the same bar.
 */
export const AI_REVIEW_BUCKETS: readonly BucketDef<AiReviewRatingKey>[] = [
  { key: "needs_edit_count", label: "Cần sửa", className: chartStyles.negative },
  { key: "satisfied_with_edit_count", label: "Đạt, có sửa", className: chartStyles.neutral },
  { key: "satisfied_count", label: "Đạt", className: chartStyles.positive },
];

export interface AiReviewChartsProps {
  readonly data: AiReviewBucket;
  /** The scope's own buckets, in key order -- the trend, already scoped. */
  readonly buckets: readonly (readonly [string, AiReviewBucket])[];
  readonly dayGrain: boolean;
  readonly weekDefinition: WeekDefinition;
}

export function AiReviewCharts({
  data,
  buckets,
  dayGrain,
  weekDefinition,
}: AiReviewChartsProps) {
  const timeBuckets = useMemo(
    () =>
      [...buckets]
        .sort(([left], [right]) => left.localeCompare(right))
        .filter(([, bucket]) => bucket.reviewed_ticket_count > 0),
    [buckets],
  );

  if (data.reviewed_ticket_count === 0) {
    return null;
  }

  return (
    <div className={chartStyles.charts}>
      <div className={chartStyles.headline}>
        <p className={chartStyles.headlineFigure}>
          <strong className={chartStyles.headlineValue}>
            {guardedRate(data.needs_edit_count, data.rated_ticket_count)}
          </strong>
          <span className={chartStyles.headlineLabel}>ticket có nhãn bị chấm “Cần sửa”</span>
        </p>
        {/* Three denominators, all printed: `evaluated_ticket_count` (Đã
            đánh giá -- rated OR reviewed>=1), `unrated_reviewed_ticket_count`
            (Chưa đánh giá lại -- reviewed but never rated), and
            `reviewed_ticket_count` (a SUM over rated tickets only). None can
            stand in for another. */}
        <p className={chartStyles.headlineSupport}>
          {`${formatCount(data.evaluated_ticket_count)} đã đánh giá / ${formatCount(data.unrated_reviewed_ticket_count)} chưa đánh giá lại / ${formatCount(data.reviewed_ticket_count)} số lần hậu kiểm`}
        </p>
        <SplitBar
          buckets={AI_REVIEW_BUCKETS}
          counts={data}
          total={data.rated_ticket_count}
          label={AI_REVIEW_BUCKETS.map(
            (bucket) => `${bucket.label} ${formatCount(data[bucket.key])}`,
          ).join(", ")}
        />
        <Legend buckets={AI_REVIEW_BUCKETS} counts={data} total={data.rated_ticket_count} />
      </div>

      {timeBuckets.length > 1 ? (
        <div className={chartStyles.panel}>
          <h3 className={chartStyles.panelTitle}>
            {dayGrain ? "Từng ngày mở ticket" : "Từng tuần mở ticket"}
          </h3>
          <p className={chartStyles.panelNote}>
            Cột cao là ngày nhiều ticket có nhãn. Dải đỏ nằm dưới đáy để so được giữa các cột.
          </p>
          <TimeChart
            series={timeBuckets}
            buckets={AI_REVIEW_BUCKETS}
            dayGrain={dayGrain}
            weekDefinition={weekDefinition}
            regionLabel="Hậu kiểm theo thời gian"
            svgLabel={(maxTotal) =>
              `Số ticket có nhãn hậu kiểm theo ${dayGrain ? "ngày" : "tuần"}, xếp chồng theo mức đánh giá, cao nhất ${formatCount(maxTotal)} ticket.`
            }
            tooltipFor={(total, counts) =>
              `${formatCount(total)} ticket có nhãn · Cần sửa ${formatCount(counts.needs_edit_count)}`
            }
          />
        </div>
      ) : null}
    </div>
  );
}
