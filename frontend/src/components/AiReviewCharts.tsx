import { useMemo } from "react";

import type { AiReviewBucket, WeekDefinition } from "../lib/dashboard-schema";
import { PERCENTAGE_SAMPLE_MINIMUM, formatCount } from "../lib/format";
import { aiReviewRowsFor } from "./AiReviewBreakdownTable";
import { csatGroupingLabel, type CsatGrouping } from "./CsatBreakdownTable";
import { Legend, SplitBar, TimeChart, guardedRate, type BucketDef } from "./CsatCharts";
import chartStyles from "./csat-charts.module.css";

type AiReviewRatingKey = "needs_edit_count" | "satisfied_with_edit_count" | "satisfied_count";

/** Worst first, same convention as CSAT's `BUCKETS` (see CsatCharts.tsx). */
const BUCKETS: readonly BucketDef<AiReviewRatingKey>[] = [
  { key: "needs_edit_count", label: "Cần sửa", className: chartStyles.negative },
  { key: "satisfied_with_edit_count", label: "Đạt, có sửa", className: chartStyles.neutral },
  { key: "satisfied_count", label: "Đạt", className: chartStyles.positive },
];

const GROUP_ROW_LIMIT = 8;

export interface AiReviewChartsProps {
  readonly data: AiReviewBucket;
  /** The scope's own buckets, in key order -- the trend, already scoped. */
  readonly buckets: readonly (readonly [string, AiReviewBucket])[];
  readonly grouping: CsatGrouping;
  readonly dayGrain: boolean;
  readonly weekDefinition: WeekDefinition;
}

export function AiReviewCharts({
  data,
  buckets,
  grouping,
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
  // aiReviewRowsFor already returns rows worst-first, small-sample-last; this
  // panel just caps them.
  const groupRows = useMemo(
    () => aiReviewRowsFor(data, grouping).slice(0, GROUP_ROW_LIMIT),
    [data, grouping],
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
        {/* Two denominators, both printed: `reviewed_ticket_count` (hậu kiểm
            ran) and `rated_ticket_count` (a rating label exists). They are
            never the same population, so neither can stand in for the other. */}
        <p className={chartStyles.headlineSupport}>
          {`${formatCount(data.rated_ticket_count)} có nhãn / ${formatCount(data.reviewed_ticket_count)} đã hậu kiểm`}
        </p>
        <SplitBar
          buckets={BUCKETS}
          counts={data}
          total={data.rated_ticket_count}
          label={BUCKETS.map(
            (bucket) => `${bucket.label} ${formatCount(data[bucket.key])}`,
          ).join(", ")}
        />
        <Legend buckets={BUCKETS} counts={data} total={data.rated_ticket_count} />
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
            buckets={BUCKETS}
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

      {groupRows.length > 0 ? (
        <div className={chartStyles.panel}>
          <h3 className={chartStyles.panelTitle}>
            {`${csatGroupingLabel(grouping)} nào bị chấm “Cần sửa” nhiều nhất`}
          </h3>
          <p className={chartStyles.panelNote}>
            Mỗi thanh là ticket có nhãn của nhóm, xếp từ cần sửa nhiều nhất bên trái. Bảng bên
            dưới có số chính xác và nút lọc.
          </p>
          <div className={chartStyles.groupList}>
            {groupRows.map((row) => (
              <div key={`${grouping}:${row.value}`} className={chartStyles.groupRow}>
                <span className={chartStyles.groupLabel}>{row.label}</span>
                <SplitBar
                  buckets={BUCKETS}
                  counts={row}
                  total={row.rated_ticket_count}
                  label={`${row.label}: ${BUCKETS.map(
                    (bucket) => `${bucket.label} ${formatCount(row[bucket.key])}`,
                  ).join(", ")}`}
                />
                <span className={chartStyles.groupValue}>
                  {row.rated_ticket_count < PERCENTAGE_SAMPLE_MINIMUM
                    ? `${formatCount(row.rated_ticket_count)} có nhãn · mẫu nhỏ`
                    : `${guardedRate(row.needs_edit_count, row.rated_ticket_count)} · ${formatCount(row.rated_ticket_count)} có nhãn`}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
