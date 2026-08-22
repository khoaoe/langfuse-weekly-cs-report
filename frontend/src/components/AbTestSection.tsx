import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { scaleLinear, scalePoint } from "@visx/scale";
import { LinePath } from "@visx/shape";

import {
  DashboardRequestError,
  fetchAbTest,
  fetchAbTestDefault,
  fetchAbTestModels,
} from "../lib/api";
import {
  parseAbTestModels,
  parseAbTestSnapshot,
  type AbTestSnapshot,
  type DailyArmPoint,
} from "../lib/ab-test-schema";
import {
  buildMetricRows,
  metricDelta,
  type MetricRow,
} from "../lib/ab-test-metrics";
import type { WeekDefinition } from "../lib/dashboard-schema";
import { formatCount, formatRate } from "../lib/format";
import styles from "./dashboard.module.css";
import trendStyles from "./trend.module.css";
import abTestStyles from "./ab-test.module.css";

const VIETNAM_TZ = "Asia/Ho_Chi_Minh";
// Sized to sit beside the comparison table rather than span the page: the
// viewBox scales to whatever width the column gives it.
const CHART_WIDTH = 460;
const CHART_HEIGHT = 260;
const CHART_PADDING = { top: 12, right: 12, bottom: 28, left: 40 };
/** Above this many days the x labels collide, so every other one is dropped. */
const MAX_DENSE_X_LABELS = 8;

interface WindowValue {
  readonly start: string; // datetime-local value, Asia/Ho_Chi_Minh wall clock
  readonly end: string;
}

