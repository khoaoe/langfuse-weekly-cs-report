import { useMemo } from "react";

import { scaleBand, scaleLinear } from "@visx/scale";

import type { CsatWeek, WeekDefinition } from "../lib/dashboard-schema";
import {
  PERCENTAGE_SAMPLE_MINIMUM,
  formatCount,
  formatRate,
  formatWeekRange,
  formatWeekStart,
} from "../lib/format";
import {
  csatGroupingLabel,
  csatResponseTotals,
  rowsFor,
  type CsatGrouping,
} from "./CsatBreakdownTable";
import chartStyles from "./csat-charts.module.css";

/**
 * Worst first, everywhere. The bar, the legend and the stacked column all read
 * in this order so the segment a reader acts on always sits against the same
 * edge — the left edge of a bar, the baseline of a column — which is the only
 * position in a stack whose length can be compared accurately by eye.
 */
const BUCKETS = [
  { key: "negative", label: "Rất tệ", className: chartStyles.negative },
  { key: "neutral", label: "Bình thường", className: chartStyles.neutral },
  { key: "positive", label: "Rất hài lòng", className: chartStyles.positive },
] as const;

type BucketKey = (typeof BUCKETS)[number]["key"];

const TIME_CHART_HEIGHT = 208;
const TIME_CHART_PADDING = { top: 8, right: 4, bottom: 26, left: 44 };
const GROUP_ROW_LIMIT = 8;

/**
 * One stacked-bar segment definition, worst-first (see `BUCKETS` above).
 * Shared shape so a second scope (AI review) can draw the same primitives
 * with its own keys/labels/colors instead of a copy of the drawing code.
 */
export interface BucketDef<K extends string> {
  readonly key: K;
  readonly label: string;
  readonly className: string | undefined;
}

export function share(count: number, total: number): number {
  return total === 0 ? 0 : count / total;
}

/** A rate only where the sample supports one, matching the table's own rule. */
export function guardedRate(count: number, total: number): string {
  return total >= PERCENTAGE_SAMPLE_MINIMUM ? formatRate(count / total) : "—";
}

export function SplitBar<K extends string>({
  buckets,
  counts,
  total,
  label,
}: {
  readonly buckets: readonly BucketDef<K>[];
  readonly counts: Record<K, number>;
  readonly total: number;
  readonly label: string;
}) {
  return (
    <div className={chartStyles.bar} role="img" aria-label={label}>
      {buckets.map((bucket) => {
        const value = counts[bucket.key];
        return value === 0 ? null : (
          <span
            key={bucket.key}
            className={`${chartStyles.barSegment} ${bucket.className}`}
            style={{ flexGrow: share(value, total) }}
          />
        );
      })}
    </div>
  );
}

export function Legend<K extends string>({
  buckets,
  counts,
  total,
}: {
  readonly buckets: readonly BucketDef<K>[];
  readonly counts: Record<K, number>;
  readonly total: number;
}) {
  return (
    <div className={chartStyles.legend}>
      {buckets.map((bucket) => (
        <p key={bucket.key} className={chartStyles.legendItem}>
          <span className={`${chartStyles.swatch} ${bucket.className}`} aria-hidden="true" />
          <span className={chartStyles.legendLabel}>{bucket.label}</span>
          <span className={chartStyles.legendValue}>
            {`${formatCount(counts[bucket.key])} · ${guardedRate(counts[bucket.key], total)}`}
          </span>
        </p>
      ))}
    </div>
  );
}

/**
 * Volume over the scope's own buckets, stacked by the worst-first dimension.
 *
 * Counts, not shares: on a thin day a share of three ratings would draw the
 * same width as a share of three hundred, and the reader would have no way to
 * tell them apart. Height carries the sample size, so a noisy bucket looks
 * noisy. One quantity, one y-axis.
 *
 * The stack's own total is always the sum of its buckets (CSAT's ticket_count,
 * AI review's rated_ticket_count) -- both are schema-enforced to reconcile,
 * so it is derived here rather than threaded in as a separate field.
 */
