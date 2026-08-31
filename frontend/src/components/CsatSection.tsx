import { useEffect, useMemo, useState } from "react";

import type {
  Csat,
  CsatFeedbackEntry,
  CsatWeek,
  Outcome,
  WeekDefinition,
} from "../lib/dashboard-schema";
import {
  formatCount,
  formatDateRangeLabel,
  formatUpdatedAt,
  formatWeekRange,
  formatWeekStart,
} from "../lib/format";
import type { TicketFilters } from "../lib/dashboard-filters";
import { selectScopeDays } from "../lib/report-scope";
import type { DayRangeScope } from "../lib/report-scope";
import csatStyles from "./csat-section.module.css";
import styles from "./dashboard.module.css";
import {
  CsatBreakdownTable,
  csatBreakdownOptions,
  csatGroupingLabel,
  CsatGroupingField,
  type CsatGrouping,
} from "./CsatBreakdownTable";
import { CsatCharts } from "./CsatCharts";
import { FreshdeskTicketLink } from "./FreshdeskTicketLink";
import { Pagination } from "./Pagination";
import { SatisfactionBadge } from "./SatisfactionBadge";

const FEEDBACK_PER_PAGE = 10;
const vietnamDateFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Ho_Chi_Minh",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function vietnamDateKey(value: string | number): string | null {
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) {
    return null;
  }
  const parts = Object.fromEntries(
    vietnamDateFormatter
      .formatToParts(parsed)
      .map((part) => [part.type, part.value]),
  );
  return parts.year !== undefined &&
    parts.month !== undefined &&
    parts.day !== undefined
    ? `${parts.year}-${parts.month}-${parts.day}`
    : null;
}

function aggregateWeeks(weeks: readonly CsatWeek[]): CsatWeek | null {
  if (weeks.length === 0) {
    return null;
  }

  const counts = weeks.reduce(
    (total, week) => ({
      response_count: total.response_count + week.response_count,
      ticket_count: total.ticket_count + week.ticket_count,
      positive: total.positive + week.positive,
      neutral: total.neutral + week.neutral,
      negative: total.negative + week.negative,
    }),
    {
      response_count: 0,
      ticket_count: 0,
      positive: 0,
      neutral: 0,
      negative: 0,
    },
  );

  const outcomes: readonly Outcome[] = [
    "ai_end_to_end",
    "ai_then_cs",
    "direct_cs",
    "unclassified",
  ];
  const byOutcome = Object.fromEntries(
    outcomes.map((outcome) => [
      outcome,
      weeks.reduce(
        (total, week) => ({
          ticket_count: total.ticket_count + week.by_outcome[outcome].ticket_count,
          positive: total.positive + week.by_outcome[outcome].positive,
          neutral: total.neutral + week.by_outcome[outcome].neutral,
          negative: total.negative + week.by_outcome[outcome].negative,
        }),
        { ticket_count: 0, positive: 0, neutral: 0, negative: 0 },
      ),
    ]),
  ) as CsatWeek["by_outcome"];
  const responseByOutcome = Object.fromEntries(
    outcomes.map((outcome) => [
      outcome,
      weeks.reduce(
        (total, week) => {
          const source = week.response_by_outcome?.[outcome] ?? week.by_outcome[outcome];
          return {
            ticket_count: total.ticket_count + source.ticket_count,
            positive: total.positive + source.positive,
            neutral: total.neutral + source.neutral,
            negative: total.negative + source.negative,
          };
        },
        { ticket_count: 0, positive: 0, neutral: 0, negative: 0 },
      ),
    ]),
  ) as CsatWeek["by_outcome"];
  const aggregateDimension = (
    dimension: keyof CsatWeek["by_dimension"],
    responseGrain = false,
  ): CsatWeek["by_dimension"][typeof dimension] => {
    const byValue = new Map<
      string,
      { value: string; ticket_count: number; positive: number; neutral: number; negative: number }
    >();
    for (const week of weeks) {
      const source = responseGrain
        ? week.response_by_dimension?.[dimension] ?? week.by_dimension[dimension]
        : week.by_dimension[dimension];
      for (const row of source) {
        const current = byValue.get(row.value) ?? {
          value: row.value,
          ticket_count: 0,
          positive: 0,
          neutral: 0,
          negative: 0,
        };
        byValue.set(row.value, {
          value: row.value,
          ticket_count: current.ticket_count + row.ticket_count,
          positive: current.positive + row.positive,
          neutral: current.neutral + row.neutral,
          negative: current.negative + row.negative,
        });
      }
    }
    return [...byValue.values()].sort(
      (left, right) =>
        right.ticket_count - left.ticket_count ||
        left.value.localeCompare(right.value, "vi"),
    );
  };

  return {
    ...counts,
    by_outcome: byOutcome,
    by_dimension: {
      skill: aggregateDimension("skill"),
      issue_category: aggregateDimension("issue_category"),
    },
    response_by_outcome: responseByOutcome,
    response_by_dimension: {
      skill: aggregateDimension("skill", true),
      issue_category: aggregateDimension("issue_category", true),
    },
    feedback_entries: weeks.flatMap((week) => week.feedback_entries),
  };
}

