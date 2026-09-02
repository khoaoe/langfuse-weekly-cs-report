import { useEffect, useMemo, useState } from "react";
import { scaleBand, scaleLinear } from "@visx/scale";
import { Bar, LinePath } from "@visx/shape";

import type {
  DashboardSnapshot,
  DayAggregate,
  Segments,
  SamePeriod,
  WeekDefinition,
  WeeklyReportRow,
} from "../lib/dashboard-schema";
import type { TicketFilterKey, TicketFilters } from "../lib/dashboard-filters";
import { niceRateTicks, niceVolumeTicks } from "../lib/chart-scale";
import {
  aggregateTransferReasonsFromDays,
  buildDayRangeWeekLabels,
  rollingRate,
} from "../lib/report-scope";
import {
  PERCENTAGE_SAMPLE_MINIMUM,
  formatCount,
  formatDateRangeLabel,
  formatRate,
  formatRateAxis,
  formatWeekRange,
  formatWeekStart,
  formatWeekdayCode,
  formatWeekdayName,
  shareWithSampleGuard,
} from "../lib/format";
import {
  MIN_TREND_WEEKS,
  selectLatestWeek,
  selectView,
  selectWeekly,
} from "../lib/selectors";
import {
  stableSortRows,
  toggleTableSort,
  type SortDirection,
  type SortValue,
  type TableSort,
} from "../lib/table-sort";
import { DataTableSortButton } from "./DataTableSortButton";
import { FilterValueButton } from "./FilterValueButton";
import { CsatSection } from "./CsatSection";
import type { CsatGrouping } from "./CsatBreakdownTable";
import { DataTrustSection } from "./DataTrustSection";
import { EntryCoverageSection } from "./EntryCoverageSection";
import { TransferDiagnostics } from "./TransferDiagnostics";
import belowFoldStyles from "./below-fold.module.css";
import styles from "./dashboard.module.css";
import trendStyles from "./trend.module.css";

/** §B1: rolling window width for day-mode rate lines. */
const ROLLING_WINDOW_DAYS = 7;

const CHART_WIDTH = 720;
const CHART_HEIGHT = 220;
const MARGIN = { top: 12, right: 16, bottom: 28, left: 56 } as const;
const INNER_WIDTH = CHART_WIDTH - MARGIN.left - MARGIN.right;
const INNER_HEIGHT = CHART_HEIGHT - MARGIN.top - MARGIN.bottom;

const SEGMENT_DIMENSIONS = [
  { key: "issue_category", label: "Category" },
  { key: "app", label: "App" },
  { key: "product_code", label: "Product Code" },
  { key: "skill", label: "Skill" },
  { key: "intent", label: "Intent" },
] as const satisfies readonly {
  key: Extract<TicketFilterKey, keyof Segments>;
  label: string;
}[];

type SegmentDimension = (typeof SEGMENT_DIMENSIONS)[number]["key"];
type SegmentCounts = Segments["issue_category"][string];
type SegmentSortKey =
  | "label"
  | "total"
  | "ai_first"
  | "transferred"
  | "reopen";

interface SegmentRow {
  readonly label: string;
  readonly counts: SegmentCounts;
}

type TrendWeek = Pick<
  WeeklyReportRow,
  | "cohort_week"
  | "cohort_status"
  | "has_data"
  | "total_tickets"
  | "ai_first_count"
  | "ai_first_rate"
  | "reopen_lifetime_rate"
>;

/**
 * Chart-internal shape shared by week mode and day mode. `key` is the
 * click/identity value (a cohort_week or a calendar day, both ISO dates);
 * `axisLabel`/`rangeLabel` are pre-formatted by the caller so this component
 * never needs to know whether it is looking at a week or a day.
 */
interface TrendPoint {
  readonly key: string;
  readonly wtd: boolean;
  readonly has_data: boolean;
  readonly total_tickets: number;
  readonly ai_first_count: number;
  readonly ai_first_rate: number;
  readonly reopen_lifetime_rate: number | null;
  readonly axisLabel: string;
  readonly rangeLabel: string;
}

function trendWeekToPoint(week: TrendWeek, weekDefinition: WeekDefinition): TrendPoint {
  return {
    key: week.cohort_week,
    wtd: week.cohort_status === "wtd",
    has_data: week.has_data,
    total_tickets: week.total_tickets,
    ai_first_count: week.ai_first_count,
    ai_first_rate: week.ai_first_rate,
    reopen_lifetime_rate: week.reopen_lifetime_rate,
    axisLabel: formatWeekStart(week.cohort_week),
    rangeLabel: formatWeekRange(week.cohort_week, weekDefinition),
  };
}

/**
 * §B1: rate lines use a 7-day rolling average, computed over `allDays`
 * (plotted range plus 6 lookback days so the window is full from the first
 * plotted point), then trimmed to `plottedDays` for rendering. The lookback
 * days themselves are never plotted.
 */
function dayRangeToTrendPoints(
  allDays: readonly DayAggregate[],
  plottedDays: readonly DayAggregate[],
): TrendPoint[] {
  const aiFirstRates = rollingRate(
    allDays,
    ROLLING_WINDOW_DAYS,
    (day) => day.ai_first_count,
    (day) => day.total_tickets,
  );
  const reopenRates = rollingRate(
    allDays,
    ROLLING_WINDOW_DAYS,
    (day) => day.reopen_lifetime_numerator,
    (day) => day.reopen_lifetime_denominator,
  );
  const plottedKeys = new Set(plottedDays.map((day) => day.day));
  return allDays.flatMap((current, index) => {
    if (!plottedKeys.has(current.day)) {
      return [];
    }
    return [
      {
        key: current.day,
        wtd: false,
        has_data: current.total_tickets > 0,
        total_tickets: current.total_tickets,
        ai_first_count: current.ai_first_count,
        ai_first_rate: aiFirstRates[index] ?? 0,
        reopen_lifetime_rate: reopenRates[index] ?? null,
        axisLabel: formatWeekStart(current.day),
        rangeLabel: formatWeekStart(current.day),
      },
    ];
  });
}