export function TimeChart<K extends string>({
  series,
  buckets,
  dayGrain,
  weekDefinition,
  regionLabel,
  svgLabel,
  tooltipFor,
}: {
  readonly series: readonly (readonly [string, Record<K, number>])[];
  readonly buckets: readonly BucketDef<K>[];
  readonly dayGrain: boolean;
  readonly weekDefinition: WeekDefinition;
  readonly regionLabel: string;
  readonly svgLabel: (maxTotal: number) => string;
  /** Renders the volume + worst-bucket half of the tooltip; the period prefix is added here. */
  readonly tooltipFor: (total: number, counts: Record<K, number>) => string;
}) {
  const totalOf = (counts: Record<K, number>) =>
    buckets.reduce((sum, bucket) => sum + counts[bucket.key], 0);
  const width = Math.max(560, series.length * 34 + TIME_CHART_PADDING.left);
  const innerWidth = width - TIME_CHART_PADDING.left - TIME_CHART_PADDING.right;
  const innerHeight = TIME_CHART_HEIGHT - TIME_CHART_PADDING.top - TIME_CHART_PADDING.bottom;
  const maxTotal = Math.max(...series.map(([, counts]) => totalOf(counts)), 1);
  const x = scaleBand<string>({
    domain: series.map(([key]) => key),
    range: [0, innerWidth],
    padding: 0.28,
  });
  const y = scaleLinear<number>({ domain: [0, maxTotal], range: [innerHeight, 0], nice: true });
  const ticks = y.ticks(3);
  const bucketLabel = (key: string) =>
    dayGrain ? formatWeekStart(key) : formatWeekRange(key, weekDefinition);
  // Enough labels to orient, never so many that they collide.
  const labelStep = Math.ceil(series.length / Math.max(1, Math.floor(innerWidth / 68)));

  return (
    <div className={chartStyles.chartViewport} role="region" aria-label={regionLabel}>
      <svg
        className={chartStyles.chartSvg}
        viewBox={`0 0 ${width} ${TIME_CHART_HEIGHT}`}
        role="img"
        aria-label={svgLabel(maxTotal)}
      >
        <g transform={`translate(${TIME_CHART_PADDING.left},${TIME_CHART_PADDING.top})`}>
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                className={chartStyles.gridLine}
                x1={0}
                x2={innerWidth}
                y1={y(tick)}
                y2={y(tick)}
              />
              <text className={chartStyles.axisLabel} x={-8} y={y(tick)} dy="0.32em" textAnchor="end">
                {formatCount(tick)}
              </text>
            </g>
          ))}
          {series.map(([key, counts], index) => {
            const left = x(key) ?? 0;
            const bandWidth = x.bandwidth();
            const total = totalOf(counts);
            let cursor = innerHeight;
            return (
              <g key={key}>
                <title>
                  {`${dayGrain ? "Ngày" : "Tuần"} ${bucketLabel(key)}: ${tooltipFor(total, counts)}`}
                </title>
                {buckets.map((bucket) => {
                  const value = counts[bucket.key];
                  if (value === 0) {
                    return null;
                  }
                  const height = (value / maxTotal) * innerHeight;
                  cursor -= height;
                  return (
                    <rect
                      key={bucket.key}
                      className={`${chartStyles.column} ${bucket.className}`}
                      x={left}
                      y={cursor}
                      width={bandWidth}
                      height={height}
                    />
                  );
                })}
                {index % labelStep === 0 ? (
                  <text
                    className={chartStyles.axisLabel}
                    x={left + bandWidth / 2}
                    y={innerHeight + 16}
                    textAnchor="middle"
                  >
                    {bucketLabel(key)}
                  </text>
                ) : null}
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

export interface CsatChartsProps {
  readonly data: CsatWeek;
  /** The scope's own buckets, in key order — the trend, already scoped. */
  readonly buckets: readonly (readonly [string, CsatWeek])[];
  readonly grouping: CsatGrouping;
  readonly dayGrain: boolean;
  readonly weekDefinition: WeekDefinition;
  /**
   * Langfuse tickets in the same scope CSAT is showing, or null when no
   * honest denominator exists (day grain, or a scope with no week match).
   * It is the only way to see participation: `ticket_count` counts tickets
   * that answered, so on its own it cannot say how many stayed silent.
   */
  readonly scopeTickets?: number | null;
}

export function CsatCharts({
  scopeTickets = null,
  data,
  buckets,
  grouping,
  dayGrain,
  weekDefinition,
}: CsatChartsProps) {
  const totals = useMemo(() => csatResponseTotals(data), [data]);
  const timeBuckets = useMemo(
    () =>
      [...buckets]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, bucket]) => [key, csatResponseTotals(bucket)] as const)
        .filter(([, counts]) => counts.ticket_count > 0),
    [buckets],
  );
  const groupRows = useMemo(() => {
    const rows = rowsFor(data, grouping).filter((row) => row.ticket_count > 0);
    // Sorted by what the reader is hunting for. Groups too small to carry a
    // rate sink below the ranked ones rather than topping it on one bad rating.
    return [...rows]
      .sort((left, right) => {
        const leftSmall = left.ticket_count < PERCENTAGE_SAMPLE_MINIMUM;
        const rightSmall = right.ticket_count < PERCENTAGE_SAMPLE_MINIMUM;
        if (leftSmall !== rightSmall) {
          return leftSmall ? 1 : -1;
        }
        return (
          share(right.negative, right.ticket_count) -
            share(left.negative, left.ticket_count) ||
          right.ticket_count - left.ticket_count
        );
      })
      .slice(0, GROUP_ROW_LIMIT);
  }, [data, grouping]);

  if (totals.ticket_count === 0) {
    return null;
  }

  return (
    <div className={chartStyles.charts}>
      <div className={chartStyles.headline}>
        <p className={chartStyles.headlineFigure}>
          <strong className={chartStyles.headlineValue}>
            {guardedRate(totals.negative, totals.ticket_count)}
          </strong>
          <span className={chartStyles.headlineLabel}>phản hồi chấm “Rất tệ”</span>
        </p>
        {/* The legend already states the negative count and share, so this line
            carries only what nothing else does: the denominator, and how much
            of the scope it covers. A share above 100% would mean the two
            sources disagree about the population, so it is dropped rather
            than printed. */}
        <p className={chartStyles.headlineSupport}>
          {`${formatCount(totals.ticket_count)} phản hồi từ ${formatCount(data.ticket_count)} ticket`}
          {scopeTickets == null ||
          scopeTickets === 0 ||
          data.ticket_count > scopeTickets
            ? null
            : ` · ${formatRate(data.ticket_count / scopeTickets)} ticket trong phạm vi có đánh giá`}
        </p>
        <SplitBar
          buckets={BUCKETS}
          counts={totals}
          total={totals.ticket_count}
          label={BUCKETS.map(
            (bucket) =>
              `${bucket.label} ${formatCount(totals[bucket.key as BucketKey])}`,
          ).join(", ")}
        />
        <Legend buckets={BUCKETS} counts={totals} total={totals.ticket_count} />
      </div>

      {timeBuckets.length > 1 ? (
        <div className={chartStyles.panel}>
          <h3 className={chartStyles.panelTitle}>
            {dayGrain ? "Từng ngày mở ticket" : "Từng tuần mở ticket"}
          </h3>
          <p className={chartStyles.panelNote}>
            Cột cao là ngày nhiều người chấm. Dải đỏ nằm dưới đáy để so được giữa các cột.
          </p>
          <TimeChart
            series={timeBuckets}
            buckets={BUCKETS}
            dayGrain={dayGrain}
            weekDefinition={weekDefinition}
            regionLabel="Phản hồi theo thời gian"
            svgLabel={(maxTotal) =>
              `Số phản hồi theo ${dayGrain ? "ngày" : "tuần"}, xếp chồng theo mức hài lòng, cao nhất ${formatCount(maxTotal)} phản hồi.`
            }
            tooltipFor={(total, counts) =>
              `${formatCount(total)} phản hồi · Rất tệ ${formatCount(counts.negative)}`
            }
          />
        </div>
      ) : null}

      {groupRows.length > 0 ? (
        <div className={chartStyles.panel}>
          <h3 className={chartStyles.panelTitle}>
            {`${csatGroupingLabel(grouping)} nào bị chấm “Rất tệ” nhiều nhất`}
          </h3>
          <p className={chartStyles.panelNote}>
            Mỗi thanh là toàn bộ phản hồi của nhóm, xếp từ tệ nhất bên trái. Bảng bên
            dưới có số chính xác và nút lọc.
          </p>
          <div className={chartStyles.groupList}>
            {groupRows.map((row) => (
              <div key={`${grouping}:${row.value}`} className={chartStyles.groupRow}>
                <span className={chartStyles.groupLabel}>{row.label}</span>
                <SplitBar
                  buckets={BUCKETS}
                  counts={row}
                  total={row.ticket_count}
                  label={`${row.label}: ${BUCKETS.map(
                    (bucket) => `${bucket.label} ${formatCount(row[bucket.key as BucketKey])}`,
                  ).join(", ")}`}
                />
                <span className={chartStyles.groupValue}>
                  {row.ticket_count < PERCENTAGE_SAMPLE_MINIMUM
                    ? `${formatCount(row.ticket_count)} phản hồi · mẫu nhỏ`
                    : `${formatRate(row.negative / row.ticket_count)} · ${formatCount(row.ticket_count)} phản hồi`}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