function vietnamParts(date: Date): { date: string; time: string } {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: VIETNAM_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const parts = Object.fromEntries(
    formatter.formatToParts(date).map((part) => [part.type, part.value]),
  );
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${parts.hour}:${parts.minute}`,
  };
}

function vietnamDateTimeLocal(date: Date): string {
  const parts = vietnamParts(date);
  return `${parts.date}T${parts.time}`;
}

/** Pure calendar-date arithmetic (no timezone conversion): `cohort_week` is
 * already a Y-M-D label, same convention as `formatWeekRange` in format.ts. */
function addCalendarDays(dateStr: string, days: number): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  const shifted = new Date(
    Date.UTC(year ?? 1970, (month ?? 1) - 1, (day ?? 1) + days),
  );
  return `${shifted.getUTCFullYear()}-${String(shifted.getUTCMonth() + 1).padStart(2, "0")}-${String(shifted.getUTCDate()).padStart(2, "0")}`;
}

function defaultWindowFromReportScope(
  selectedReportWeeks: readonly string[],
  weekDefinition: WeekDefinition,
): WindowValue {
  const now = new Date();
  if (selectedReportWeeks.length === 0) {
    const start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    return {
      start: vietnamDateTimeLocal(start),
      end: vietnamDateTimeLocal(now),
    };
  }
  const sorted = [...selectedReportWeeks].sort();
  const firstWeek = sorted[0] as string;
  const lastWeek = sorted[sorted.length - 1] as string;
  const candidateEnd = addCalendarDays(
    lastWeek,
    weekDefinition === "mon_fri" ? 5 : 7,
  );
  const today = vietnamParts(now).date;
  return {
    start: `${firstWeek}T00:00`,
    end:
      candidateEnd > today
        ? vietnamDateTimeLocal(now)
        : `${candidateEnd}T00:00`,
  };
}

function toIsoWithOffset(dateTimeLocalValue: string): string {
  return `${dateTimeLocalValue}:00+07:00`;
}

function abTestErrorMessage(error: unknown): string {
  if (error instanceof DashboardRequestError) {
    if (error.status === 400) {
      return "Khoảng thời gian không hợp lệ (tối đa 60 ngày).";
    }
    if (error.status === 503) {
      return "Không đọc được Langfuse lúc này. Thử lại sau.";
    }
  }
  return "Không đọc được dữ liệu AB test.";
}

/** Model ids are long; the trailing segment is what tells them apart. */
function shortArmLabel(arm: string): string {
  const slash = arm.lastIndexOf("/");
  return slash === -1 ? arm : arm.slice(slash + 1);
}

function formatSeconds(value: number): string {
  if (value < 60) {
    return `${value.toFixed(1)}s`;
  }
  const minutes = Math.floor(value / 60);
  return `${minutes}m ${Math.round(value % 60)}s`;
}

function formatMetricValue(row: MetricRow, value: number | null): string {
  if (value === null) {
    return "—";
  }
  if (row.kind === "rate") {
    return formatRate(value);
  }
  if (row.kind === "seconds") {
    return formatSeconds(value);
  }
  return value >= 100 || Number.isInteger(value)
    ? formatCount(Math.round(value))
    : value.toFixed(2).replace(".", ",");
}

function formatDeltaValue(row: MetricRow, value: number): string {
  const sign = value > 0 ? "+" : "";
  if (row.kind === "rate") {
    return `${sign}${(value * 100).toFixed(1).replace(".", ",")} pp`;
  }
  return `${sign}${(value * 100).toFixed(0)}%`;
}

interface DailySeries {
  readonly dates: readonly string[];
  readonly byArm: ReadonlyMap<string, readonly (number | null)[]>;
}

type DailyMetricKind = "rate" | "seconds" | "number";

interface DailyMetricOption {
  readonly key: string;
  readonly label: string;
  readonly group: string;
  readonly kind: DailyMetricKind;
  /** Raw value for one day/arm, or null when the day's sample is too thin
   * to trust -- left as a gap rather than a spike the reader would over-read. */
  readonly value: (point: DailyArmPoint) => number | null;
}

/** Only metrics with a valid daily aggregation make the cut here. Token
 * sums are re-bucketed from the metrics endpoint's UTC-hour granularity into
 * Asia/Ho_Chi_Minh days server-side, same as the ticket-fact metrics, so
 * every line on this chart shares the same day boundary. LLM-call latency
 * (p95) stays comparison-table-only: a p95 does not sum or average across
 * sub-buckets into a valid daily p95, and the endpoint returns only
 * pre-aggregated percentiles, never raw samples to re-derive one from. */
const DAILY_METRIC_OPTIONS: readonly DailyMetricOption[] = [
  {
    key: "ai_end_to_end",
    label: "AI xử lý trọn",
    group: "Kết quả xử lý",
    kind: "rate",
    value: (point) =>
      point.ticket_count >= 10 ? point.ai_end_to_end / point.ticket_count : null,
  },
  {
    key: "ai_first",
    label: "AI First",
    group: "Kết quả xử lý",
    kind: "rate",
    value: (point) =>
      point.ticket_count >= 10 ? point.ai_first_count / point.ticket_count : null,
  },
  {
    key: "transferred",
    label: "Chuyển CS",
    group: "Kết quả xử lý",
    kind: "rate",
    value: (point) =>
      point.ticket_count >= 10 ? point.transferred_count / point.ticket_count : null,
  },
  {
    key: "direct_cs",
    label: "Vào thẳng CS",
    group: "Kết quả xử lý",
    kind: "rate",
    value: (point) =>
      point.ticket_count >= 10 ? point.direct_cs / point.ticket_count : null,
  },
  {
    key: "reopen",
    label: "Reopen",
    group: "Kết quả xử lý",
    kind: "rate",
    value: (point) =>
      point.reopen_denominator >= 10
        ? point.reopen_count / point.reopen_denominator
        : null,
  },
  {
    key: "latency_p50",
    label: "Thời gian xử lý p50",
    group: "Tốc độ",
    kind: "seconds",
    value: (point) => (point.ticket_count >= 10 ? point.latency_p50 : null),
  },
  {
    key: "latency_p95",
    label: "Thời gian xử lý p95",
    group: "Tốc độ",
    kind: "seconds",
    value: (point) => (point.ticket_count >= 10 ? point.latency_p95 : null),
  },
  {
    key: "turns_per_ticket",
    label: "Lượt / ticket",
    group: "Chi phí",
    kind: "number",
    value: (point) =>
      point.ticket_count >= 10 ? point.turn_total / point.ticket_count : null,
  },
  {
    key: "tokens_per_ticket",
    label: "Token / ticket",
    group: "Chi phí",
    kind: "number",
    value: (point) =>
      point.ticket_count >= 10 ? point.total_tokens / point.ticket_count : null,
  },
  {
    key: "output_tokens_per_ticket",
    label: "Token output / ticket",
    group: "Chi phí",
    kind: "number",
    value: (point) =>
      point.ticket_count >= 10 ? point.output_tokens / point.ticket_count : null,
  },
];
const DAILY_METRIC_GROUPS = ["Kết quả xử lý", "Tốc độ", "Chi phí"] as const;

/** One series per arm for the selected metric, aligned on a shared date axis. */
function dailyMetricSeries(
  data: AbTestSnapshot,
  arms: readonly string[],
  metric: DailyMetricOption,
): DailySeries {
  const dates = [...new Set(data.daily.map((row) => row.date))].sort();
  const index = new Map(dates.map((date, position) => [date, position]));
  const byArm = new Map<string, (number | null)[]>(
    arms.map((arm) => [arm, dates.map(() => null)]),
  );
  for (const row of data.daily) {
    const position = index.get(row.date);
    const series = byArm.get(row.arm);
    if (position === undefined || series === undefined) {
      continue;
    }
    series[position] = metric.value(row);
  }
  return { dates, byArm };
}

function seriesMax(series: DailySeries): number {
  let max = 0;
  for (const values of series.byArm.values()) {
    for (const value of values) {
      if (value !== null && value > max) {
        max = value;
      }
    }
  }
  return max;
}

function formatTickValue(kind: DailyMetricKind, tick: number): string {
  if (kind === "rate") {
    return `${Math.round(tick * 100)}%`;
  }
  if (kind === "seconds") {
    return formatSeconds(tick);
  }
  return tick.toFixed(1);
}

function DailyMetricChart({
  series,
  arms,
  metric,
  onMetricChange,
}: {
  readonly series: DailySeries;
  readonly arms: readonly string[];
  readonly metric: DailyMetricOption;
  readonly onMetricChange: (key: string) => void;
}) {
  const { dates, byArm } = series;
  const xScale = scalePoint<string>({
    domain: [...dates],
    range: [CHART_PADDING.left, CHART_WIDTH - CHART_PADDING.right],
    padding: 0.5,
  });
  const isRate = metric.kind === "rate";
  const rawMax = isRate ? 1 : seriesMax(series);
  const domainMax = isRate ? 1 : rawMax > 0 ? rawMax * 1.1 : 1;
  const yScale = scaleLinear<number>({
    domain: [0, domainMax],
    range: [CHART_HEIGHT - CHART_PADDING.bottom, CHART_PADDING.top],
  });
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => fraction * domainMax);
  const strokeClass = [
    trendStyles.seriesPrimaryStroke ?? "",
    trendStyles.seriesSecondaryStroke ?? "",
  ];

  const labelStride = dates.length > MAX_DENSE_X_LABELS ? 2 : 1;

  return (
    <figure className={abTestStyles.chartCard}>
      <div className={abTestStyles.chartHeader}>
        <h3 className={abTestStyles.tableTitle}>{`${metric.label} theo ngày`}</h3>
        <label className={abTestStyles.chartMetricPicker}>
          Chỉ số
          <select
            id="abTestDailyMetric"
            value={metric.key}
            onChange={(event) => onMetricChange(event.target.value)}
          >
            {DAILY_METRIC_GROUPS.map((group) => (
              <optgroup label={group} key={group}>
                {DAILY_METRIC_OPTIONS.filter(
                  (option) => option.group === group,
                ).map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
      </div>
      <div>
        <svg
          className={abTestStyles.chartSvg}
          viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
          role="img"
          aria-label={`Biểu đồ ${metric.label} theo ngày, tách theo model`}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                className={trendStyles.gridLine}
                x1={CHART_PADDING.left}
                x2={CHART_WIDTH - CHART_PADDING.right}
                y1={yScale(tick)}
                y2={yScale(tick)}
              />
              <text
                className={trendStyles.axisLabel}
                x={CHART_PADDING.left - 8}
                y={yScale(tick) + 4}
                textAnchor="end"
              >
                {formatTickValue(metric.kind, tick)}
              </text>
            </g>
          ))}
          {dates.map((date, position) =>
            position % labelStride === 0 ? (
              <text
                key={date}
                className={trendStyles.axisLabel}
                x={xScale(date) ?? 0}
                y={CHART_HEIGHT - 8}
                textAnchor="middle"
              >
                {date.slice(5)}
              </text>
            ) : null,
          )}
          {arms.map((arm, armIndex) => {
            const values = byArm.get(arm) ?? [];
            const points = dates
              .map((date, position) => ({ date, value: values[position] ?? null }))
              .filter(
                (point): point is { date: string; value: number } =>
                  point.value !== null,
              );
            return (
              <LinePath<{ date: string; value: number }>
                key={arm}
                className={strokeClass[armIndex] ?? ""}
                data={points}
                x={(point) => xScale(point.date) ?? 0}
                y={(point) => yScale(point.value)}
              />
            );
          })}
        </svg>
      </div>
      <div className={trendStyles.legend}>
        {arms.map((arm, armIndex) => (
          <span className={trendStyles.legendItem} key={arm}>
            <span
              className={
                armIndex === 0
                  ? trendStyles.swatchPrimary
                  : trendStyles.swatchSecondary
              }
            />
            {shortArmLabel(arm)}
          </span>
        ))}
      </div>
    </figure>
  );
}

function ComparisonTable({
  rows,
  arms,
}: {
  readonly rows: readonly MetricRow[];
  readonly arms: readonly string[];
}) {
  let lastGroup = "";
  return (
    <div className={abTestStyles.chartCard}>
      <h3 className={abTestStyles.tableTitle}>
        {arms.length === 2
          ? `So sánh ${shortArmLabel(arms[0] as string)} với ${shortArmLabel(arms[1] as string)}`
          : "So sánh model"}
      </h3>
      <div className={styles.tableScroll}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Chỉ số</th>
            {arms.map((arm) => (
              <th scope="col" className={styles.numeric} key={arm}>
                <code className={abTestStyles.armLabel}>
                  {shortArmLabel(arm)}
                </code>
              </th>
            ))}
            <th scope="col" className={styles.numeric}>
              Δ
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const delta = metricDelta(row);
            const groupHeader = row.group !== lastGroup ? row.group : null;
            lastGroup = row.group;
            return (
              <Fragment key={row.key}>
                {groupHeader ? (
                  <tr className={abTestStyles.groupRow}>
                    <th scope="rowgroup" colSpan={arms.length + 2}>
                      {groupHeader}
                    </th>
                  </tr>
                ) : null}
                <tr>
                  <th scope="row" className={styles.stickyColumn}>
                    {row.label}
                    {row.hint ? (
                      <span className={abTestStyles.metricHint}>{row.hint}</span>
                    ) : null}
                  </th>
                  {row.values.map((value, armIndex) => (
                    <td
                      className={styles.numeric}
                      key={arms[armIndex] ?? armIndex}
                    >
                      {formatMetricValue(row, value ?? null)}
                      {value === null && row.denominators[armIndex] !== undefined ? (
                        <span className={abTestStyles.sampleNote}>
                          {`n=${formatCount(row.denominators[armIndex])}`}
                        </span>
                      ) : null}
                    </td>
                  ))}
                  <td className={styles.numeric}>
                    {delta === null ? (
                      "—"
                    ) : (
                      <span
                        className={
                          delta.better === null
                            ? abTestStyles.deltaNeutral
                            : delta.better
                              ? abTestStyles.deltaBetter
                              : abTestStyles.deltaWorse
                        }
                      >
                        {formatDeltaValue(row, delta.value)}
                      </span>
                    )}
                  </td>
                </tr>
              </Fragment>
            );
          })}
        </tbody>
      </table>
      </div>
    </div>
  );
}

/** Same vocabulary as `SEGMENT_DIMENSIONS` in BelowFold.tsx ("So sánh theo
 * thuộc tính ticket"), so the two sections never disagree on what a
 * dimension is called. */
const DIMENSION_TABS = [
  { key: "issue_category", label: "Category" },
  { key: "app", label: "App" },
  { key: "product_code", label: "Product Code" },
  { key: "skill", label: "Skill" },
  { key: "intent", label: "Intent" },
] as const;
type DimensionKey = (typeof DIMENSION_TABS)[number]["key"];

function DimensionTable({
  data,
  arms,
}: {
  readonly data: AbTestSnapshot;
  readonly arms: readonly string[];
}) {
  const [dimension, setDimension] = useState<DimensionKey>("issue_category");
  const rows = data.dimensions[dimension] ?? [];
  const lookup = new Map(rows.map((row) => [`${row.value}|${row.arm}`, row]));
  const totalByValue = new Map<string, number>();
  for (const row of rows) {
    totalByValue.set(row.value, (totalByValue.get(row.value) ?? 0) + row.ticket_count);
  }
  // Busiest attribute value first, so the reader sees where the sample
  // actually is before scanning down to the long tail.
  const values = [...new Set(rows.map((row) => row.value))].sort(
    (left, right) => (totalByValue.get(right) ?? 0) - (totalByValue.get(left) ?? 0),
  );

  return (
    <div>
      <div
        className={abTestStyles.tabs}
        role="tablist"
        aria-label="Thuộc tính so sánh"
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
            return;
          }
          event.preventDefault();
          const current = DIMENSION_TABS.findIndex(
            (item) => item.key === dimension,
          );
          const next =
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? DIMENSION_TABS.length - 1
                : (current +
                    (event.key === "ArrowRight" ? 1 : -1) +
                    DIMENSION_TABS.length) %
                  DIMENSION_TABS.length;
          const item = DIMENSION_TABS[next];
          if (item !== undefined) {
            setDimension(item.key);
            document.getElementById(`ab-test-dim-tab-${item.key}`)?.focus();
          }
        }}
      >
        {DIMENSION_TABS.map((item) => (
          <button
            key={item.key}
            id={`ab-test-dim-tab-${item.key}`}
            type="button"
            role="tab"
            className={abTestStyles.tab}
            aria-selected={dimension === item.key}
            aria-controls="ab-test-dim-panel"
            tabIndex={dimension === item.key ? 0 : -1}
            onClick={() => setDimension(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div
        id="ab-test-dim-panel"
        className={styles.tableScroll}
        role="tabpanel"
        aria-label={
          DIMENSION_TABS.find((item) => item.key === dimension)?.label ??
          dimension
        }
      >
        {values.length === 0 ? (
          <p className={styles.emptyCell}>
            Không có dữ liệu cho thuộc tính này trong khoảng thời gian đang
            chọn.
          </p>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">
                  {DIMENSION_TABS.find((item) => item.key === dimension)
                    ?.label ?? dimension}
                </th>
                {arms.map((arm) => (
                  <th scope="col" className={styles.numeric} key={arm}>
                    <code className={abTestStyles.armLabel}>
                  {shortArmLabel(arm)}
                </code>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {values.map((value) => (
                <tr key={value}>
                  <th scope="row" className={styles.stickyColumn}>
                    {value}
                  </th>
                  {arms.map((arm) => {
                    const row = lookup.get(`${value}|${arm}`);
                    if (row === undefined || row.ticket_count === 0) {
                      return (
                        <td className={styles.numeric} key={arm}>
                          —
                        </td>
                      );
                    }
                    return (
                      <td className={styles.numeric} key={arm}>
                        {formatCount(row.ticket_count)}
                        <span className={abTestStyles.sampleNote}>
                          {row.ticket_count >= 20
                            ? `AI trọn ${formatRate(row.ai_end_to_end / row.ticket_count)}`
                            : `AI trọn ${formatCount(row.ai_end_to_end)}`}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export function AbTestSection({
  selectedReportWeeks,
  weekDefinition,
}: {
  readonly selectedReportWeeks: readonly string[];
  readonly weekDefinition: WeekDefinition;
}) {
  // Collapsed by default to keep the dashboard short. The Langfuse read is
  // expensive, so it is gated on the panel actually being open rather than
  // fired for every reader who never looks at this section.
  const [open, setOpen] = useState(
    () => typeof window !== "undefined" && window.location.hash === "#ab-test",
  );
  const [override, setOverride] = useState<WindowValue | null>(null);
  // null = defer to the server's own default arm selection (the two models
  // it found overlapping most recently). Set only once the reader picks a
  // pair through the model picker below.
  const [armsOverride, setArmsOverride] = useState<readonly [string, string] | null>(
    null,
  );
  const defaultWindow = useMemo(
    () => defaultWindowFromReportScope(selectedReportWeeks, weekDefinition),
    [selectedReportWeeks, weekDefinition],
  );

  // Discovers which models have recent traffic and each one's first-seen
  // timestamp -- feeds both the picker's option list and the auto window
  // below. Runs every time the panel opens, per product decision (cheap:
  // served from the server's own cache after the first live discovery).
  const modelsQuery = useQuery({
    queryKey: ["ab-test-models"],
    enabled: open,
    retry: false,
    queryFn: async ({ signal }) => {
      const parsed = parseAbTestModels(await fetchAbTestModels(signal));
      if (!parsed.ok) {
        throw new Error(parsed.message);
      }
      return parsed.data;
    },
  });

  // When the reader picks a pair, the window defaults to when both models
  // first ran side by side -- the true start of that comparison -- rather
  // than the report's own date range, which usually predates either model.
  const armsAutoWindow = useMemo<WindowValue | null>(() => {
    if (armsOverride === null) {
      return null;
    }
    const models = modelsQuery.data?.models ?? [];
    const seenTimes = armsOverride
      .map((model) => models.find((entry) => entry.model === model)?.first_seen)
      .filter((value): value is string => typeof value === "string")
      .map((iso) => new Date(iso));
    if (seenTimes.length === 0) {
      return null;
    }
    const start = new Date(Math.max(...seenTimes.map((date) => date.getTime())));
    return { start: vietnamDateTimeLocal(start), end: vietnamDateTimeLocal(new Date()) };
  }, [armsOverride, modelsQuery.data]);

  const effectiveWindow = override ?? armsAutoWindow ?? defaultWindow;
  const startIso = toIsoWithOffset(effectiveWindow.start);
  const endIso = toIsoWithOffset(effectiveWindow.end);
  const isDefaultView = override === null && armsOverride === null;

  // Default view: read the background-refreshed cache (instant, matches the
  // main dashboard snapshot's trade-off). A custom range or a hand-picked
  // pair still costs a live Langfuse read, so it keeps the per-request path
  // with its own short-TTL cache instead.
  const defaultQuery = useQuery({
    queryKey: ["ab-test-default"],
    enabled: open && isDefaultView,
    retry: false,
    refetchInterval: 60_000,
    queryFn: async ({ signal }) => {
      const envelope = await fetchAbTestDefault(signal);
      if (envelope.status !== "ready" || envelope.data === null) {
        return null;
      }
      const parsed = parseAbTestSnapshot(envelope.data);
      if (!parsed.ok) {
        throw new Error(parsed.message);
      }
      return parsed.data;
    },
  });

  // Falls back to whatever pair the default view last resolved, so a
  // time-only override (picker untouched) still compares exactly the two
  // arms the reader was already looking at, not every arm with traffic in
  // the new window.
  const liveArms =
    armsOverride ?? (defaultQuery.data ? defaultQuery.data.arms.map((arm) => arm.arm) : undefined);

  const liveQuery = useQuery({
    queryKey: ["ab-test", startIso, endIso, liveArms?.join(",") ?? ""],
    enabled: open && !isDefaultView,
    retry: false,
    queryFn: async ({ signal }) => {
      const parsed = parseAbTestSnapshot(
        await fetchAbTest(startIso, endIso, liveArms, signal),
      );
      if (!parsed.ok) {
        throw new Error(parsed.message);
      }
      return parsed.data;
    },
  });

  const query = isDefaultView ? defaultQuery : liveQuery;
  // The default query resolves successfully even while the background cache
  // has nothing yet (`data: null`) -- that is still "loading" to the reader.
  const isLoading = isDefaultView
    ? defaultQuery.isLoading || (defaultQuery.isSuccess && defaultQuery.data === null)
    : liveQuery.isLoading;
  const data = query.data ?? undefined;
  // The default view shows the window the server actually computed, not the
  // client's guess -- they usually agree, but the payload is the truth.
  const windowLabel = isDefaultView && data
    ? {
        start: data.window_start.slice(0, 16).replace("T", " "),
        end: data.window_end.slice(0, 16).replace("T", " "),
      }
    : { start: effectiveWindow.start.replace("T", " "), end: effectiveWindow.end.replace("T", " ") };
  const arms = useMemo(
    () => (data ? data.arms.map((arm) => arm.arm) : []),
    [data],
  );
  const rows = useMemo(() => (data ? buildMetricRows(data.arms) : []), [data]);
  const [dailyMetricKey, setDailyMetricKey] = useState<string>("ai_end_to_end");
  const dailyMetric =
    DAILY_METRIC_OPTIONS.find((option) => option.key === dailyMetricKey) ??
    (DAILY_METRIC_OPTIONS[0] as DailyMetricOption);
  const series = useMemo(
    () => (data ? dailyMetricSeries(data, arms, dailyMetric) : null),
    [data, arms, dailyMetric],
  );

  return (
    <section
      id="ab-test"
      className={styles.section}
      aria-labelledby="ab-test-title"
    >
      <div className={styles.sectionHead}>
        <h2 id="ab-test-title" className={styles.sectionTitle}>
          A/B Test model
        </h2>
        <button
          type="button"
          className={styles.action}
          aria-expanded={open}
          aria-controls="ab-test-body"
          onClick={() => setOpen((current) => !current)}
        >
          {open ? "Thu gọn" : "Mở"}
        </button>
      </div>

      {!open ? null : (
      <div id="ab-test-body">
      <div className={abTestStyles.rangeRow}>
      <details className={abTestStyles.rangeDetails}>
        <summary className={abTestStyles.rangeSummary}>
          Chọn model so sánh
        </summary>
        <div className={abTestStyles.rangePanel}>
          {modelsQuery.isLoading ? (
            <p role="status">Đang dò model…</p>
          ) : modelsQuery.isError ? (
            <p role="alert">Không thể tải danh sách model.</p>
          ) : (
            <>
              {([0, 1] as const).map((slot) => {
                const current = armsOverride?.[slot] ?? liveArms?.[slot] ?? "";
                const otherSlot = slot === 0 ? 1 : 0;
                const other = armsOverride?.[otherSlot] ?? liveArms?.[otherSlot];
                const options = (modelsQuery.data?.models ?? []).filter(
                  (entry) => entry.model === current || entry.model !== other,
                );
                return (
                  <label className={abTestStyles.rangeField} key={slot}>
                    {slot === 0 ? "Model A" : "Model B"}
                    <select
                      value={current}
                      onChange={(event) => {
                        const nextValue = event.target.value;
                        const nextOther = other ?? "";
                        const nextPair: [string, string] =
                          slot === 0 ? [nextValue, nextOther] : [nextOther, nextValue];
                        setArmsOverride(nextPair);
                        setOverride(null);
                      }}
                    >
                      {current === "" ? <option value="">— chọn model —</option> : null}
                      {options.map((entry) => (
                        <option key={entry.model} value={entry.model}>
                          {shortArmLabel(entry.model)}
                        </option>
                      ))}
                    </select>
                  </label>
                );
              })}
            </>
          )}
        </div>
      </details>
      <details className={abTestStyles.rangeDetails}>
        <summary className={abTestStyles.rangeSummary}>
          Điều chỉnh thời gian
        </summary>
        <div className={abTestStyles.rangePanel}>
          <label className={abTestStyles.rangeField}>
            Bắt đầu
            <input
              type="datetime-local"
              value={effectiveWindow.start}
              onChange={(event) =>
                setOverride({
                  start: event.target.value,
                  end: override?.end ?? effectiveWindow.end,
                })
              }
            />
          </label>
          <label className={abTestStyles.rangeField}>
            Kết thúc
            <input
              type="datetime-local"
              value={effectiveWindow.end}
              onChange={(event) =>
                setOverride({
                  start: override?.start ?? effectiveWindow.start,
                  end: event.target.value,
                })
              }
            />
          </label>
          <button
            type="button"
            className={styles.action}
            onClick={() =>
              setOverride({
                start: override?.start ?? effectiveWindow.start,
                end: vietnamDateTimeLocal(new Date()),
              })
            }
          >
            Đặt kết thúc = hiện tại
          </button>
          {override !== null ? (
            <button
              type="button"
              className={styles.action}
              onClick={() => setOverride(null)}
            >
              Dùng lại thời gian mặc định
            </button>
          ) : null}
        </div>
      </details>
      </div>

      {isLoading ? (
        <p role="status">Đang tải…</p>
      ) : query.isError ? (
        <p role="alert">{abTestErrorMessage(query.error)}</p>
      ) : data && series ? (
        data.total_tickets === 0 ? (
          <p className={styles.emptyCell}>
            Không có ticket nào có <code>model_info</code> trong khoảng thời gian
            này.
          </p>
        ) : (
          <>
            <p className={abTestStyles.scopeNote}>
              {`${formatCount(data.total_tickets)} ticket · ${windowLabel.start} → ${windowLabel.end}`}
              {isDefaultView
                ? " · theo Phạm vi báo cáo"
                : armsOverride !== null
                  ? " · model tự chọn"
                  : ""}
            </p>
            {data.unmatched_tickets > 0 ? (
              <p className={abTestStyles.warningNote} role="status">
                {`${formatCount(data.unmatched_tickets)} ticket không có model_info nên không vào được so sánh.`}
              </p>
            ) : null}
            {data.arms.some((arm) => arm.low_sample) ? (
              <p className={abTestStyles.warningNote} role="status">
                Có model dưới 30 ticket — chênh lệch ở dưới chưa đủ tin cậy để
                kết luận.
              </p>
            ) : null}

            <div className={abTestStyles.compareRow}>
              <ComparisonTable rows={rows} arms={arms} />
              <DailyMetricChart
                series={series}
                arms={arms}
                metric={dailyMetric}
                onMetricChange={setDailyMetricKey}
              />
            </div>

            <details className={abTestStyles.disclosure}>
              <summary className={abTestStyles.disclosureSummary}>
                So sánh theo thuộc tính ticket
              </summary>
              <div className={abTestStyles.disclosureBody}>
                <DimensionTable data={data} arms={arms} />
              </div>
            </details>
          </>
        )
      ) : null}
      </div>
      )}
    </section>
  );
}