interface TrendCopy {
  readonly volumeChartTitle: string;
  readonly rateChartTitle: string;
  readonly volumeAriaLabel: string;
  readonly rateAriaLabel: string;
  readonly rateAriaTitle: string;
  readonly rateAriaDesc: (rateCeiling: string) => string;
  readonly tooltipRangePrefix: string;
  readonly volumeCaption: (rangeLabel: string, total: string, aiFirst: string) => string;
  readonly rateCaption: (aiFirstRate: string, reopenRate: string) => string;
  readonly emptyMessage: (minPoints: number, observedCount: string) => string;
  readonly wtdSuffix: string;
  /**
   * §B2: a mandatory two-line label above the charts, not decorative — without
   * the second line a reader mistakes a single day's plotted rate for that
   * day's own rate rather than a 7-day rolling average. `null` in week mode,
   * which has no such ambiguity (a week's rate is already a whole-week rate).
   */
  readonly subtitle: ((rangeLabel: string) => readonly [string, string]) | null;
}

const WEEK_TREND_COPY: TrendCopy = {
  volumeChartTitle: "Volume ticket theo tuần",
  rateChartTitle: "Tỷ lệ theo tuần",
  volumeAriaLabel: "Biểu đồ volume, cuộn ngang khi cần",
  rateAriaLabel: "Biểu đồ tỷ lệ, cuộn ngang khi cần",
  rateAriaTitle: "Tỷ lệ AI First và reopen theo tuần",
  rateAriaDesc: (rateCeiling) =>
    [
      `Hai đường dùng chung trục phần trăm, chạy từ 0 đến ${rateCeiling} để vừa cả tuần cao điểm nhất.`,
      "Đường liền là AI First, đường nét đứt là reopen sau AI First — reopen có thể vượt 100% vì một ticket có thể reopen nhiều lần.",
      "Volume nằm ở biểu đồ phía trên để tránh hai trục trong một khung.",
    ].join(" "),
  tooltipRangePrefix: "Tuần",
  volumeCaption: (rangeLabel, total, aiFirst) =>
    `Tuần gần nhất có dữ liệu ${rangeLabel}: ${total} ticket, trong đó ${aiFirst} ticket AI First.`,
  rateCaption: (aiFirstRate, reopenRate) =>
    `Tuần gần nhất có dữ liệu: AI First ${aiFirstRate}, reopen ${reopenRate}.`,
  emptyMessage: (minPoints, observedCount) =>
    `Cần ít nhất ${minPoints} tuần có dữ liệu mới vẽ được xu hướng. Hiện có ${observedCount} tuần.`,
  wtdSuffix: " · WTD",
  subtitle: null,
};

const DAY_TREND_COPY: TrendCopy = {
  volumeChartTitle: "Volume ticket theo ngày",
  rateChartTitle: "Tỷ lệ theo ngày (trung bình động 7 ngày)",
  volumeAriaLabel: "Biểu đồ volume theo ngày, cuộn ngang khi cần",
  rateAriaLabel: "Biểu đồ tỷ lệ theo ngày, cuộn ngang khi cần",
  rateAriaTitle: "Tỷ lệ AI First và reopen theo ngày, trung bình động 7 ngày",
  rateAriaDesc: (rateCeiling) =>
    [
      `Hai đường dùng chung trục phần trăm, chạy từ 0 đến ${rateCeiling} để vừa cả ngày cao điểm nhất.`,
      "Mỗi điểm là trung bình động 7 ngày kết thúc ở ngày đó, không phải tỷ lệ riêng của ngày đó.",
      "Đường liền là AI First, đường nét đứt là reopen sau AI First — reopen có thể vượt 100% vì một ticket có thể reopen nhiều lần.",
      "Volume nằm ở biểu đồ phía trên để tránh hai trục trong một khung.",
    ].join(" "),
  tooltipRangePrefix: "Ngày",
  volumeCaption: (rangeLabel, total, aiFirst) =>
    `Ngày gần nhất có dữ liệu ${rangeLabel}: ${total} ticket, trong đó ${aiFirst} ticket AI First.`,
  rateCaption: (aiFirstRate, reopenRate) =>
    `Ngày gần nhất có dữ liệu: AI First ${aiFirstRate} (TB động 7 ngày), reopen ${reopenRate} (TB động 7 ngày).`,
  emptyMessage: (minPoints, observedCount) =>
    `Cần ít nhất ${minPoints} ngày có dữ liệu mới vẽ được xu hướng. Hiện có ${observedCount} ngày.`,
  wtdSuffix: "",
  subtitle: (rangeLabel) => [
    `Xu hướng theo ngày · ${rangeLabel}`,
    "Tỷ lệ là trung bình động 7 ngày",
  ],
};

type TrendTooltipKind = "volume" | "rate";

interface TrendTooltipState {
  readonly point: TrendPoint;
  readonly chart: TrendTooltipKind;
  readonly anchorX: number;
}

