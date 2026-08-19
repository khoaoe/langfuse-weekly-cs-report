import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { scaleLinear, scalePoint } from "@visx/scale";
import { LinePath } from "@visx/shape";

import { DashboardRequestError, fetchAbTest } from "../lib/api";
import {
  parseAbTestSnapshot,
  type AbTestSnapshot,
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

/** One rate series per arm, aligned on a shared date axis. */
function dailyRateSeries(data: AbTestSnapshot, arms: readonly string[]): DailySeries {
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
    // A day with a handful of tickets produces a rate that swings wildly;
    // leave it as a gap rather than draw a spike the reader would trust.
    series[position] =
      row.ticket_count >= 10 ? row.ai_end_to_end / row.ticket_count : null;
  }
  return { dates, byArm };
}

function DailyRateChart({
  series,
  arms,
}: {
  readonly series: DailySeries;
  readonly arms: readonly string[];
}) {
  const { dates, byArm } = series;
  const xScale = scalePoint<string>({
    domain: [...dates],
    range: [CHART_PADDING.left, CHART_WIDTH - CHART_PADDING.right],
    padding: 0.5,
  });
  const yScale = scaleLinear<number>({
    domain: [0, 1],
    range: [CHART_HEIGHT - CHART_PADDING.bottom, CHART_PADDING.top],
  });
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const strokeClass = [
    trendStyles.seriesPrimaryStroke ?? "",
    trendStyles.seriesSecondaryStroke ?? "",
  ];

  const labelStride = dates.length > MAX_DENSE_X_LABELS ? 2 : 1;

  return (
    <figure className={abTestStyles.chartCard}>
      <h3 className={abTestStyles.tableTitle}>Tỉ lệ AI xử lý trọn theo ngày</h3>
      <div>
        <svg
          className={abTestStyles.chartSvg}
          viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
          role="img"
          aria-label="Biểu đồ tỉ lệ AI xử lý trọn theo ngày, tách theo model"
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
                {`${Math.round(tick * 100)}%`}
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
    <div>
      <h3 className={abTestStyles.tableTitle}>So sánh 2 model</h3>
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
  const values = [...new Set(rows.map((row) => row.value))];
  const lookup = new Map(rows.map((row) => [`${row.value}|${row.arm}`, row]));

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
      <p className={styles.tableCaption}>
        Nếu 2 model gặp phân bố khác nhau ở thuộc tính này, chênh lệch tổng có
        thể chỉ là do mix chứ không phải do model.
      </p>
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
  const defaultWindow = useMemo(
    () => defaultWindowFromReportScope(selectedReportWeeks, weekDefinition),
    [selectedReportWeeks, weekDefinition],
  );
  const effectiveWindow = override ?? defaultWindow;
  const startIso = toIsoWithOffset(effectiveWindow.start);
  const endIso = toIsoWithOffset(effectiveWindow.end);

  const query = useQuery({
    queryKey: ["ab-test", startIso, endIso],
    enabled: open,
    retry: false,
    queryFn: async ({ signal }) => {
      const parsed = parseAbTestSnapshot(
        await fetchAbTest(startIso, endIso, signal),
      );
      if (!parsed.ok) {
        throw new Error(parsed.message);
      }
      return parsed.data;
    },
  });

  const data = query.data;
  const arms = useMemo(
    () => (data ? data.arms.map((arm) => arm.arm) : []),
    [data],
  );
  const rows = useMemo(() => (data ? buildMetricRows(data.arms) : []), [data]);
  const series = useMemo(
    () => (data ? dailyRateSeries(data, arms) : null),
    [data, arms],
  );

  return (
    <section
      id="ab-test"
      className={styles.section}
      aria-labelledby="ab-test-title"
    >
      <div className={styles.sectionHead}>
        <h2 id="ab-test-title" className={styles.sectionTitle}>
          AB Test model
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
                  end: override?.end ?? defaultWindow.end,
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
                  start: override?.start ?? defaultWindow.start,
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
                start: override?.start ?? defaultWindow.start,
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
              Dùng lại Phạm vi báo cáo
            </button>
          ) : null}
        </div>
      </details>

      {query.isLoading ? (
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
              {`${formatCount(data.total_tickets)} ticket · ${effectiveWindow.start.replace("T", " ")} → ${effectiveWindow.end.replace("T", " ")}`}
              {override === null ? " · theo Phạm vi báo cáo" : ""}
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
              <DailyRateChart series={series} arms={arms} />
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