function selectCsatScope(
  csat: Csat,
  effectiveWeek: string,
  scopeWeeks?: readonly string[],
  scopeDays?: readonly string[] | null,
): CsatWeek | null {
  if (scopeDays != null) {
    return aggregateWeeks(
      scopeDays
        .map((day) => csat.by_day?.[day])
        .filter((day): day is CsatWeek => day !== undefined),
    );
  }
  if (scopeWeeks !== undefined) {
    return aggregateWeeks(
      scopeWeeks
        .map((week) => csat.by_week[week])
        .filter((week): week is CsatWeek => week !== undefined),
    );
  }
  if (effectiveWeek !== "") {
    return csat.by_week[effectiveWeek] ?? null;
  }
  return aggregateWeeks(Object.values(csat.by_week));
}

interface FeedbackWithBucket extends CsatFeedbackEntry {
  readonly bucketKey: string;
}

function FeedbackDisclosure({
  buckets,
  defaultBucketFilter,
  bucketFieldLabel,
  allBucketsLabel,
  formatBucketOption,
  data,
  grouping,
  activeValue,
  onActiveValueChange,
}: {
  /** The scope's buckets, keyed by cohort week or by cohort day. */
  readonly buckets: readonly (readonly [string, CsatWeek])[];
  readonly defaultBucketFilter: string;
  readonly bucketFieldLabel: string;
  readonly allBucketsLabel: string;
  readonly formatBucketOption: (key: string) => string;
  readonly data: CsatWeek;
  readonly grouping: CsatGrouping;
  readonly activeValue: string;
  readonly onActiveValueChange: (value: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [satisfactionFilter, setSatisfactionFilter] = useState<
    "all" | CsatFeedbackEntry["satisfaction_bucket"]
  >("all");
  const [weekFilter, setWeekFilter] = useState(defaultBucketFilter);
  const [timeSort, setTimeSort] = useState<"newest" | "oldest">("newest");
  const [page, setPage] = useState(1);
  const groupOptions = useMemo(
    () => csatBreakdownOptions(data, grouping),
    [data, grouping],
  );
  const feedback = useMemo<FeedbackWithBucket[]>(
    () =>
      buckets.flatMap(([bucketKey, bucket]) =>
        bucket.feedback_entries.map((comment) => ({ ...comment, bucketKey })),
      ),
    [buckets],
  );
  const availableWeeks = useMemo(
    () =>
      buckets
        .filter(([, bucket]) => bucket.feedback_entries.length > 0)
        .map(([bucketKey]) => bucketKey)
        .sort((left, right) => right.localeCompare(left)),
    [buckets],
  );
  const filteredComments = useMemo(
    () =>
      feedback
        .filter(
          (comment) =>
            (weekFilter === "all" || comment.bucketKey === weekFilter) &&
            (satisfactionFilter === "all" ||
              comment.satisfaction_bucket === satisfactionFilter),
        )
        .filter(
          (entry) => activeValue === "" || entry[grouping] === activeValue,
        )
        .sort((left, right) => {
          const order =
            Date.parse(left.responded_at) - Date.parse(right.responded_at);
          return timeSort === "oldest" ? order : -order;
        }),
    [activeValue, feedback, grouping, satisfactionFilter, timeSort, weekFilter],
  );
  useEffect(() => {
    setPage(1);
  }, [activeValue, grouping]);
  const pageCount = Math.ceil(filteredComments.length / FEEDBACK_PER_PAGE);
  const currentPage = Math.min(page, Math.max(1, pageCount));
  const pageStart = (currentPage - 1) * FEEDBACK_PER_PAGE;
  const visibleComments = filteredComments.slice(
    pageStart,
    pageStart + FEEDBACK_PER_PAGE,
  );

  const changePage = (nextPage: number) => {
    setPage(nextPage);
  };

  if (feedback.length === 0) {
    return null;
  }

  const count = formatCount(filteredComments.length);
  const disclosureLabel = `${expanded ? "Ẩn" : "Xem"} ${count} nội dung phản hồi`;

  return (
    <div className={csatStyles.commentDisclosure}>
      <button
        type="button"
        className={styles.action}
        aria-expanded={expanded}
        aria-controls="csat-comments"
        onClick={() => setExpanded((current) => !current)}
      >
        {disclosureLabel}
      </button>
      {expanded ? (
        <div id="csat-comments" className={csatStyles.commentPanel}>
          <div className={csatStyles.commentControls}>
            <label
              className={csatStyles.commentField}
              htmlFor="csatCommentGroupingInput"
            >
              <span>{`Lọc nội dung theo ${csatGroupingLabel(grouping)}`}</span>
              <select
                id="csatCommentGroupingInput"
                value={activeValue}
                onChange={(event) => {
                  onActiveValueChange(event.target.value);
                  setPage(1);
                }}
              >
                <option value="">Tất cả</option>
                {groupOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label
              className={csatStyles.commentField}
              htmlFor="csatCommentWeekInput"
            >
              <span>{bucketFieldLabel}</span>
              <select
                id="csatCommentWeekInput"
                value={weekFilter}
                onChange={(event) => {
                  setWeekFilter(event.target.value);
                  setPage(1);
                }}
              >
                <option value="all">{allBucketsLabel}</option>
                {availableWeeks.map((bucketKey) => (
                  <option key={bucketKey} value={bucketKey}>
                    {formatBucketOption(bucketKey)}
                  </option>
                ))}
              </select>
            </label>
            <label
              className={csatStyles.commentField}
              htmlFor="csatCommentSatisfactionInput"
            >
              <span>Mức hài lòng</span>
              <select
                id="csatCommentSatisfactionInput"
                value={satisfactionFilter}
                onChange={(event) => {
                  setSatisfactionFilter(
                    event.target.value as
                      | "all"
                      | CsatFeedbackEntry["satisfaction_bucket"],
                  );
                  setPage(1);
                }}
              >
                <option value="all">Tất cả mức</option>
                <option value="positive">Rất hài lòng</option>
                <option value="neutral">Bình thường</option>
                <option value="negative">Rất tệ</option>
              </select>
            </label>
            <label
              className={csatStyles.commentField}
              htmlFor="csatCommentSortInput"
            >
              <span>Sắp xếp thời gian</span>
              <select
                id="csatCommentSortInput"
                value={timeSort}
                onChange={(event) => {
                  setTimeSort(event.target.value as "newest" | "oldest");
                  setPage(1);
                }}
              >
                <option value="newest">Mới nhất trước</option>
                <option value="oldest">Cũ nhất trước</option>
              </select>
            </label>
          </div>
          <p
            className={csatStyles.commentResultCount}
            aria-live="polite"
          >
            {filteredComments.length === 0
              ? "Không có nội dung phản hồi phù hợp."
              : `Hiển thị ${formatCount(pageStart + 1)}–${formatCount(
                  pageStart + visibleComments.length,
                )} / ${formatCount(filteredComments.length)} nội dung phản hồi`}
          </p>
          {visibleComments.length > 0 ? (
            <ul className={csatStyles.commentList}>
              {visibleComments.map((comment, index) => (
                <li
                  key={`${comment.ticket_id}-${comment.responded_at}-${pageStart + index}`}
                  className={csatStyles.commentItem}
                >
                  <p className={csatStyles.commentMeta}>
                    Ticket{" "}
                    <FreshdeskTicketLink
                      ticketId={comment.ticket_id}
                      className={csatStyles.ticketLink}
                    />{" "}
                    · <SatisfactionBadge value={comment.satisfaction_bucket} /> ·{" "}
                    <time dateTime={comment.responded_at}>
                      {formatUpdatedAt(comment.responded_at)}
                    </time>
                    {comment.response_total > 1 ? (
                      <>
                        {" · "}
                        <span className={csatStyles.responseSequence}>
                          {`Lần ${formatCount(comment.response_number)}/${formatCount(
                          comment.response_total,
                        )}${comment.is_latest_for_ticket ? " · Mới nhất" : ""}`}
                        </span>
                      </>
                    ) : null}
                  </p>
                  <p className={csatStyles.commentText}>{comment.text}</p>
                </li>
              ))}
            </ul>
          ) : null}
          <Pagination
            currentPage={currentPage}
            pageCount={pageCount}
            onPageChange={changePage}
            ariaLabel="Phân trang nội dung phản hồi CSAT"
          />
        </div>
      ) : null}
    </div>
  );
}

export interface CsatSectionProps {
  readonly csat: Csat | null;
  readonly effectiveWeek: string;
  readonly weekDefinition: WeekDefinition;
  readonly activeBreakdownFilters: Pick<
    TicketFilters,
    "outcome" | "skill" | "issue_category"
  >;
  readonly onBreakdownSelect: (
    grouping: CsatGrouping,
    value: string,
  ) => void;
  readonly onBreakdownRowSelect: (
    grouping: CsatGrouping,
    value: string,
  ) => void;
  readonly onBreakdownGroupingChange: () => void;
  readonly freshdeskCookieState?: "ok" | "expired" | "missing" | null;
  readonly onOpenFreshdeskCookieDialog?: () => void;
  /**
   * Day-range mode: the full weeks the picked day range touches. Used only
   * as the fallback for a snapshot that predates day-grain CSAT; when the
   * snapshot carries `by_day`, `dayRange` cuts to the exact days instead.
   */
  readonly scopeWeeks?: readonly string[];
  /**
   * Day-range mode: the inclusive range the reader actually picked. CSAT is
   * cut to exactly these days, matching every other metric on the page.
   */
  readonly dayRange?: DayRangeScope;
}

/** Bot-only Freshdesk satisfaction, kept separate from Langfuse metrics. */
export function CsatSection({
  csat,
  effectiveWeek,
  weekDefinition,
  activeBreakdownFilters,
  onBreakdownSelect,
  onBreakdownRowSelect,
  onBreakdownGroupingChange,
  freshdeskCookieState = null,
  onOpenFreshdeskCookieDialog = () => {},
  scopeWeeks,
  dayRange,
}: CsatSectionProps) {
  const [grouping, setGrouping] = useState<CsatGrouping>("outcome");
  const activeValue = activeBreakdownFilters[grouping];
  const scopeDays = useMemo(
    () =>
      csat === null || dayRange === undefined
        ? null
        : selectScopeDays(csat.by_day, dayRange),
    [csat, dayRange],
  );
  const data = useMemo(
    () =>
      csat === null
        ? null
        : selectCsatScope(csat, effectiveWeek, scopeWeeks, scopeDays),
    [csat, effectiveWeek, scopeDays, scopeWeeks],
  );
  /** The buckets behind `data`, so the comment list can never drift from it. */
  const scopedBuckets = useMemo<readonly (readonly [string, CsatWeek])[]>(() => {
    if (csat === null) {
      return [];
    }
    const pick = (
      keys: readonly string[],
      source: Readonly<Record<string, CsatWeek>>,
    ) =>
      keys.flatMap((key) => {
        const bucket = source[key];
        return bucket === undefined ? [] : [[key, bucket] as const];
      });
    if (scopeDays != null) {
      return pick(scopeDays, csat.by_day ?? {});
    }
    if (scopeWeeks !== undefined) {
      return pick(scopeWeeks, csat.by_week);
    }
    if (effectiveWeek !== "") {
      return pick([effectiveWeek], csat.by_week);
    }
    return Object.entries(csat.by_week);
  }, [csat, effectiveWeek, scopeDays, scopeWeeks]);
  const stale =
    csat !== null &&
    vietnamDateKey(csat.fetched_at) !== vietnamDateKey(Date.now());
  const dayGrain = scopeDays != null;
  const scopeLabel =
    dayGrain && dayRange !== undefined
      ? scopeDays.length === 0
        ? "Không có ticket nào có CSAT trong khoảng ngày đã chọn."
        : `Phạm vi CSAT: ${formatDateRangeLabel(
            dayRange.from,
            dayRange.to,
          )} · đúng khoảng ngày đã chọn`
      : scopeWeeks !== undefined
        ? scopeWeeks.length === 0
          ? "Khoảng ngày đã chọn không chạm tuần nào có dữ liệu CSAT."
          : `CSAT theo tuần trọn vẹn chạm khoảng ngày: ${scopeWeeks
              .map((week) => formatWeekRange(week, weekDefinition))
              .join(", ")}. Bản dữ liệu này chưa có CSAT theo ngày.`
        : effectiveWeek === ""
          ? "Phạm vi CSAT: Toàn kỳ · cộng các tuần đã có dữ liệu"
          : `Phạm vi CSAT: Tuần ${formatWeekRange(effectiveWeek, weekDefinition)}`;

  return (
    <section
      id="csat"
      className={styles.section}
      aria-labelledby="csat-title"
    >
      <div className={styles.sectionHead}>
        <div>
          <h2 id="csat-title" className={styles.sectionTitle}>
            Khách hài lòng tới đâu
          </h2>
        </div>
      </div>
      <p
        id="csat-scope"
        className={scopeWeeks !== undefined ? undefined : "visually-hidden"}
      >
        {scopeLabel}
      </p>

      {csat === null ? (
        <div className={csatStyles.empty}>
          <p>
            {freshdeskCookieState === "expired"
              ? "Cookie Freshdesk đã hết hạn — CSAT đã dừng cập nhật."
              : freshdeskCookieState === null
                ? "Chưa đọc được trạng thái cookie Freshdesk."
                : "Chưa kết nối Freshdesk. Cần cookie để lấy dữ liệu CSAT."}
          </p>
          {freshdeskCookieState !== "ok" ? (
            <div className={csatStyles.emptyActions}>
              <button
                type="button"
                className={styles.action}
                onClick={onOpenFreshdeskCookieDialog}
              >
                {freshdeskCookieState === "expired"
                  ? "Cập nhật cookie"
                  : "Kết nối Freshdesk"}
              </button>
            </div>
          ) : null}
        </div>
      ) : data === null ? (
        <p className={csatStyles.empty}>
          {effectiveWeek === ""
            ? "Chưa có dữ liệu CSAT Freshdesk trong toàn kỳ."
            : "Chưa có dữ liệu CSAT Freshdesk cho tuần này."}
        </p>
      ) : (
        <>
          <CsatGroupingField
            grouping={grouping}
            onGroupingChange={(nextGrouping) => {
              setGrouping(nextGrouping);
              onBreakdownGroupingChange();
            }}
          />
          <CsatCharts
            data={data}
            buckets={scopedBuckets}
            grouping={grouping}
            dayGrain={dayGrain}
            weekDefinition={weekDefinition}
          />
          <CsatBreakdownTable
            data={data}
            grouping={grouping}
            scopeKey={effectiveWeek}
            onValueSelect={onBreakdownRowSelect}
          />
          <FeedbackDisclosure
            key={`${dayGrain ? `${dayRange?.from}:${dayRange?.to}` : effectiveWeek}:${csat.fetched_at}`}
            buckets={scopedBuckets}
            defaultBucketFilter={
              !dayGrain && scopeWeeks === undefined && effectiveWeek !== ""
                ? effectiveWeek
                : "all"
            }
            bucketFieldLabel={dayGrain ? "Ngày mở ticket" : "Tuần mở ticket"}
            allBucketsLabel={dayGrain ? "Tất cả ngày" : "Tất cả tuần"}
            formatBucketOption={(key) =>
              dayGrain
                ? `Ngày ${formatWeekStart(key)}`
                : `Tuần ${formatWeekRange(key, weekDefinition)}`
            }
            data={data}
            grouping={grouping}
            activeValue={activeValue}
            onActiveValueChange={(value) => onBreakdownSelect(grouping, value)}
          />
        </>
      )}

      {csat === null ? null : (
        <p id="csat-source" className={csatStyles.source}>
          CSAT: Freshdesk · chỉ Admin CS ZaloPay · cập nhật{" "}
          <time dateTime={csat.fetched_at}>
            {formatUpdatedAt(csat.fetched_at)}
          </time>
          {stale ? (
            <>
              {" · "}
              <strong className={csatStyles.staleInline}>
                Chưa cập nhật hôm nay.
              </strong>
            </>
          ) : (
            "."
          )}
        </p>
      )}
    </section>
  );
}