interface SegmentSortColumn {
  readonly key: SegmentSortKey;
  readonly label: string;
  readonly initialDirection: SortDirection;
  readonly value: (row: SegmentRow) => SortValue;
}

const SEGMENT_SORT_COLUMNS: readonly SegmentSortColumn[] = [
  {
    key: "label",
    label: "Giá trị",
    initialDirection: "asc",
    value: (row) => row.label,
  },
  {
    key: "total",
    label: "Ticket",
    initialDirection: "desc",
    value: (row) => row.counts.total,
  },
  {
    key: "ai_first",
    label: "AI First",
    initialDirection: "desc",
    value: (row) => row.counts.ai_first,
  },
  {
    key: "transferred",
    label: "Chuyển CS",
    initialDirection: "desc",
    value: (row) => row.counts.transferred,
  },
  {
    key: "reopen",
    label: "Reopen",
    initialDirection: "desc",
    value: (row) => row.counts.reopen,
  },
];

/**
 * Default ranking is absolute CS handoffs caused, not ticket volume.
 *
 * The PO reads this table to pick next week's work (SPEC-v2 §5.1). Volume
 * order puts the biggest bucket first even when it is the one AI handles
 * cleanly, and a rate order puts a 2-ticket bucket at 100% above a 349-ticket
 * bucket. `transferred` is volume times transfer rate, so the top row is the
 * segment actually generating the most CS work.
 */
const DEFAULT_SEGMENT_SORT: TableSort<SegmentSortKey> = {
  key: "transferred",
  direction: "desc",
};

/** SPEC-v2 §5.10: a ranked list shows its head, not its whole tail. */
const SEGMENT_HEAD_ROWS = 12;

function tooltipAnchor(clientX: number, bounds: DOMRect): number {
  if (bounds.width <= 0) {
    return 50;
  }
  return Math.min(
    88,
    Math.max(12, ((clientX - bounds.left) / bounds.width) * 100),
  );
}

function TrendTooltip({
  state,
  copy,
}: {
  readonly state: TrendTooltipState;
  readonly copy: TrendCopy;
}) {
  const showVolume = state.chart !== "rate";
  const showRate = state.chart !== "volume";
  const horizontalTransform =
    state.anchorX <= 25
      ? "translateX(0)"
      : state.anchorX >= 75
        ? "translateX(-100%)"
        : "translateX(-50%)";
  return (
    <div
      id="trendTooltip"
      role="tooltip"
      className={trendStyles.chartTooltip}
      style={{ left: `${state.anchorX}%`, transform: horizontalTransform }}
    >
      <strong>{`${copy.tooltipRangePrefix} ${state.point.rangeLabel}`}</strong>
      {showVolume ? (
        <>
          <span>{`Tổng ${formatCount(state.point.total_tickets)} ticket`}</span>
          <span>{`AI First ${formatCount(state.point.ai_first_count)} ticket`}</span>
        </>
      ) : null}
      {showRate ? (
        <>
          <span>{`AI First ${formatRate(state.point.ai_first_rate)}`}</span>
          <span>{`Reopen sau AI First ${formatRate(
            state.point.reopen_lifetime_rate,
          )}`}</span>
        </>
      ) : null}
    </div>
  );
}

/**
 * Volume and rate live in two aligned panels rather than one dual-axis chart:
 * a count and a percentage share no scale, so overlaying them would invent a
 * relationship the data does not contain.
 */
