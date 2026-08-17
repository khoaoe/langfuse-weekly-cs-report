import { useEffect, useMemo, useState } from "react";
import { scaleBand, scaleLinear } from "@visx/scale";
import { Bar, LinePath } from "@visx/shape";

import type {
  DashboardSnapshot,
  Segments,
  SamePeriod,
  WeekDefinition,
  WeeklyReportRow,
} from "../lib/dashboard-schema";
import type { TicketFilterKey, TicketFilters } from "../lib/dashboard-filters";
import { niceVolumeTicks } from "../lib/chart-scale";
import {
  formatCount,
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
import { EntryCoverageSection } from "./EntryCoverageSection";
import { TransferDiagnostics } from "./TransferDiagnostics";
import belowFoldStyles from "./below-fold.module.css";
import styles from "./dashboard.module.css";
import trendStyles from "./trend.module.css";

const CHART_WIDTH = 720;
const CHART_HEIGHT = 220;
const MARGIN = { top: 12, right: 16, bottom: 28, left: 56 } as const;
const INNER_WIDTH = CHART_WIDTH - MARGIN.left - MARGIN.right;
const INNER_HEIGHT = CHART_HEIGHT - MARGIN.top - MARGIN.bottom;
const TICK_COUNT = 4;

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

type TrendTooltipKind = "volume" | "rate";

interface TrendTooltipState {
  readonly week: TrendWeek;
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

const DEFAULT_SEGMENT_SORT: TableSort<SegmentSortKey> = {
  key: "total",
  direction: "desc",
};

function ticks(count: number): number[] {
  return Array.from(
    { length: TICK_COUNT + 1 },
    (_, index) => (index * count) / TICK_COUNT,
  );
}

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
  weekDefinition,
}: {
  readonly state: TrendTooltipState;
  readonly weekDefinition: WeekDefinition;
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
      <strong>{`Tuần ${formatWeekRange(
        state.week.cohort_week,
        weekDefinition,
      )}`}</strong>
      {showVolume ? (
        <>
          <span>{`Tổng ${formatCount(state.week.total_tickets)} ticket`}</span>
          <span>{`AI First ${formatCount(state.week.ai_first_count)} ticket`}</span>
        </>
      ) : null}
      {showRate ? (
        <>
          <span>{`AI First ${formatRate(state.week.ai_first_rate)}`}</span>
          <span>{`Reopen sau AI First ${formatRate(
            state.week.reopen_lifetime_rate,
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
  weeks,
  weekDefinition,
  activeWeek,
  onWeekSelect,
}: {
  readonly weeks: readonly TrendWeek[];
  readonly weekDefinition: WeekDefinition;
  readonly activeWeek: string;
  readonly onWeekSelect: (cohortWeek: string) => void;
}) {
  const [tooltip, setTooltip] = useState<TrendTooltipState | null>(null);
  const observed = weeks.filter((week) => week.has_data);
  if (observed.length < MIN_TREND_WEEKS) {
    return (
      <p id="trendEmpty" className={belowFoldStyles.empty}>
        {`Cần ít nhất ${MIN_TREND_WEEKS} tuần có dữ liệu mới vẽ được xu hướng. Hiện có ${formatCount(
          observed.length,
        )} tuần.`}
      </p>
    );
  }

  const chartWeeks = [...weeks];
  const weekScale = scaleBand<string>({
    domain: chartWeeks.map((week) => week.cohort_week),
    range: [0, INNER_WIDTH],
  });
  const step = weekScale.bandwidth();
  const barWidth = Math.max(2, step * 0.34);
  const maxVolume = Math.max(0, ...observed.map((week) => week.total_tickets));
  const volumeTicks = niceVolumeTicks(maxVolume);
  const volumeCeiling = volumeTicks.at(-1) ?? 1;
  const volumeY = scaleLinear<number>({
    domain: [0, volumeCeiling],
    range: [INNER_HEIGHT, 0],
  });
  const rateY = scaleLinear<number>({
    domain: [0, 1],
    range: [INNER_HEIGHT, 0],
    clamp: true,
  });
  const x = (week: TrendWeek) => weekScale(week.cohort_week) ?? 0;
  const centre = (week: TrendWeek) => x(week) + step / 2;
  const labelledIndexes = new Set([
    0,
    weeks.length - 1,
    ...weeks.flatMap((week, index) =>
      index % 3 === 0 || week.cohort_status === "wtd" ? [index] : [],
    ),
  ]);
  const renderXAxis = () =>
    weeks.map((week, index) =>
      labelledIndexes.has(index) ? (
        <g key={`axis-${week.cohort_week}`}>
          {week.cohort_status === "wtd" ? (
            <line
              className={trendStyles.wtdMarker}
              x1={centre(week)}
              x2={centre(week)}
              y1={0}
              y2={INNER_HEIGHT}
            />
          ) : null}
          <text
            className={`${trendStyles.axisLabel} ${
              week.cohort_status === "wtd" ? trendStyles.wtdAxisLabel : ""
            }`}
            x={centre(week)}
            y={INNER_HEIGHT + 18}
            textAnchor="middle"
          >
            {`${formatWeekStart(week.cohort_week)}${
              week.cohort_status === "wtd" ? " · WTD" : ""
            }`}
          </text>
        </g>
      ) : null,
    );

  const renderWeekTargets = (chart: "volume" | "rate") =>
    weeks.map((week) =>
      week.has_data ? (
        <g
          key={`target-${week.cohort_week}`}
          className={trendStyles.weekTarget}
          data-week-target={week.cohort_week}
          aria-hidden="true"
          onPointerEnter={(event) => {
            const bounds =
              event.currentTarget.ownerSVGElement?.getBoundingClientRect();
            setTooltip({
              week,
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
                week,
                chart,
                anchorX: tooltipAnchor(event.clientX, bounds),
              });
            }
          }}
          onPointerLeave={() => setTooltip(null)}
          onClick={() => onWeekSelect(week.cohort_week)}
        >
          <rect
            className={`${trendStyles.weekHit} ${
              activeWeek === week.cohort_week ? trendStyles.weekHitActive : ""
            }`}
            x={x(week)}
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
      <div className={trendStyles.charts}>
        <figure className={trendStyles.chart}>
        <figcaption className={trendStyles.chartTitle}>Volume ticket theo tuần</figcaption>
        <div
          className={trendStyles.chartViewport}
          role="region"
          aria-label="Biểu đồ volume, cuộn ngang khi cần"
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
          <title id="trend-volume-title">Volume ticket theo tuần</title>
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
            {weeks.map((week) =>
              week.has_data ? (
                <g key={week.cohort_week}>
                  <Bar
                    className={trendStyles.seriesPrimaryFill ?? ""}
                    x={centre(week) - barWidth}
                    y={volumeY(week.total_tickets)}
                    width={barWidth}
                    height={INNER_HEIGHT - volumeY(week.total_tickets)}
                  />
                  <Bar
                    className={trendStyles.seriesSecondaryFill ?? ""}
                    x={centre(week)}
                    y={volumeY(week.ai_first_count)}
                    width={barWidth}
                    height={INNER_HEIGHT - volumeY(week.ai_first_count)}
                  />
                </g>
              ) : null,
            )}
            {renderWeekTargets("volume")}
          </g>
          </svg>
        </div>
        {tooltip?.chart === "volume" ? (
          <TrendTooltip state={tooltip} weekDefinition={weekDefinition} />
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
            : `Tuần gần nhất có dữ liệu ${formatWeekRange(
                latest.cohort_week,
                weekDefinition,
              )}: ${formatCount(latest.total_tickets)} ticket, trong đó ${formatCount(
                latest.ai_first_count,
              )} ticket AI First.`}
        </p>
        </figure>

        <figure className={trendStyles.chart}>
        <figcaption className={trendStyles.chartTitle}>Tỷ lệ theo tuần</figcaption>
        <div
          className={trendStyles.chartViewport}
          role="region"
          aria-label="Biểu đồ tỷ lệ, cuộn ngang khi cần"
          tabIndex={0}
        >
          <svg
            className={trendStyles.chartSvg}
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            role="img"
            aria-labelledby="trend-rate-title"
            aria-describedby="trend-rate-desc"
          >
          <title id="trend-rate-title">Tỷ lệ AI First và reopen theo tuần</title>
          <desc id="trend-rate-desc">
            Hai đường dùng chung trục phần trăm từ 0 đến 100. Đường liền là AI
            First, đường nét đứt là reopen sau AI First. Volume nằm ở biểu đồ
            phía trên để tránh hai trục trong một khung.
          </desc>
          <g transform={`translate(${MARGIN.left} ${MARGIN.top})`}>
            {ticks(1).map((tick) => (
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
            <LinePath<TrendWeek>
              className={trendStyles.seriesPrimaryStroke ?? ""}
              data={chartWeeks}
              defined={(week) => week.has_data}
              x={centre}
              y={(week) => rateY(week.ai_first_rate)}
            />
            <LinePath<TrendWeek>
              className={trendStyles.seriesSecondaryStroke ?? ""}
              data={chartWeeks}
              defined={(week) =>
                week.has_data && week.reopen_lifetime_rate !== null
              }
              x={centre}
              y={(week) => rateY(week.reopen_lifetime_rate ?? 0)}
            />
            {renderWeekTargets("rate")}
          </g>
          </svg>
        </div>
        {tooltip?.chart === "rate" ? (
          <TrendTooltip state={tooltip} weekDefinition={weekDefinition} />
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
            : `Tuần gần nhất có dữ liệu: AI First ${formatRate(
                latest.ai_first_rate,
              )}, reopen ${formatRate(latest.reopen_lifetime_rate)}.`}
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
        Ticket: tỷ trọng trong tuần. AI First, Chuyển CS, Reopen: tỷ lệ trong
        chính nhóm đó.
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
            {rows.map(({ label, counts }) => (
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
}

/**
 * Trends, segment comparison, transfer diagnostics and the data-quality
 * disclosure — everything that explains the ledger above.
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
  // Empty means "latest" for direct component consumers; explicit all-period
  // scope is carried separately so it can never be confused with first load.
  const latestWeek = selectLatestWeek(view);
  const effectiveWeek =
    allWeeks
      ? ""
      : activeWeek !== ""
      ? activeWeek
      : (latestWeek?.cohort_week ?? "");

  const selectedWeek = weeks.find((week) => week.cohort_week === effectiveWeek);
  const weeklyDetail =
    effectiveWeek === "" ? undefined : view.by_week[effectiveWeek];
  const segments = weeklyDetail?.segments ?? view.segments;
  const transfer = weeklyDetail?.transfer_reasons ?? view.transfer_reasons;
  const rule =
    selectedWeek === undefined
      ? view.rule_gt4
      : {
          gt4_turn_total:
            selectedWeek.gt4_turn_with_cs + selectedWeek.gt4_turn_without_cs,
          gt4_turn_with_cs: selectedWeek.gt4_turn_with_cs,
          gt4_turn_without_cs: selectedWeek.gt4_turn_without_cs,
          max_replies_rule_fired: selectedWeek.max_replies_rule_fired,
        };
  return (
    <>
      <EntryCoverageSection
        entryCoverage={view.entry_coverage}
        weekDefinition={weekDefinition}
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
          weeks={trendWeeks}
          weekDefinition={weekDefinition}
          activeWeek={effectiveWeek}
          onWeekSelect={onWeekSelect}
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
        csat={view.csat}
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
      />

      <TransferDiagnostics
        transfer={transfer}
        rule={rule}
        selectedWeek={selectedWeek}
        weekDefinition={weekDefinition}
        onShowStuckTickets={() => onShowStuckTickets(effectiveWeek)}
        onTicketFilterSelect={onTicketFilterSelect}
      />
    </>
  );
}