function TrendPanels({
  points,
  copy,
  subtitle,
  activeKey,
  onPointSelect,
}: {
  readonly points: readonly TrendPoint[];
  readonly copy: TrendCopy;
  readonly subtitle: readonly [string, string] | null;
  readonly activeKey: string;
  readonly onPointSelect: (key: string) => void;
}) {
  const [tooltip, setTooltip] = useState<TrendTooltipState | null>(null);
  const observed = points.filter((point) => point.has_data);
  if (observed.length < MIN_TREND_WEEKS) {
    return (
      <p id="trendEmpty" className={belowFoldStyles.empty}>
        {copy.emptyMessage(MIN_TREND_WEEKS, formatCount(observed.length))}
      </p>
    );
  }

  const chartPoints = [...points];
  const pointScale = scaleBand<string>({
    domain: chartPoints.map((point) => point.key),
    range: [0, INNER_WIDTH],
  });
  const step = pointScale.bandwidth();
  const barWidth = Math.max(2, step * 0.34);
  const maxVolume = Math.max(0, ...observed.map((point) => point.total_tickets));
  const volumeTicks = niceVolumeTicks(maxVolume);
  const volumeCeiling = volumeTicks.at(-1) ?? 1;
  const volumeY = scaleLinear<number>({
    domain: [0, volumeCeiling],
    range: [INNER_HEIGHT, 0],
  });
  const maxRate = Math.max(
    1,
    ...observed.map((point) =>
      Math.max(point.ai_first_rate, point.reopen_lifetime_rate ?? 0),
    ),
  );
  const rateTicks = niceRateTicks(maxRate);
  const rateCeiling = rateTicks.at(-1) ?? 1;
  const rateY = scaleLinear<number>({
    domain: [0, rateCeiling],
    range: [INNER_HEIGHT, 0],
    clamp: true,
  });
  const x = (point: TrendPoint) => pointScale(point.key) ?? 0;
  const centre = (point: TrendPoint) => x(point) + step / 2;
  const labelledIndexes = new Set([
    0,
    points.length - 1,
    ...points.flatMap((point, index) =>
      index % 3 === 0 || point.wtd ? [index] : [],
    ),
  ]);
  const renderXAxis = () =>
    points.map((point, index) =>
      labelledIndexes.has(index) ? (
        <g key={`axis-${point.key}`}>
          {point.wtd ? (
            <line
              className={trendStyles.wtdMarker}
              x1={centre(point)}
              x2={centre(point)}
              y1={0}
              y2={INNER_HEIGHT}
            />
          ) : null}
          <text
            className={`${trendStyles.axisLabel} ${
              point.wtd ? trendStyles.wtdAxisLabel : ""
            }`}
            x={centre(point)}
            y={INNER_HEIGHT + 18}
            textAnchor="middle"
          >
            {`${point.axisLabel}${point.wtd ? copy.wtdSuffix : ""}`}
          </text>
        </g>
      ) : null,
    );

  const renderPointTargets = (chart: "volume" | "rate") =>
    points.map((point) =>
      point.has_data ? (
        <g
          key={`target-${point.key}`}
          className={trendStyles.weekTarget}
          data-week-target={point.key}
          aria-hidden="true"
          onPointerEnter={(event) => {
            const bounds =
              event.currentTarget.ownerSVGElement?.getBoundingClientRect();
            setTooltip({
              point,
              chart,
              anchorX:
                bounds === undefined
                  ? 50
                  : tooltipAnchor(event.clientX, bounds),
            });
          }}
          onPointerMove={(event) => {
            const bounds =
              event.currentTarget.ownerSVGElement?.getBoundingClientRect();
            if (bounds !== undefined) {
              setTooltip({
                point,
                chart,
                anchorX: tooltipAnchor(event.clientX, bounds),
              });
            }
          }}
          onPointerLeave={() => setTooltip(null)}
          onClick={() => onPointSelect(point.key)}
        >
          <rect
            className={`${trendStyles.weekHit} ${
              activeKey === point.key ? trendStyles.weekHitActive : ""
            }`}
            x={x(point)}
            y={0}
            width={step}
            height={INNER_HEIGHT + MARGIN.bottom}
          />
        </g>
      ) : null,
    );

  const latest = observed.at(-1);

  return (
    <div className={trendStyles.trendPanels}>
      {subtitle === null ? null : (
        <p className={styles.sectionNote}>
          <span>{subtitle[0]}</span>
          <br />
          <span>{subtitle[1]}</span>
        </p>
      )}
      <div className={trendStyles.charts}>
        <figure className={trendStyles.chart}>
        <figcaption className={trendStyles.chartTitle}>{copy.volumeChartTitle}</figcaption>
        <div
          className={trendStyles.chartViewport}
          role="region"
          aria-label={copy.volumeAriaLabel}
          tabIndex={0}
        >
          <svg
            id="trendChart"
            className={trendStyles.chartSvg}
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            role="img"
            aria-labelledby="trend-volume-title"
            aria-describedby="trend-volume-desc"
          >
          <title id="trend-volume-title">{copy.volumeChartTitle}</title>
          <desc id="trend-volume-desc">
            Cột thứ nhất là tổng ticket, cột thứ hai là ticket AI First. Cả hai
            dùng chung một trục số lượng. Tuần không có dữ liệu để trống.
          </desc>
          <g transform={`translate(${MARGIN.left} ${MARGIN.top})`}>
            {volumeTicks.map((tick) => (
              <g key={tick}>
                <line
                  className={trendStyles.gridLine}
                  x1={0}
                  x2={INNER_WIDTH}
                  y1={volumeY(tick)}
                  y2={volumeY(tick)}
                />
                <text
                  className={trendStyles.axisLabel}
                  x={-8}
                  y={volumeY(tick) + 4}
                  textAnchor="end"
                >
                  {formatCount(Math.round(tick))}
                </text>
              </g>
            ))}
            {renderXAxis()}
            {points.map((point) =>
              point.has_data ? (
                <g key={point.key}>
                  <Bar
                    className={trendStyles.seriesPrimaryFill ?? ""}
                    x={centre(point) - barWidth}
                    y={volumeY(point.total_tickets)}
                    width={barWidth}
                    height={INNER_HEIGHT - volumeY(point.total_tickets)}
                  />
                  <Bar
                    className={trendStyles.seriesSecondaryFill ?? ""}
                    x={centre(point)}
                    y={volumeY(point.ai_first_count)}
                    width={barWidth}
                    height={INNER_HEIGHT - volumeY(point.ai_first_count)}
                  />
                </g>
              ) : null,
            )}
            {renderPointTargets("volume")}
          </g>
          </svg>
        </div>
        {tooltip?.chart === "volume" ? (
          <TrendTooltip state={tooltip} copy={copy} />
        ) : null}
        <div className={trendStyles.legend}>
          <span className={trendStyles.legendItem}>
            <span className={trendStyles.swatchPrimary} /> Tổng ticket
          </span>
          <span className={trendStyles.legendItem}>
            <span className={trendStyles.swatchSecondary} /> Ticket AI First
          </span>
        </div>
        <p id="trendCaption" className={styles.caption}>
          {latest === undefined
            ? "—"
            : copy.volumeCaption(
                latest.rangeLabel,
                formatCount(latest.total_tickets),
                formatCount(latest.ai_first_count),
              )}
        </p>
        </figure>

        <figure className={trendStyles.chart}>
        <figcaption className={trendStyles.chartTitle}>{copy.rateChartTitle}</figcaption>
        <div
          className={trendStyles.chartViewport}
          role="region"
          aria-label={copy.rateAriaLabel}
          tabIndex={0}
        >
          <svg
            className={trendStyles.chartSvg}
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            role="img"
            aria-labelledby="trend-rate-title"
            aria-describedby="trend-rate-desc"
          >
          <title id="trend-rate-title">{copy.rateAriaTitle}</title>
          <desc id="trend-rate-desc">
            {copy.rateAriaDesc(formatRateAxis(rateCeiling))}
          </desc>
          <g transform={`translate(${MARGIN.left} ${MARGIN.top})`}>
            {rateTicks.map((tick) => (
              <g key={tick}>
                <line
                  className={trendStyles.gridLine}
                  x1={0}
                  x2={INNER_WIDTH}
                  y1={rateY(tick)}
                  y2={rateY(tick)}
                />
                <text
                  className={trendStyles.axisLabel}
                  x={-8}
                  y={rateY(tick) + 4}
                  textAnchor="end"
                >
                  {formatRateAxis(tick)}
                </text>
              </g>
            ))}
            {renderXAxis()}
            <LinePath<TrendPoint>
              className={trendStyles.seriesPrimaryStroke ?? ""}
              data={chartPoints}
              defined={(point) => point.has_data}
              x={centre}
              y={(point) => rateY(point.ai_first_rate)}
            />
            <LinePath<TrendPoint>
              className={trendStyles.seriesSecondaryStroke ?? ""}
              data={chartPoints}
              defined={(point) =>
                point.has_data && point.reopen_lifetime_rate !== null
              }
              x={centre}
              y={(point) => rateY(point.reopen_lifetime_rate ?? 0)}
            />
            {renderPointTargets("rate")}
          </g>
          </svg>
        </div>
        {tooltip?.chart === "rate" ? (
          <TrendTooltip state={tooltip} copy={copy} />
        ) : null}
        <div className={trendStyles.legend}>
          <span className={trendStyles.legendItem}>
            <span className={trendStyles.swatchPrimary} /> Tỷ lệ AI First
          </span>
          <span className={trendStyles.legendItem}>
            <span className={trendStyles.swatchSecondary} /> Tỷ lệ reopen sau AI First
          </span>
        </div>
        <p className={styles.caption}>
          {latest === undefined
            ? "—"
            : copy.rateCaption(
                formatRate(latest.ai_first_rate),
                formatRate(latest.reopen_lifetime_rate),
              )}
        </p>
        </figure>
      </div>
    </div>
  );
}

function samePeriodTrendWeeks(
  weeks: readonly WeeklyReportRow[],
  samePeriod: SamePeriod,
): TrendWeek[] {
  return weeks.flatMap((week) => {
    const truncated = samePeriod.by_week[week.cohort_week];
    if (truncated === undefined) {
      return [];
    }
    return [
      {
        cohort_week: truncated.cohort_week,
        cohort_status: week.cohort_status,
        has_data: truncated.total_tickets > 0,
        total_tickets: truncated.total_tickets,
        ai_first_count: truncated.ai_first_count,
        ai_first_rate: truncated.ai_first_rate,
        reopen_lifetime_rate: truncated.reopen_lifetime_rate,
      },
    ];
  });
}

function SegmentTable({
  segments,
  onSelect,
}: {
  readonly segments: Segments;
  readonly onSelect: (key: SegmentDimension, value: string) => void;
}) {
  const [dimension, setDimension] =
    useState<SegmentDimension>("issue_category");
  const [sort, setSort] =
    useState<TableSort<SegmentSortKey>>(DEFAULT_SEGMENT_SORT);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    setExpanded(false);
  }, [dimension]);
  const buckets = segments[dimension];
  const total = useMemo(
    () => Object.values(buckets).reduce((sum, counts) => sum + counts.total, 0),
    [buckets],
  );
  const formatMetric = shareWithSampleGuard;
  const rows = useMemo(() => {
    const source = Object.entries(buckets)
      .filter(([, counts]) => counts.total > 0)
      .map(([label, counts]) => ({
        label,
        counts,
      }));
    const deterministic = stableSortRows(source, (row) => row.label, "asc");
    const column =
      SEGMENT_SORT_COLUMNS.find((item) => item.key === sort.key) ??
      SEGMENT_SORT_COLUMNS[0];
    return stableSortRows(
      deterministic,
      (row) => column?.value(row),
      sort.direction,
    );
  }, [buckets, sort]);
  const hiddenRows = expanded ? [] : rows.slice(SEGMENT_HEAD_ROWS);
  const visibleRows = expanded ? rows : rows.slice(0, SEGMENT_HEAD_ROWS);
  // The tail is summed rather than dropped: every ticket stays in the table,
  // so the column totals a reader adds up still reconcile with the ledger.
  const restCounts = hiddenRows.reduce(
    (sum, row) => ({
      total: sum.total + row.counts.total,
      ai_first: sum.ai_first + row.counts.ai_first,
      transferred: sum.transferred + row.counts.transferred,
      reopen: sum.reopen + row.counts.reopen,
    }),
    { total: 0, ai_first: 0, transferred: 0, reopen: 0 },
  );
  const activeTabId = `segment-tab-${dimension}`;

  return (
    <>
      <div
        id="segmentTabs"
        className={belowFoldStyles.tabs}
        role="tablist"
        aria-label="Chiều so sánh"
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
            return;
          }
          event.preventDefault();
          const current = SEGMENT_DIMENSIONS.findIndex(
            (item) => item.key === dimension,
          );
          const next =
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? SEGMENT_DIMENSIONS.length - 1
                : (current +
                    (event.key === "ArrowRight" ? 1 : -1) +
                    SEGMENT_DIMENSIONS.length) %
                  SEGMENT_DIMENSIONS.length;
          const item = SEGMENT_DIMENSIONS[next];
          if (item !== undefined) {
            setDimension(item.key);
            document.getElementById(`segment-tab-${item.key}`)?.focus();
          }
        }}
      >
        {SEGMENT_DIMENSIONS.map((item) => (
          <button
            key={item.key}
            id={`segment-tab-${item.key}`}
            type="button"
            role="tab"
            className={belowFoldStyles.tab}
            aria-selected={dimension === item.key}
            aria-controls="segmentList"
            tabIndex={dimension === item.key ? 0 : -1}
            onClick={() => setDimension(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <p
        id="segmentCaption"
        className={styles.tableCaption}
        aria-live="polite"
      >
        {`Xếp theo số ca chuyển CS nhiều nhất. Ticket: tỷ trọng trong tuần. AI First, Chuyển CS, Reopen: tỷ lệ trong chính nhóm đó. Nhóm dưới ${PERCENTAGE_SAMPLE_MINIMUM} ticket chỉ hiện số ca, không hiện tỷ lệ.`}
      </p>

      <div
        id="segmentList"
        className={styles.tableScroll}
        tabIndex={0}
      role="tabpanel"
      aria-labelledby={activeTabId}
    >
        {rows.length === 0 ? (
          <p className={styles.emptyCell}>
            Không có ticket trong phạm vi đang chọn.
          </p>
        ) : (
          <table className={styles.table} aria-labelledby="segmentCaption">
          <thead>
            <tr>
              {SEGMENT_SORT_COLUMNS.map((column, index) => {
                const active = sort.key === column.key;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    className={
                      index === 0 ? styles.stickyColumn : styles.numeric
                    }
                    aria-sort={
                      active
                        ? sort.direction === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <DataTableSortButton
                      label={column.label}
                      active={active}
                      direction={sort.direction}
                      align={index === 0 ? "start" : "end"}
                      onClick={() =>
                        setSort((current) =>
                          toggleTableSort(
                            current,
                            column.key,
                            column.initialDirection,
                          ),
                        )
                      }
                    />
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map(({ label, counts }) => (
              <tr key={label}>
                <th scope="row" className={styles.stickyColumn}>
                  <FilterValueButton
                    label={label}
                    filterLabel={
                      SEGMENT_DIMENSIONS.find((item) => item.key === dimension)
                        ?.label ?? dimension
                    }
                    onClick={() => onSelect(dimension, label)}
                  />
                </th>
                <td className={styles.numeric}>
                  {formatMetric(counts.total, total)}
                </td>
                <td className={styles.numeric}>
                  {formatMetric(counts.ai_first, counts.total)}
                </td>
                <td className={styles.numeric}>
                  {formatMetric(counts.transferred, counts.total)}
                </td>
                <td className={styles.numeric}>
                  {formatMetric(counts.reopen, counts.total)}
                </td>
              </tr>
            ))}
            {hiddenRows.length === 0 ? null : (
              <tr>
                <th scope="row" className={styles.stickyColumn}>
                  <button
                    type="button"
                    className={belowFoldStyles.inlineAction}
                    onClick={() => setExpanded(true)}
                  >
                    {`${hiddenRows.length} nhóm còn lại — xem hết`}
                  </button>
                </th>
                <td className={styles.numeric}>
                  {formatMetric(restCounts.total, total)}
                </td>
                <td className={styles.numeric}>
                  {formatMetric(restCounts.ai_first, restCounts.total)}
                </td>
                <td className={styles.numeric}>
                  {formatMetric(restCounts.transferred, restCounts.total)}
                </td>
                <td className={styles.numeric}>
                  {formatMetric(restCounts.reopen, restCounts.total)}
                </td>
              </tr>
            )}
            {expanded && rows.length > SEGMENT_HEAD_ROWS ? (
              <tr>
                <th scope="row" className={styles.stickyColumn}>
                  <button
                    type="button"
                    className={belowFoldStyles.inlineAction}
                    onClick={() => setExpanded(false)}
                  >
                    {`Thu gọn về ${SEGMENT_HEAD_ROWS} nhóm đầu`}
                  </button>
                </th>
                <td className={styles.numeric} colSpan={4} />
              </tr>
            ) : null}
          </tbody>
          </table>
        )}
      </div>
    </>
  );
}

export interface BelowFoldProps {
  readonly snapshot: DashboardSnapshot;
  readonly weekDefinition: WeekDefinition;
  readonly activeWeek: string;
  readonly allWeeks?: boolean;
  readonly onWeekSelect: (cohortWeek: string) => void;
  readonly onSegmentSelect: (
    key: SegmentDimension,
    value: string,
  ) => void;
  readonly onShowStuckTickets?: (cohortWeek: string) => void;
  readonly onTicketFilterSelect?: (patch: Partial<TicketFilters>) => void;
  readonly activeCsatBreakdownFilters: Pick<
    TicketFilters,
    "outcome" | "skill" | "issue_category"
  >;
  readonly onCsatBreakdownSelect: (
    grouping: CsatGrouping,
    value: string,
  ) => void;
  readonly onCsatBreakdownGroupingChange: () => void;
  readonly freshdeskCookieState?: "ok" | "expired" | "missing" | null;
  readonly onOpenFreshdeskCookieDialog?: () => void;
  /**
   * When present, the trend chart plots a true day-grain range instead of
   * weeks — §5 Phần B of the day-grain spec. Segments/ledger read `snapshot`
   * (the day-range synthetic view in this mode); transfer diagnostics reads
   * `weeklySnapshot` instead (§6 — TPE/transfer-reason grain doesn't exist
   * per day, so that whole panel stays week-based with a note).
   */
  readonly dayRange?: {
    readonly from: string;
    readonly to: string;
    readonly allDays: readonly DayAggregate[];
    readonly plottedDays: readonly DayAggregate[];
    readonly activeDay: string;
    readonly onDaySelect: (day: string) => void;
  };
  readonly weeklySnapshot?: DashboardSnapshot;
}

/**
 * Trends, segment comparison, CSAT and transfer/rule diagnostics —
 * everything that explains the ledger above.
 */
export function BelowFold({
  snapshot,
  weekDefinition,
  activeWeek,
  allWeeks = false,
  onWeekSelect,
  onSegmentSelect,
  onShowStuckTickets = () => {},
  onTicketFilterSelect = () => {},
  activeCsatBreakdownFilters,
  onCsatBreakdownSelect,
  onCsatBreakdownGroupingChange,
  freshdeskCookieState = null,
  onOpenFreshdeskCookieDialog = () => {},
  dayRange,
  weeklySnapshot,
}: BelowFoldProps) {
  const view = selectView(snapshot, weekDefinition);
  const weeks = selectWeekly(view);
  const [trendMode, setTrendMode] = useState<"full" | "same_period">("full");
  const hasSamePeriod = view.same_period !== null;
  useEffect(() => {
    setTrendMode("full");
  }, [weekDefinition, hasSamePeriod]);
  const effectiveTrendMode =
    hasSamePeriod && trendMode === "same_period" ? "same_period" : "full";
  const trendWeeks = useMemo(
    () =>
      effectiveTrendMode === "same_period" && view.same_period !== null
        ? samePeriodTrendWeeks(weeks, view.same_period)
        : weeks,
    [effectiveTrendMode, view.same_period, weeks],
  );
  const weekTrendPoints = useMemo(
    () => trendWeeks.map((week) => trendWeekToPoint(week, weekDefinition)),
    [trendWeeks, weekDefinition],
  );
  const dayTrendPoints = useMemo(
    () =>
      dayRange === undefined
        ? []
        : dayRangeToTrendPoints(dayRange.allDays, dayRange.plottedDays),
    [dayRange],
  );
  const trendPoints = dayRange === undefined ? weekTrendPoints : dayTrendPoints;
  const trendCopy = dayRange === undefined ? WEEK_TREND_COPY : DAY_TREND_COPY;
  const trendOnPointSelect = dayRange === undefined ? onWeekSelect : dayRange.onDaySelect;
  const trendSubtitle =
    dayRange === undefined || trendCopy.subtitle === null
      ? null
      : trendCopy.subtitle(
          `${formatWeekStart(dayRange.from)}–${formatWeekStart(dayRange.to)}`,
        );
  // Empty means "latest" for direct component consumers; explicit all-period
  // scope is carried separately so it can never be confused with first load.
  const latestWeek = selectLatestWeek(view);
  const effectiveWeek =
    allWeeks
      ? ""
      : activeWeek !== ""
      ? activeWeek
      : (latestWeek?.cohort_week ?? "");
  const trendActiveKey = dayRange === undefined ? effectiveWeek : dayRange.activeDay;

  const selectedWeek = weeks.find((week) => week.cohort_week === effectiveWeek);
  const weeklyDetail =
    effectiveWeek === "" ? undefined : view.by_week[effectiveWeek];
  const segments = weeklyDetail?.segments ?? view.segments;

  // §4.3: the day-grain backend now carries the full transfer/TPE shape on
  // every day, so day mode sums it straight from the plotted days via
  // `aggregateTransferReasonsFromDays()`. It only falls back to the latest
  // complete week (with a note) when a day in range still lacks the block —
  // an older snapshot generated before this contract landed.
  const weeklyView =
    dayRange === undefined
      ? view
      : weeklySnapshot === undefined
        ? view
        : selectView(weeklySnapshot, weekDefinition);
  const dayRangeTransfer =
    dayRange === undefined ? null : aggregateTransferReasonsFromDays(dayRange.plottedDays);
  const usesDayRangeDiagnostics = dayRange !== undefined && dayRangeTransfer !== null;
  const diagnosticsWeek =
    dayRange === undefined
      ? selectedWeek
      : usesDayRangeDiagnostics
        ? undefined
        : (selectLatestWeek(weeklyView) ?? undefined);
  const diagnosticsWeeklyDetail =
    diagnosticsWeek === undefined ? undefined : weeklyView.by_week[diagnosticsWeek.cohort_week];
  const transfer = usesDayRangeDiagnostics
    ? dayRangeTransfer
    : (diagnosticsWeeklyDetail?.transfer_reasons ?? weeklyView.transfer_reasons);
  // rule_gt4 always has a real day-grain source (aggregateDays() sums
  // gt4_turn_with_cs/without_cs directly) so day mode never needs the weekly
  // fallback here, unlike transfer/TPE above.
  const rule =
    dayRange !== undefined
      ? view.rule_gt4
      : diagnosticsWeek === undefined
        ? weeklyView.rule_gt4
        : {
            gt4_turn_total:
              diagnosticsWeek.gt4_turn_with_cs + diagnosticsWeek.gt4_turn_without_cs,
            gt4_turn_with_cs: diagnosticsWeek.gt4_turn_with_cs,
            gt4_turn_without_cs: diagnosticsWeek.gt4_turn_without_cs,
            max_replies_rule_fired: diagnosticsWeek.max_replies_rule_fired,
          };
  const dayModeDiagnosticsNote =
    dayRange === undefined || usesDayRangeDiagnostics || diagnosticsWeek === undefined
      ? null
      : `Chẩn đoán chuyển CS và TPE tính theo tuần trọn vẹn (${formatWeekRange(
          diagnosticsWeek.cohort_week,
          weekDefinition,
        )}), không theo khoảng ngày đã chọn.`;

  // The day-range synthetic `view` carries CSAT and entry coverage as null
  // (report-scope.ts), so day mode reads the real weekly snapshot instead of
  // quietly reporting "not connected". `touchedWeeks` is now only the
  // fallback for snapshots written before day grain existed -- both CSAT and
  // entry coverage cut to the picked range exactly when `by_day` is present.
  const touchedWeeks = useMemo(
    () =>
      dayRange === undefined
        ? []
        : Object.keys(buildDayRangeWeekLabels(dayRange.plottedDays)).sort(),
    [dayRange],
  );
  const csat = dayRange === undefined ? view.csat : (weeklyView.csat ?? null);
  const entryCoverage =
    dayRange === undefined ? view.entry_coverage : weeklyView.entry_coverage;
  const entryCoverageScopeNote =
    dayRange === undefined
      ? undefined
      : entryCoverage !== null && entryCoverage.by_day !== undefined
        ? `Phạm vi độ phủ: ${formatDateRangeLabel(
            dayRange.from,
            dayRange.to,
          )} · đúng khoảng ngày đã chọn`
        : touchedWeeks.length === 0
          ? undefined
          : `Độ phủ theo tuần trọn vẹn chạm khoảng ngày: ${touchedWeeks
              .map((week) => formatWeekRange(week, weekDefinition))
              .join(", ")}. Bản dữ liệu này chưa có độ phủ theo ngày.`;

  return (
    <>
      <EntryCoverageSection
        entryCoverage={entryCoverage}
        weekDefinition={weekDefinition}
        {...(entryCoverageScopeNote === undefined
          ? {}
          : { scopeNote: entryCoverageScopeNote })}
        {...(dayRange === undefined
          ? {}
          : { dayRange: { from: dayRange.from, to: dayRange.to } })}
      />
      <section id="trend" className={styles.section} aria-labelledby="trend-title">
        <div className={styles.sectionHead}>
          <div>
            <h2 id="trend-title" className={styles.sectionTitle}>
              Volume và tỷ lệ theo tuần
            </h2>
          </div>
          {view.same_period === null ? null : (
            <div
              className={styles.segmented}
              role="group"
              aria-label="Phạm vi biểu đồ"
            >
              <button
                type="button"
                className={styles.segmentedButton}
                aria-pressed={effectiveTrendMode === "same_period"}
                onClick={() => setTrendMode("same_period")}
              >
                {`Cùng kỳ đến ${formatWeekdayCode(
                  view.same_period.cutoff_weekday,
                )}`}
              </button>
              <button
                type="button"
                className={styles.segmentedButton}
                aria-pressed={effectiveTrendMode === "full"}
                onClick={() => setTrendMode("full")}
              >
                Tuần đủ
              </button>
            </div>
          )}
        </div>
        {effectiveTrendMode === "same_period" &&
        view.same_period !== null ? (
          <p className={styles.sectionNote}>
            {`Mọi tuần đều cắt tới ${formatWeekdayName(
              view.same_period.cutoff_weekday,
            )} để so cùng kỳ.`}
          </p>
        ) : null}
        <TrendPanels
          points={trendPoints}
          copy={trendCopy}
          subtitle={trendSubtitle}
          activeKey={trendActiveKey}
          onPointSelect={trendOnPointSelect}
        />
      </section>

      <section id="segments" className={styles.section} aria-labelledby="segments-title">
        <div className={styles.sectionHead}>
          <div>
            <h2 id="segments-title" className={styles.sectionTitle}>
              So sánh theo thuộc tính ticket
            </h2>
          </div>
        </div>
        <SegmentTable segments={segments} onSelect={onSegmentSelect} />
      </section>

      <CsatSection
        csat={csat}
        effectiveWeek={effectiveWeek}
        weekDefinition={weekDefinition}
        activeBreakdownFilters={activeCsatBreakdownFilters}
        onBreakdownSelect={onCsatBreakdownSelect}
        onBreakdownRowSelect={(grouping, value) =>
          onTicketFilterSelect({ [grouping]: value })
        }
        onBreakdownGroupingChange={onCsatBreakdownGroupingChange}
        freshdeskCookieState={freshdeskCookieState}
        onOpenFreshdeskCookieDialog={onOpenFreshdeskCookieDialog}
        {...(dayRange === undefined
          ? {}
          : {
              // Both are passed: CSAT cuts to the exact days when the
              // snapshot carries day grain, and falls back to the touched
              // weeks when it does not (see CsatSection).
              scopeWeeks: touchedWeeks,
              dayRange: { from: dayRange.from, to: dayRange.to },
            })}
      />

      <TransferDiagnostics
        transfer={transfer}
        rule={rule}
        selectedWeek={diagnosticsWeek}
        weekDefinition={weekDefinition}
        dayModeNote={dayModeDiagnosticsNote}
        onShowStuckTickets={() => onShowStuckTickets(effectiveWeek)}
        onTicketFilterSelect={onTicketFilterSelect}
      />

      <DataTrustSection snapshot={snapshot} />
    </>
  );
}
