import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { useState, type ComponentProps, type ReactElement } from "react";

import { dashboardEnvelopeFixture } from "./fixtures/dashboard";
import { server } from "./msw/server";
import {
  DashboardEnvelopeSchema,
  type DashboardSnapshot,
  type DayAggregate,
  type EntryCoverage,
  type EntryCoverageWeek,
  type Segments,
  type WeeklyReportRow,
} from "../src/lib/dashboard-schema";
import { EMPTY_TICKET_FILTERS, type TicketFilters } from "../src/lib/dashboard-filters";
import { multiSelectSummaryText, toggleMultiSelectOption } from "./multi-select";
import { WEEKLY_EXPORT_COLUMNS } from "../src/lib/weekly-export";
import {
  selectAttentionItems,
  selectLatestWeek,
  selectPreviousWeek,
  selectView,
} from "../src/lib/selectors";
import { TICKET_COLUMN_STORAGE_KEY } from "../src/lib/ticket-columns";
import { BelowFold } from "../src/components/BelowFold";
import {
  TicketExplorer,
  TicketIdentifier,
} from "../src/components/TicketExplorer";
import { WeeklyReport } from "../src/components/WeeklyReport";

const baseSnapshot = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture)
  .snapshot as DashboardSnapshot;

type CsatPayload = NonNullable<
  DashboardSnapshot["views"]["mon_sun"]["csat"]
>;
type CsatWeek = CsatPayload["by_week"][string];

function weekRow(
  overrides: Partial<WeeklyReportRow> & Pick<WeeklyReportRow, "cohort_week">,
): WeeklyReportRow {
  const template = baseSnapshot.views.mon_sun.weekly[0] as WeeklyReportRow;
  return { ...template, ...overrides };
}

/** Builds a snapshot whose `mon_sun` weekly rows are exactly `weeks`. */
function snapshotWithWeeks(weeks: readonly WeeklyReportRow[]): DashboardSnapshot {
  return {
    ...baseSnapshot,
    views: {
      ...baseSnapshot.views,
      mon_sun: { ...baseSnapshot.views.mon_sun, weekly: [...weeks] },
    },
  };
}

function snapshotWithActiveSkillBuckets(
  skill: Segments["skill"],
): DashboardSnapshot {
  return snapshotWithActiveSegmentBuckets("skill", skill);
}

type DisplaySegmentDimension =
  | "issue_category"
  | "app"
  | "product_code"
  | "skill"
  | "intent";

function snapshotWithActiveSegmentBuckets(
  dimension: DisplaySegmentDimension,
  buckets: Segments[DisplaySegmentDimension],
): DashboardSnapshot {
  const view = baseSnapshot.views.mon_sun;
  const detail = view.by_week["2026-07-20"];
  if (detail === undefined) {
    throw new Error("fixture must include the active week");
  }
  return {
    ...baseSnapshot,
    coverage: { ...baseSnapshot.coverage, skill: 1 },
    views: {
      ...baseSnapshot.views,
      mon_sun: {
        ...view,
        by_week: {
          ...view.by_week,
          "2026-07-20": {
            ...detail,
            segments: {
              ...detail.segments,
              [dimension]: buckets,
            },
          },
        },
      },
    },
  };
}

function csatWeek(overrides: Partial<CsatWeek> = {}): CsatWeek {
  const positive = overrides.positive ?? 23;
  const neutral = overrides.neutral ?? 4;
  const negative = overrides.negative ?? 4;
  const ticketCount = overrides.ticket_count ?? positive + neutral + negative;
  const counts = { ticket_count: ticketCount, positive, neutral, negative };
  return {
    response_count: overrides.response_count ?? ticketCount,
    ticket_count: ticketCount,
    positive,
    neutral,
    negative,
    by_outcome: {
      ai_end_to_end: counts,
      ai_then_cs: { ticket_count: 0, positive: 0, neutral: 0, negative: 0 },
      direct_cs: { ticket_count: 0, positive: 0, neutral: 0, negative: 0 },
      unclassified: { ticket_count: 0, positive: 0, neutral: 0, negative: 0 },
    },
    by_dimension: {
      skill: [{ value: "interbank-fund-transfer", ...counts }],
      issue_category: [{ value: "Chuyển tiền", ...counts }],
    },
    feedback_entries: [],
    ...overrides,
  };
}

function csatComments(count: number): CsatWeek["feedback_entries"] {
  const buckets = ["positive", "neutral", "negative"] as const;
  return Array.from({ length: count }, (_, index) => ({
    ticket_id: String(7_000_000 + index + 1),
    responded_at: new Date(Date.UTC(2026, 6, 1, index)).toISOString(),
    satisfaction_bucket: buckets[index % buckets.length] ?? "neutral",
    outcome: "ai_end_to_end" as const,
    skill: "interbank-fund-transfer",
    issue_category: "Chuyển tiền",
    text: `Nội dung phản hồi ${index + 1}`,
    response_number: 1,
    response_total: 1,
    is_latest_for_ticket: true,
  }));
}

function snapshotWithCsat(
  byWeek: CsatPayload["by_week"],
  fetchedAt = new Date(Date.now() - 60 * 60 * 1_000).toISOString(),
  byDay?: CsatPayload["by_day"],
): DashboardSnapshot {
  const view = baseSnapshot.views.mon_sun;
  const currentWeek = view.weekly[0];
  const detail = view.by_week["2026-07-20"];
  if (currentWeek === undefined || detail === undefined) {
    throw new Error("fixture must include the current week and its detail");
  }
  return {
    ...baseSnapshot,
    views: {
      ...baseSnapshot.views,
      mon_sun: {
        ...view,
        weekly: [
          { ...currentWeek, cohort_week: "2026-07-13" },
          currentWeek,
        ],
        by_week: {
          "2026-07-13": detail,
          "2026-07-20": detail,
        },
        csat: {
          source: "freshdesk",
          fetched_at: fetchedAt,
          by_week: byWeek,
          ...(byDay === undefined ? {} : { by_day: byDay }),
        },
      },
    },
  };
}

const EMPTY_DAY_TRANSFER_REASONS: DayAggregate["transfer_reasons"] = {
  observed_transfer_denominator: 0,
  triggers: [],
  step_result_missing: { count: 0, denominator: 0 },
  tpe: [],
  guardrail: [],
  escalation_guard_blocked: { count: 0, denominator: 0 },
};

function dayAggregate(day: string): DayAggregate {
  return {
    day,
    total_tickets: 5,
    ai_first_count: 3,
    transferred_count: 2,
    direct_cs_count: 0,
    outcomes: { ai_end_to_end: 3, ai_then_cs: 2, direct_cs: 0, unclassified: 0 },
    reopen_lifetime_numerator: 0,
    reopen_lifetime_denominator: 5,
    gt4_turn_with_cs: 0,
    gt4_turn_without_cs: 0,
    resolved_first_reply_count: 3,
    ai_reply_sum_ai_first: 3,
    segments: { skill: {}, app: {}, issue_category: {} },
    transfer_reasons: EMPTY_DAY_TRANSFER_REASONS,
  };
}

function coverageBucket(
  overrides: Partial<EntryCoverageWeek> = {},
): EntryCoverageWeek {
  return {
    freshdesk_ticket_count: 4,
    ai_replied_only: 1,
    ai_replied_then_transferred: 0,
    transferred_without_ai_reply: 0,
    invoked_no_result: 1,
    not_observed_invoked: 2,
    not_observed_human_replied: 1,
    not_observed_no_human_reply: 1,
    unresolved: 0,
    ...overrides,
  };
}

function snapshotWithEntryCoverage(
  byDay?: EntryCoverage["by_day"],
): DashboardSnapshot {
  const view = baseSnapshot.views.mon_sun;
  return {
    ...baseSnapshot,
    views: {
      ...baseSnapshot.views,
      mon_sun: {
        ...view,
        entry_coverage: {
          source: "freshdesk",
          source_start_week: "2026-07-06",
          fetched_at: "2026-08-04T03:00:00Z",
          by_week: { "2026-07-20": coverageBucket() },
          ...(byDay === undefined ? {} : { by_day: byDay }),
        },
      },
    },
  };
}

function renderWithQuery(element: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{element}</QueryClientProvider>);
}

function captureDownload(): { text: () => Promise<string> } {
  const captured: Blob[] = [];
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: (blob: Blob) => {
      captured.push(blob);
      return "blob:captured-csat-test";
    },
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: () => {},
  });
  return {
    text: async () => {
      const blob = captured.at(-1);
      return blob === undefined
        ? ""
        : new TextDecoder("utf-8", { ignoreBOM: true }).decode(
            await blob.arrayBuffer(),
          );
    },
  };
}

function belowFold(
  snapshot: DashboardSnapshot,
  overrides: Partial<ComponentProps<typeof BelowFold>> = {},
) {
  return (
    <BelowFold
      snapshot={snapshot}
      weekDefinition="mon_sun"
      activeWeek=""
      onWeekSelect={() => {}}
      onSegmentSelect={() => {}}
      activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
      onCsatBreakdownSelect={() => {}}
      onCsatBreakdownGroupingChange={() => {}}
      {...overrides}
    />
  );
}

describe("Weekly Report", () => {
  it("groups the decision-useful screen columns by ticket flow and never turns an empty week into zero", async () => {
    const user = userEvent.setup();
    const snapshot = snapshotWithWeeks([
      weekRow({
        cohort_week: "2026-07-13",
        has_data: false,
        total_tickets: 0,
        ai_first_count: 0,
        ai_first_rate: 0,
        ai_end_to_end_count: 0,
        ai_then_cs_count: 0,
        direct_cs_count: 0,
        unclassified_count: 0,
      }),
      weekRow({ cohort_week: "2026-07-20", cohort_status: "wtd" }),
    ]);

    renderWithQuery(<WeeklyReport snapshot={snapshot} weekDefinition="mon_sun" />);

    const table = screen.getByRole("table", { name: /Báo cáo tuần/ });
    expect(
      screen.getByRole("region", {
        name: /Báo cáo tuần T2–CN · cập nhật/,
      }),
    ).toBeVisible();
    const firstResponseGroup = within(table).getByRole("columnheader", {
      name: "Phản hồi đầu tiên",
    });
    const aiFirstGroup = within(table).getByRole("columnheader", {
      name: "Sau AI First",
    });
    const outcomeGroup = within(table).getByRole("columnheader", {
      name: "Kết quả xử lý",
    });
    expect(firstResponseGroup).toHaveAttribute("colspan", "3");
    expect(aiFirstGroup).toHaveAttribute("colspan", "2");
    expect(outcomeGroup).toHaveAttribute("colspan", "6");

    const sortableHeaders = within(table)
      .getAllByRole("button", { name: /Sắp xếp theo/ })
      .map((button) => button.textContent);
    expect(sortableHeaders).toEqual([
      "Tuần",
      "Tổng ticket",
      "AI First",
      "Tỷ lệ AI First",
      "Chuyển CS ngay từ đầu",
      "AI xử lý trọn",
      "AI trả lời rồi chuyển CS",
      "Tổng chuyển CS",
      "Reopen sau AI First",
      "Tỷ lệ reopen",
      "AI phản hồi/ticket TB",
      ">3 lượt xử lý + CS",
      ">3 lượt xử lý chưa chuyển",
    ]);

    // Weeks without data collapse behind an explicit toggle by default, so a
    // 13-row table does not read as 62% empty on first paint.
    expect(within(table).queryByText("Không có dữ liệu")).toBeNull();
    await user.click(
      screen.getByRole("button", { name: "+ 1 tuần không có dữ liệu" }),
    );
    expect(within(table).getByText("Không có dữ liệu")).toBeVisible();
    expect(
      within(table).getByRole("rowheader", { name: "20/07–26/07 (WTD)" }),
    ).toBeVisible();
    expect(within(table).getAllByRole("rowheader")[0]).toHaveTextContent(
      "20/07–26/07 (WTD)",
    );
  });

  it("highlights the current T2–T6 row even after that cohort is complete", () => {
    const view = baseSnapshot.views.mon_fri;
    const snapshot: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        ...baseSnapshot.views,
        mon_fri: {
          ...view,
          weekly: [
            weekRow({ cohort_week: "2026-07-13", cohort_status: "complete" }),
            weekRow({ cohort_week: "2026-07-20", cohort_status: "complete" }),
          ],
        },
      },
    };

    renderWithQuery(<WeeklyReport snapshot={snapshot} weekDefinition="mon_fri" />);

    const currentRow = screen
      .getByRole("rowheader", { name: "20/07–24/07" })
      .closest("tr");
    const previousRow = screen
      .getByRole("rowheader", { name: "13/07–17/07" })
      .closest("tr");
    expect(currentRow).toHaveAttribute("data-current-week", "true");
    expect(
      within(currentRow as HTMLTableRowElement).getByRole("rowheader"),
    ).toHaveAttribute("aria-current", "date");
    expect(previousRow).not.toHaveAttribute("data-current-week");
  });

  it("keeps every reordered screen header aligned with its metric value", () => {
    const snapshot = snapshotWithWeeks([
      weekRow({
        cohort_week: "2026-07-20",
        total_tickets: 1_000,
        ai_first_count: 700,
        ai_first_rate: 0.7,
        direct_cs_count: 211,
        unclassified_count: 89,
        ai_end_to_end_count: 601,
        ai_then_cs_count: 99,
        reopen_lifetime_numerator: 33,
        reopen_lifetime_rate: 0.047,
        ai_reply_mean_ai_first: 1.23,
        gt4_turn_with_cs: 17,
        gt4_turn_without_cs: 19,
      }),
    ]);

    renderWithQuery(<WeeklyReport snapshot={snapshot} weekDefinition="mon_sun" />);

    const row = screen.getByRole("rowheader", { name: "20/07–26/07" }).closest("tr");
    expect(row).not.toBeNull();
    expect(
      within(row as HTMLTableRowElement)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual([
      "1.000",
      "700",
      "70,0%",
      "211",
      "601",
      "99",
      "310",
      "33",
      "4,7%",
      "1,23",
      "17",
      "19",
    ]);
  });

  it("copies the rendered newest-first table as a header-first 14-column TSV", async () => {
    const user = userEvent.setup();
    const snapshot = snapshotWithWeeks([
      weekRow({ cohort_week: "2026-07-13" }),
      weekRow({ cohort_week: "2026-07-20", cohort_status: "wtd" }),
    ]);
    renderWithQuery(<WeeklyReport snapshot={snapshot} weekDefinition="mon_sun" />);

    const table = screen.getByRole("table", { name: /Báo cáo tuần/ });
    const renderedWeeks = within(table)
      .getAllByRole("rowheader")
      .map((cell) => cell.textContent);

    await user.click(screen.getByRole("button", { name: "Chép TSV" }));

    const copiedLines = (await navigator.clipboard.readText()).split("\n");
    expect(copiedLines[0]?.split("\t")).toEqual([...WEEKLY_EXPORT_COLUMNS]);
    expect(copiedLines.every((line) => line.split("\t").length === 14)).toBe(true);
    expect(copiedLines.slice(1).map((line) => line.split("\t")[0])).toEqual(
      renderedWeeks,
    );
  });

  it("exposes the full column set through an explicit control", async () => {
    const user = userEvent.setup();
    renderWithQuery(<WeeklyReport snapshot={baseSnapshot} weekDefinition="mon_sun" />);

    const toggle = screen.getByRole("button", { name: "Xem đủ cột" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Rút gọn cột" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("keeps CSAT comments out of the governed 14-column TSV and CSV", async () => {
    const privateComment = "COMMENT_DO_NOT_EXPORT_6991254";
    const snapshot = snapshotWithCsat({
      "2026-07-20": csatWeek({
        feedback_entries: [
          {
            ticket_id: "6991254",
            responded_at: "2026-07-20T01:00:00Z",
            satisfaction_bucket: "positive",
            outcome: "ai_end_to_end",
            skill: "interbank-fund-transfer",
            issue_category: "Chuyển tiền",
            text: privateComment,
            response_number: 1,
            response_total: 1,
            is_latest_for_ticket: true,
          },
        ],
      }),
    });
    const download = captureDownload();
    const user = userEvent.setup();

    renderWithQuery(
      <WeeklyReport snapshot={snapshot} weekDefinition="mon_sun" />,
    );
    await user.click(screen.getByRole("button", { name: "Chép TSV" }));
    const tsv = await navigator.clipboard.readText();
    await user.click(screen.getByRole("button", { name: "Tải CSV" }));
    const csv = await download.text();

    expect(tsv).not.toContain(privateComment);
    expect(csv).not.toContain(privateComment);
    expect(tsv.split("\n").every((line) => line.split("\t").length === 14)).toBe(
      true,
    );
    expect(
      csv
        .slice(1)
        .split("\r\n")
        .every((line) => (line.match(/"(?:[^"]|"")*"/g) ?? []).length === 14),
    ).toBe(true);
  });
});

describe("Below-fold analysis", () => {
  it("shows Freshdesk entry coverage separately and opens a paginated investigation list", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/freshdesk-entry-coverage/tickets", () =>
        HttpResponse.json({
          items: [
            {
              ticket_id: "7043723",
              opened_at: "2026-07-21T02:00:00Z",
              cohort_week: "2026-07-20",
              status: "not_observed_invoked",
              human_replied: true,
            },
          ],
          page: 1,
          page_size: 10,
          total: 1,
        }),
      ),
    );

    renderWithQuery(belowFold(snapshotWithEntryCoverage()));

    const section = screen.getByRole("region", {
      name: "Độ phủ xử lý từ Freshdesk",
    });
    expect(within(section).getByText("Không thấy lần gọi CS-agent")).toBeVisible();
    expect(within(section).getByText("Đã gọi nhưng không có phản hồi/chuyển CS")).toBeVisible();
    expect(within(section).getByText("CS người đã phản hồi trực tiếp: 1")).toBeVisible();
    expect(within(section).getAllByRole("button", { name: "Xem ticket" })).toHaveLength(3);

    await user.click(
      within(section).getAllByRole("button", { name: "Xem ticket" })[1]!,
    );
    expect(await within(section).findByRole("table")).toHaveTextContent("7043723");
    expect(within(section).getByText("Trang 1 · 1 ticket")).toBeVisible();
  });

  it("refuses to draw a trend from a single observed week", () => {
    renderWithQuery(belowFold(baseSnapshot));

    expect(
      screen.getByText(/Cần ít nhất 2 tuần có dữ liệu mới vẽ được xu hướng/),
    ).toBeVisible();
    expect(screen.queryByRole("img", { name: /Volume ticket theo tuần/ })).toBeNull();
  });

  it("draws aligned week labels and marks WTD in both separate trend charts", () => {
    const snapshot = snapshotWithWeeks([
      weekRow({ cohort_week: "2026-07-06" }),
      weekRow({ cohort_week: "2026-07-13" }),
      weekRow({ cohort_week: "2026-07-20" }),
      weekRow({ cohort_week: "2026-07-27", cohort_status: "wtd" }),
    ]);

    renderWithQuery(belowFold(snapshot));

    const volumeChart = screen.getByRole("img", {
      name: /Volume ticket theo tuần/,
    });
    expect(volumeChart).toBeVisible();
    const rateChart = screen.getByRole("img", {
      name: /Tỷ lệ AI First và reopen theo tuần/,
    });
    expect(rateChart).toHaveAccessibleDescription(/Volume nằm ở biểu đồ phía trên/);
    expect(within(volumeChart).getByText("06/07")).toBeVisible();
    expect(within(rateChart).getByText("06/07")).toBeVisible();
    expect(within(volumeChart).getByText("27/07 · WTD")).toBeVisible();
    expect(within(rateChart).getByText("27/07 · WTD")).toBeVisible();
  });

  it("filters from a data week by clicking a chart point", async () => {
    const user = userEvent.setup();
    const onWeekSelect = vi.fn();
    const snapshot = snapshotWithWeeks([
      weekRow({ cohort_week: "2026-07-06" }),
      weekRow({ cohort_week: "2026-07-13" }),
      weekRow({ cohort_week: "2026-07-20" }),
    ]);

    renderWithQuery(belowFold(snapshot, { onWeekSelect }));

    const volumeChart = screen.getByRole("img", {
      name: /Volume ticket theo tuần/,
    });
    const pointerTarget = volumeChart.querySelector(
      '[data-week-target="2026-07-13"]',
    );
    expect(pointerTarget).not.toBeNull();
    await user.click(pointerTarget as Element);
    expect(onWeekSelect).toHaveBeenCalledOnce();
    expect(onWeekSelect).toHaveBeenCalledWith("2026-07-13");
  });

  it("test_segments_and_diagnostics_default_to_the_latest_week_not_the_whole_range", () => {
    const mon_sun = baseSnapshot.views.mon_sun;
    // The whole-range total (999) is deliberately far from the latest week's
    // own number (10, already in by_week["2026-07-20"]) so a reader can tell
    // at a glance which one is on screen.
    const snapshot: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        ...baseSnapshot.views,
        mon_sun: {
          ...mon_sun,
          segments: {
            ...mon_sun.segments,
            issue_category: {
              "Thanh toán-IBFT": {
                total: 999,
                ai_first: 500,
                transferred: 100,
                reopen: 50,
              },
            },
          },
        },
      },
    };

    const latestRender = renderWithQuery(belowFold(snapshot));

    // Landing state: nothing explicitly picked yet. Segments already show the
    // latest observed week, matching what the KPI ledger above would show for
    // the same snapshot — not a blended 13-week total the reader never asked
    // for.
    // The week-level total (10) sits below the small-sample threshold (20),
    // so the guard hides the rate and shows the raw count instead; the
    // whole-range total (999) clears it and keeps "count · rate".
    expect(screen.getByText("10")).toBeVisible();
    expect(screen.queryByText("999 · 100%")).toBeNull();
    expect(screen.queryByRole("button", { name: "Xem toàn kỳ" })).toBeNull();

    latestRender.unmount();
    renderWithQuery(belowFold(snapshot, { allWeeks: true }));

    expect(screen.getByText("999 · 100%")).toBeVisible();
    expect(screen.queryByText("10 · 100%")).toBeNull();
  });

  it("renders the CSAT section immediately after segments even when the cache is unavailable", () => {
    renderWithQuery(belowFold(baseSnapshot));

    const segmentSection = document.getElementById("segments");
    const csatSection = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    expect(segmentSection?.nextElementSibling).toBe(csatSection);
    // freshdeskCookieState defaults to null (unknown) here — the section must
    // not assert "not connected" for a state it hasn't actually observed yet
    // (bug #4), and must still offer the connect action since null !== "ok".
    expect(csatSection).toHaveTextContent(
      "Chưa đọc được trạng thái cookie Freshdesk.",
    );
    expect(
      within(csatSection).getByRole("button", { name: "Kết nối Freshdesk" }),
    ).toBeVisible();
    expect(csatSection).not.toHaveTextContent("0 phản hồi");
  });

  it("day-range mode reads CSAT from the real weekly snapshot instead of the day-range placeholder", () => {
    // §3.4 bug #4: the day-range synthetic `snapshot` always carries
    // csat/entry_coverage as null (report-scope.ts), so BelowFold must fall
    // back to `weeklySnapshot` in day mode rather than reporting "not
    // connected" when Freshdesk data actually exists.
    const weeklySnapshot = snapshotWithCsat({ "2026-07-20": csatWeek() });
    const dayRangeSnapshot: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        ...baseSnapshot.views,
        mon_sun: { ...baseSnapshot.views.mon_sun, csat: null, entry_coverage: null },
      },
    };

    renderWithQuery(
      belowFold(dayRangeSnapshot, {
        weeklySnapshot,
        dayRange: {
          from: "2026-07-20",
          to: "2026-07-21",
          allDays: [dayAggregate("2026-07-20"), dayAggregate("2026-07-21")],
          plottedDays: [dayAggregate("2026-07-20"), dayAggregate("2026-07-21")],
          activeDay: "",
          onDaySelect: () => {},
        },
      }),
    );

    const csatSection = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    expect(csatSection).not.toHaveTextContent("Chưa kết nối Freshdesk");
    expect(
      within(csatSection).getByText(/CSAT theo tuần trọn vẹn chạm khoảng ngày/),
    ).toBeVisible();
  });

  it("cuts CSAT to the picked days, not the weeks they touch, when the snapshot carries day grain", () => {
    // The picked range is Mon-Tue of a week whose Wed also has ratings. Week
    // grain would report all three days; day grain must report exactly two.
    // 5 + 5 rated tickets in range, 90 out of range -- so a number anywhere
    // near 100 means the cut silently widened back to the whole week.
    const inRange = csatWeek({ positive: 4, neutral: 1, negative: 0 });
    const outOfRange = csatWeek({ positive: 88, neutral: 1, negative: 1 });
    const weeklySnapshot = snapshotWithCsat(
      { "2026-07-20": csatWeek({ positive: 96, neutral: 3, negative: 1 }) },
      undefined,
      {
        "2026-07-20": inRange,
        "2026-07-21": inRange,
        "2026-07-22": outOfRange,
      },
    );

    renderWithQuery(
      belowFold(baseSnapshot, {
        weeklySnapshot,
        dayRange: {
          from: "2026-07-20",
          to: "2026-07-21",
          allDays: [dayAggregate("2026-07-20"), dayAggregate("2026-07-21")],
          plottedDays: [dayAggregate("2026-07-20"), dayAggregate("2026-07-21")],
          activeDay: "",
          onDaySelect: () => {},
        },
      }),
    );

    const csatSection = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    expect(
      within(csatSection).getByText(/Phạm vi CSAT: 20\/07–21\/07/),
    ).toBeVisible();
    expect(csatSection).not.toHaveTextContent(
      "CSAT theo tuần trọn vẹn chạm khoảng ngày",
    );
    // 8 positive + 2 neutral over 10 rated tickets: the two in-range days
    // summed, with 2026-07-22 left out entirely.
    expect(csatSection).toHaveTextContent("10");
    expect(csatSection).not.toHaveTextContent("100");
  });

  it("cuts entry coverage to the picked days, and sends the same window to the drill-down", async () => {
    const user = userEvent.setup();
    // The picked range is Mon-Tue of a week whose Wed also has coverage. Week
    // grain reports 100 tickets; day grain must report exactly the 8 in range.
    const weeklySnapshot = snapshotWithEntryCoverage({
      "2026-07-20": coverageBucket({ freshdesk_ticket_count: 4 }),
      "2026-07-21": coverageBucket({ freshdesk_ticket_count: 4 }),
      "2026-07-22": coverageBucket({
        freshdesk_ticket_count: 92,
        ai_replied_only: 89,
      }),
    });
    weeklySnapshot.views.mon_sun.entry_coverage!.by_week["2026-07-20"] =
      coverageBucket({ freshdesk_ticket_count: 100, ai_replied_only: 97 });
    const requested: string[] = [];
    server.use(
      http.get("/api/freshdesk-entry-coverage/tickets", ({ request }) => {
        requested.push(new URL(request.url).search);
        return HttpResponse.json({ items: [], page: 1, page_size: 10, total: 0 });
      }),
    );

    renderWithQuery(
      belowFold(baseSnapshot, {
        weeklySnapshot,
        dayRange: {
          from: "2026-07-20",
          to: "2026-07-21",
          allDays: [dayAggregate("2026-07-20"), dayAggregate("2026-07-21")],
          plottedDays: [dayAggregate("2026-07-20"), dayAggregate("2026-07-21")],
          activeDay: "",
          onDaySelect: () => {},
        },
      }),
    );

    const section = screen.getByRole("region", {
      name: "Độ phủ xử lý từ Freshdesk",
    });
    expect(
      within(section).getByText(/Phạm vi độ phủ: 20\/07–21\/07/),
    ).toBeVisible();
    expect(section).not.toHaveTextContent("Độ phủ theo tuần trọn vẹn");
    expect(section).toHaveTextContent("Ticket Freshdesk8");
    // 100 (the week) and 89/92 (the out-of-range day) must appear nowhere.
    expect(section).not.toHaveTextContent(/Ticket Freshdesk(100|92)/);
    expect(section).not.toHaveTextContent(/AI đã phản hồi(97|89)/);

    // The list under the counts has to answer for the same population; sending
    // only the touched week would return the whole week's tickets.
    await user.click(
      within(section).getAllByRole("button", { name: "Xem ticket" })[0]!,
    );
    await waitFor(() => expect(requested).not.toHaveLength(0));
    expect(requested[0]).toContain("opened_from=2026-07-20");
    expect(requested[0]).toContain("opened_to=2026-07-21");
  });

  it("names the shortfall instead of listing nothing when the picked range touches no week", () => {
    // A range landing entirely outside the observed weeks (the "30 ngày qua"
    // preset on a stale snapshot does this) yields no touched weeks. Joining an
    // empty list left the sentence as "chạm khoảng ngày: ." — punctuation
    // around a number that was never there.
    const weeklySnapshot = snapshotWithCsat({ "2026-07-20": csatWeek() });

    renderWithQuery(
      belowFold(baseSnapshot, {
        weeklySnapshot,
        dayRange: {
          from: "2026-07-20",
          to: "2026-07-21",
          allDays: [],
          plottedDays: [],
          activeDay: "",
          onDaySelect: () => {},
        },
      }),
    );

    const csatSection = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    expect(csatSection).toHaveTextContent(
      "Khoảng ngày đã chọn không chạm tuần nào có dữ liệu CSAT.",
    );
    expect(csatSection).not.toHaveTextContent("chạm khoảng ngày: .");
  });

  it("shows the Freshdesk connect action when cookie state is unknown, not just when it is expired or missing", () => {
    renderWithQuery(belowFold(baseSnapshot, { freshdeskCookieState: null }));

    const csatSection = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    expect(
      within(csatSection).getByRole("button", { name: "Kết nối Freshdesk" }),
    ).toBeVisible();
  });

  it("keeps Freshdesk outcome reconciliation out of the dashboard UI", () => {
    const snapshot = snapshotWithCsat({
      "2026-07-20": csatWeek(),
    });
    const view = snapshot.views.mon_sun;
    const withReconciliation: DashboardSnapshot = {
      ...snapshot,
      views: {
        ...snapshot.views,
        mon_sun: {
          ...view,
          outcome_reconciliation: {
            source: "freshdesk",
            fetched_at: "2026-08-03T01:00:00Z",
            by_week: {
              "2026-07-20": {
                langfuse_ai_end_to_end: 6,
                checked_ticket_count: 4,
                human_replied_after_ai: 1,
                unresolved_ticket_count: 1,
                mismatch_rate: 0.25,
              },
            },
          },
        },
      },
    };

    renderWithQuery(
      belowFold(withReconciliation, { activeWeek: "2026-07-20" }),
    );

    expect(
      screen.queryByRole("region", {
        name: "Đối chiếu kết quả xử lý với Freshdesk",
      }),
    ).toBeNull();
    expect(document.body).not.toHaveTextContent(
      /Đối chiếu Freshdesk|đã xác định có CS người trả lời sau|AI First phía trên/i,
    );
  });

  it("groups response-grain CSAT by outcome, Skill, or Category without showing zero rows", async () => {
    const user = userEvent.setup();
    const zero = { ticket_count: 0, positive: 0, neutral: 0, negative: 0 };
    const one = (value: string, bucket: "positive" | "neutral" | "negative") => ({
      value,
      ticket_count: 1,
      positive: bucket === "positive" ? 1 : 0,
      neutral: bucket === "neutral" ? 1 : 0,
      negative: bucket === "negative" ? 1 : 0,
    });
    const snapshot = snapshotWithCsat({
      "2026-07-20": csatWeek({
        response_count: 23,
        ticket_count: 20,
        positive: 12,
        neutral: 5,
        negative: 3,
        by_outcome: {
          ai_end_to_end: { ticket_count: 18, positive: 11, neutral: 4, negative: 3 },
          ai_then_cs: { ticket_count: 2, positive: 1, neutral: 1, negative: 0 },
          direct_cs: zero,
          unclassified: zero,
        },
        by_dimension: {
          skill: [
            { value: "interbank-fund-transfer", ticket_count: 6, positive: 4, neutral: 1, negative: 1 },
            { value: "withdraw", ticket_count: 3, positive: 2, neutral: 1, negative: 0 },
            { value: "topup", ticket_count: 2, positive: 1, neutral: 1, negative: 0 },
            { value: "Nhiều skill", ticket_count: 2, positive: 1, neutral: 0, negative: 1 },
            one("skill-05", "positive"),
            one("skill-06", "positive"),
            one("skill-07", "positive"),
            one("skill-08", "positive"),
            one("skill-09", "neutral"),
            one("skill-10", "neutral"),
            one("skill-11", "negative"),
            { value: "Chưa ghi nhận", ...zero },
          ],
          issue_category: [
            { value: "Chuyển tiền", ticket_count: 12, positive: 7, neutral: 3, negative: 2 },
            { value: "Rút tiền", ticket_count: 8, positive: 5, neutral: 2, negative: 1 },
          ],
        },
      }),
    });

    renderWithQuery(belowFold(snapshot));
    const section = screen.getByRole("region", { name: "Khách hài lòng tới đâu" });
    const grouping = within(section).getByRole("combobox", { name: "Nhóm theo" });
    expect(within(grouping).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Kết quả xử lý",
      "Skill",
      "Category",
    ]);
    expect(grouping).toHaveValue("outcome");
    expect(within(section).getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "Kết quả xử lý",
      "Phản hồi có đánh giá",
      "Rất hài lòng",
      "Bình thường",
      "Rất tệ",
    ]);
    const totalRow = within(section).getByRole("row", { name: /Tổng/ });
    expect(within(totalRow).getByText("20 ticket")).toBeVisible();
    expect(within(totalRow).getByText("23 phản hồi")).toBeVisible();
    expect(within(totalRow).getByText("12 · 52,2%")).toBeVisible();
    const smallRow = within(section).getByRole("row", { name: /AI xử lý trọn/ });
    expect(
      within(smallRow).getByRole("button", {
        name: "Lọc Ticket Explorer theo Kết quả xử lý: AI xử lý trọn",
      }),
    ).toBeVisible();
    expect(within(smallRow).getByText("Mẫu nhỏ")).toBeVisible();
    expect(within(smallRow).queryByText("%", { exact: false })).toBeNull();
    expect(within(section).queryByRole("button", { name: "Chuyển CS ngay từ đầu" })).toBeNull();
    expect(within(section).queryByRole("rowheader", { name: "Admin CS ZaloPay" })).toBeNull();

    await user.selectOptions(grouping, "skill");
    expect(within(section).getByRole("columnheader", { name: "Skill" })).toBeVisible();
    expect(within(section).getByRole("rowheader", { name: "interbank-fund-transfer" })).toBeVisible();
    expect(within(section).queryByRole("button", { name: "AI xử lý trọn" })).toBeNull();
    expect(within(section).queryByRole("rowheader", { name: "skill-11" })).toBeNull();
    expect(within(section).queryByRole("rowheader", { name: "Chưa ghi nhận" })).toBeNull();
    await user.click(within(section).getByRole("button", { name: "Xem tất cả 11 nhóm" }));
    expect(within(section).getByRole("rowheader", { name: "skill-11" })).toBeVisible();
    await user.click(within(section).getByRole("button", { name: "Thu gọn" }));
    expect(within(section).queryByRole("rowheader", { name: "skill-11" })).toBeNull();

    await user.selectOptions(grouping, "issue_category");
    expect(within(section).getByRole("columnheader", { name: "Category" })).toBeVisible();
    expect(within(section).getByRole("rowheader", { name: "Chuyển tiền" })).toBeVisible();
    expect(within(section).queryByRole("rowheader", { name: "interbank-fund-transfer" })).toBeNull();
    expect(section).toHaveTextContent("Mỗi phản hồi survey được tính một lần.");
  });

  it("shows raw bot-only ticket counts without percentages below twenty tickets", () => {
    // The stale-CSAT check compares fetched_at against real Date.now(); an
    // unpinned clock makes this test flip right after Vietnam midnight.
    vi.spyOn(Date, "now").mockReturnValue(
      new Date("2026-08-10T10:00:00+07:00").getTime(),
    );
    try {
      const snapshot = snapshotWithCsat({
        "2026-07-13": csatWeek({
          response_count: 12,
          ticket_count: 12,
          positive: 7,
          neutral: 3,
          negative: 2,
        }),
        "2026-07-20": csatWeek(),
      });

      renderWithQuery(belowFold(snapshot, { activeWeek: "2026-07-13" }));

      const section = screen.getByRole("region", {
        name: "Khách hài lòng tới đâu",
      });
      const rows = within(section).getAllByRole("row");
      expect(rows).toHaveLength(3);
      const totalRow = within(section).getByRole("row", { name: /Tổng/ });
      expect(within(totalRow).getAllByRole("cell").map(
        (cell) => cell.textContent,
      )).toEqual(["12 phản hồi12 ticket", "7", "3", "2"]);
      const outcomeRow = within(section).getByRole("row", { name: /AI xử lý trọn/ });
      expect(within(outcomeRow).getAllByRole("cell").map(
        (cell) => cell.textContent,
      )).toEqual(["12Mẫu nhỏ", "7", "3", "2"]);
      expect(section).not.toHaveTextContent("%");
      const source = document.getElementById("csat-source");
      expect(source).toHaveTextContent(
        /^CSAT: Freshdesk · chỉ Admin CS ZaloPay · cập nhật .+\.$/,
      );
      expect(source?.tagName).toBe("P");
      expect(document.getElementById("csat-attribution")).toBeNull();
      expect(section).not.toHaveTextContent(
        "không tính phản hồi không xác định được agent hoặc thuộc CS người",
      );
      expect(source?.querySelector("time")).not.toBeNull();
      expect(within(section).queryByRole("row", { name: /human|CS người/i })).toBeNull();
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("inherits the global report scope without exposing a duplicate CSAT week control", () => {
    const snapshot = snapshotWithCsat({
      "2026-07-13": csatWeek({
        response_count: 9,
        ticket_count: 9,
        positive: 5,
        neutral: 2,
        negative: 2,
      }),
      "2026-07-20": csatWeek({
        response_count: 20,
        ticket_count: 20,
        positive: 14,
        neutral: 3,
        negative: 3,
      }),
    });

    const latestRender = renderWithQuery(belowFold(snapshot));

    const section = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    expect(
      within(section).queryByRole("combobox", { name: "Tuần CSAT" }),
    ).toBeNull();
    expect(within(section).getByRole("row", { name: /Tổng/ })).toHaveTextContent(
      "20 ticket",
    );

    latestRender.unmount();
    const previousRender = renderWithQuery(
      belowFold(snapshot, { activeWeek: "2026-07-13" }),
    );
    const previousSection = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    expect(
      within(previousSection).getByRole("row", { name: /Tổng/ }),
    ).toHaveTextContent(
      "9 ticket",
    );

    previousRender.unmount();
    renderWithQuery(belowFold(snapshot, { allWeeks: true }));
    const allPeriodSection = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    expect(
      within(allPeriodSection).getByRole("row", { name: /Tổng/ }),
    ).toHaveTextContent(
      "29 ticket",
    );
  });

  it("shows all three count-percentages at twenty responses and aggregates the whole period", async () => {
    // The stale-CSAT check compares fetched_at against real Date.now(); an
    // unpinned clock makes this test flip right after Vietnam midnight.
    vi.spyOn(Date, "now").mockReturnValue(
      new Date("2026-08-10T10:00:00+07:00").getTime(),
    );
    const user = userEvent.setup();
    const snapshot = snapshotWithCsat({
      "2026-07-13": csatWeek({
        response_count: 9,
        ticket_count: 9,
        positive: 5,
        neutral: 2,
        negative: 2,
        feedback_entries: [
          {
            ticket_id: "6991253",
            // The survey can arrive after the ticket's cohort week. The filter
            // must still use the week the ticket opened, not this timestamp.
            responded_at: "2026-07-23T01:00:00Z",
            satisfaction_bucket: "negative",
            outcome: "ai_end_to_end",
            skill: "interbank-fund-transfer",
            issue_category: "Chuyển tiền",
            text: "Phản hồi tuần trước",
            response_number: 1,
            response_total: 1,
            is_latest_for_ticket: true,
          },
        ],
      }),
      "2026-07-20": csatWeek({
        response_count: 20,
        ticket_count: 20,
        positive: 14,
        neutral: 3,
        negative: 3,
        feedback_entries: [
          {
            ticket_id: "6991254",
            responded_at: "2026-07-22T01:00:00Z",
            satisfaction_bucket: "positive",
            outcome: "ai_end_to_end",
            skill: "interbank-fund-transfer",
            issue_category: "Chuyển tiền",
            text: "Phản hồi tuần mới nhất",
            response_number: 1,
            response_total: 1,
            is_latest_for_ticket: true,
          },
        ],
      }),
    });

    const latestRender = renderWithQuery(belowFold(snapshot));

    const section = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    expect(
      within(section)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual([
      "Kết quả xử lý",
      "Phản hồi có đánh giá",
      "Rất hài lòng",
      "Bình thường",
      "Rất tệ",
    ]);
    expect(within(section).getByRole("row", { name: /Tổng/ })).toHaveTextContent(
      "20 ticket14 · 70,0%3 · 15,0%3 · 15,0%",
    );
    expect(
      within(section).getByRole("columnheader", { name: "Bình thường" }),
    ).toBeVisible();
    expect(
      within(section).getByRole("button", {
        name: "Xem 1 nội dung phản hồi",
      }),
    ).toBeVisible();
    expect(section).not.toHaveTextContent("Chưa cập nhật hôm nay.");

    latestRender.unmount();
    renderWithQuery(belowFold(snapshot, { allWeeks: true }));
    const allPeriodSection = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });

    expect(
      within(allPeriodSection).getByRole("row", { name: /Tổng/ }),
    ).toHaveTextContent(
      "29 ticket19 · 65,5%5 · 17,2%5 · 17,2%",
    );
    expect(
      within(allPeriodSection).getByRole("button", {
        name: "Xem 2 nội dung phản hồi",
      }),
    ).toBeVisible();

    await user.click(
      within(allPeriodSection).getByRole("button", {
        name: "Xem 2 nội dung phản hồi",
      }),
    );
    await user.selectOptions(
      within(allPeriodSection).getByRole("combobox", { name: "Tuần mở ticket" }),
      "2026-07-13",
    );
    expect(within(allPeriodSection).getByText("Phản hồi tuần trước")).toBeVisible();
    expect(
      allPeriodSection.querySelector('time[datetime="2026-07-23T01:00:00Z"]'),
    ).not.toBeNull();
    expect(
      within(allPeriodSection).queryByText("Phản hồi tuần mới nhất"),
    ).toBeNull();
    vi.restoreAllMocks();
  });

  it("keeps feedback closed and warns when Freshdesk is not updated today", async () => {
    const user = userEvent.setup();
    const firstComment = "Cảm ơn, xử lý nhanh";
    const secondComment = "Mình đã nhận được hỗ trợ";
    const thirdComment = "Chưa xử lý được";
    const snapshot = snapshotWithCsat(
      {
        "2026-07-20": csatWeek({
          feedback_entries: [
            {
              ticket_id: "6991254",
              responded_at: "2026-07-20T01:00:00Z",
              satisfaction_bucket: "positive",
              outcome: "ai_end_to_end",
              skill: "interbank-fund-transfer",
              issue_category: "Chuyển tiền",
              text: firstComment,
              response_number: 1,
              response_total: 2,
              is_latest_for_ticket: false,
            },
            {
              ticket_id: "6991254",
              responded_at: "2026-07-22T01:00:00Z",
              satisfaction_bucket: "neutral",
              outcome: "ai_end_to_end",
              skill: "interbank-fund-transfer",
              issue_category: "Chuyển tiền",
              text: secondComment,
              response_number: 2,
              response_total: 2,
              is_latest_for_ticket: true,
            },
            {
              ticket_id: "6991256",
              responded_at: "2026-07-20T01:00:00.500000Z",
              satisfaction_bucket: "negative",
              outcome: "ai_end_to_end",
              skill: "interbank-fund-transfer",
              issue_category: "Chuyển tiền",
              text: thirdComment,
              response_number: 1,
              response_total: 1,
              is_latest_for_ticket: true,
            },
          ],
        }),
      },
      new Date(Date.now() - 49 * 60 * 60 * 1_000).toISOString(),
    );

    renderWithQuery(belowFold(snapshot));

    const section = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    const disclosure = within(section).getByRole("button", {
      name: "Xem 3 nội dung phản hồi",
    });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(section).not.toHaveTextContent(firstComment);
    expect(section).not.toHaveTextContent(secondComment);
    expect(section).not.toHaveTextContent(thirdComment);
    expect(disclosure).not.toHaveAccessibleName(new RegExp(firstComment));
    expect(document.getElementById("csat-source")).toHaveTextContent(
      /· Chưa cập nhật hôm nay\.$/,
    );

    await user.click(disclosure);

    expect(within(section).getByText(firstComment)).toBeVisible();
    expect(within(section).getByText(secondComment)).toBeVisible();
    expect(within(section).getByText(thirdComment)).toBeVisible();
    expect(disclosure).toHaveAccessibleName("Ẩn 3 nội dung phản hồi");
    expect(disclosure).not.toHaveAccessibleName(new RegExp(firstComment));
    expect(within(section).getAllByRole("listitem")).toHaveLength(3);
    expect(within(section).getByText("Lần 1/2")).toBeVisible();
    expect(within(section).getByText("Lần 2/2 · Mới nhất")).toBeVisible();
    expect(section).not.toHaveTextContent(/bình luận|free text|lựa chọn có sẵn/i);
    const commentItems = within(section).getAllByRole("listitem");
    expect(within(commentItems[0] as HTMLLIElement).getByText("Bình thường")).toBeVisible();
    expect(within(commentItems[1] as HTMLLIElement).getByText("Rất tệ")).toBeVisible();
    expect(within(commentItems[2] as HTMLLIElement).getByText("Rất hài lòng")).toBeVisible();
    expect(section.querySelector('time[datetime="2026-07-20T01:00:00Z"]')).not.toBeNull();
    expect(
      within(section).getAllByRole("link", {
        name: "Mở ticket 6991254 trên Freshdesk trong thẻ mới",
      })[0],
    ).toHaveAttribute(
      "href",
      "https://vngzalopay.freshdesk.com/a/tickets/6991254",
    );

    await user.selectOptions(
      within(section).getByRole("combobox", { name: "Mức hài lòng" }),
      "negative",
    );
    expect(within(section).getAllByRole("listitem")).toHaveLength(1);
    expect(within(section).getByText(thirdComment)).toBeVisible();

    await user.selectOptions(
      within(section).getByRole("combobox", { name: "Mức hài lòng" }),
      "all",
    );
    await user.selectOptions(
      within(section).getByRole("combobox", { name: "Sắp xếp thời gian" }),
      "oldest",
    );
    expect(
      within(within(section).getAllByRole("listitem")[0] as HTMLLIElement)
        .getAllByRole("link", {
          name: "Mở ticket 6991254 trên Freshdesk trong thẻ mới",
        })[0],
    ).toBeVisible();
  });

  it("paginates 117 CSAT comments ten at a time with bounded, accessible controls", async () => {
    const user = userEvent.setup();
    const snapshot = snapshotWithCsat({
      "2026-07-20": csatWeek({
        response_count: 117,
        ticket_count: 117,
        positive: 39,
        neutral: 39,
        negative: 39,
        feedback_entries: csatComments(117),
      }),
    });

    renderWithQuery(belowFold(snapshot));

    const section = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    await user.click(
      within(section).getByRole("button", {
        name: "Xem 117 nội dung phản hồi",
      }),
    );

    expect(within(section).getAllByRole("listitem")).toHaveLength(10);
    expect(section).toHaveTextContent("Hiển thị 1–10 / 117 nội dung phản hồi");
    const pagination = within(section).getByRole("navigation", {
      name: "Phân trang nội dung phản hồi CSAT",
    });
    expect(
      within(pagination).getByRole("button", { name: "Trang 1" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      within(pagination).getByRole("button", { name: "Trang 12" }),
    ).toBeVisible();
    expect(
      within(pagination).queryByRole("button", { name: "Trang 6" }),
    ).toBeNull();

    const nextPage = within(pagination).getByRole("button", {
      name: "Trang sau",
    });
    await user.click(nextPage);
    expect(section).toHaveTextContent("Hiển thị 11–20 / 117 nội dung phản hồi");
    expect(within(section).getAllByRole("listitem")).toHaveLength(10);
    await waitFor(() => expect(nextPage).toHaveFocus());
    expect(
      within(pagination).getByRole("button", { name: "Trang 2" }),
    ).toHaveAttribute("aria-current", "page");

    await user.click(
      within(pagination).getByRole("button", { name: "Trang 5" }),
    );
    expect(
      within(pagination).getByRole("button", { name: "Trang 5" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      within(pagination).getByRole("button", { name: "Trang 4" }),
    ).toBeVisible();
    expect(
      within(pagination).getByRole("button", { name: "Trang 6" }),
    ).toBeVisible();
    expect(
      within(pagination).queryByRole("button", { name: "Trang 2" }),
    ).toBeNull();

    await user.click(
      within(pagination).getByRole("button", { name: "Trang 12" }),
    );
    expect(section).toHaveTextContent("Hiển thị 111–117 / 117 nội dung phản hồi");
    expect(within(section).getAllByRole("listitem")).toHaveLength(7);
    expect(
      within(pagination).queryByRole("button", { name: "Trang sau" }),
    ).toBeNull();
    expect(
      within(pagination).getByRole("button", { name: "Trang trước" }),
    ).toBeVisible();
  });

  it("keeps the comment disclosure target present when filters return no results", async () => {
    const user = userEvent.setup();
    const snapshot = snapshotWithCsat({
      "2026-07-20": csatWeek({
        response_count: 11,
        ticket_count: 11,
        positive: 11,
        neutral: 0,
        negative: 0,
        feedback_entries: csatComments(11).map((comment) => ({
          ...comment,
          satisfaction_bucket: "positive" as const,
        })),
      }),
    });

    renderWithQuery(belowFold(snapshot));

    const section = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    const disclosure = within(section).getByRole("button", {
      name: "Xem 11 nội dung phản hồi",
    });
    await user.click(disclosure);
    await user.selectOptions(
      within(section).getByRole("combobox", { name: "Mức hài lòng" }),
      "negative",
    );

    expect(section).toHaveTextContent("Không có nội dung phản hồi phù hợp.");
    expect(within(section).queryByRole("listitem")).toBeNull();
    const controlledId = disclosure.getAttribute("aria-controls");
    expect(controlledId).toBe("csat-comments");
    expect(document.getElementById(controlledId ?? "")).not.toBeNull();
  });

  it("returns comment pagination to page one after filtering or sorting", async () => {
    const user = userEvent.setup();
    const snapshot = snapshotWithCsat({
      "2026-07-20": csatWeek({
        response_count: 23,
        ticket_count: 23,
        positive: 8,
        neutral: 8,
        negative: 7,
        feedback_entries: csatComments(23),
      }),
    });

    renderWithQuery(belowFold(snapshot));

    const section = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    await user.click(
      within(section).getByRole("button", {
        name: "Xem 23 nội dung phản hồi",
      }),
    );
    await user.click(
      within(section).getByRole("button", { name: "Trang sau" }),
    );
    expect(section).toHaveTextContent("Hiển thị 11–20 / 23 nội dung phản hồi");

    await user.selectOptions(
      within(section).getByRole("combobox", { name: "Mức hài lòng" }),
      "neutral",
    );
    expect(section).toHaveTextContent("Hiển thị 1–8 / 8 nội dung phản hồi");
    expect(
      within(section).queryByRole("navigation", {
        name: "Phân trang nội dung phản hồi CSAT",
      }),
    ).toBeNull();

    await user.selectOptions(
      within(section).getByRole("combobox", { name: "Mức hài lòng" }),
      "all",
    );
    await user.click(
      within(section).getByRole("button", { name: "Trang sau" }),
    );
    await user.selectOptions(
      within(section).getByRole("combobox", { name: "Sắp xếp thời gian" }),
      "oldest",
    );

    expect(section).toHaveTextContent("Hiển thị 1–10 / 23 nội dung phản hồi");
    expect(
      within(section).getByRole("button", { name: "Trang 1" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      within(within(section).getAllByRole("listitem")[0] as HTMLLIElement)
        .getByText("Nội dung phản hồi 1"),
    ).toBeVisible();
  });

  it("does not show comments from other weeks under a zero-comment weekly scope", () => {
    const snapshot = snapshotWithCsat({
      "2026-07-13": csatWeek({
        feedback_entries: [
          {
            ticket_id: "6991253",
            responded_at: "2026-07-15T01:00:00Z",
            satisfaction_bucket: "negative",
            outcome: "ai_end_to_end",
            skill: "interbank-fund-transfer",
            issue_category: "Chuyển tiền",
            text: "Chỉ thuộc tuần trước",
            response_number: 1,
            response_total: 1,
            is_latest_for_ticket: true,
          },
        ],
      }),
      "2026-07-20": csatWeek({ feedback_entries: [] }),
    });

    const latestRender = renderWithQuery(belowFold(snapshot));
    const section = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    expect(
      within(section).queryByRole("button", { name: /nội dung phản hồi/ }),
    ).toBeNull();

    latestRender.unmount();
    renderWithQuery(belowFold(snapshot, { allWeeks: true }));
    const allPeriodSection = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    expect(
      within(allPeriodSection).getByRole("button", {
        name: "Xem 1 nội dung phản hồi",
      }),
    ).toBeVisible();
  });

  it("does not expose an empty week as an actionable chart filter", () => {
    const snapshot = snapshotWithWeeks([
      weekRow({ cohort_week: "2026-07-06" }),
      weekRow({
        cohort_week: "2026-07-13",
        has_data: false,
        total_tickets: 0,
        ai_first_count: 0,
        ai_first_rate: 0,
        ai_end_to_end_count: 0,
        ai_then_cs_count: 0,
        direct_cs_count: 0,
        unclassified_count: 0,
      }),
      weekRow({ cohort_week: "2026-07-20" }),
    ]);

    renderWithQuery(belowFold(snapshot));

    expect(
      document.querySelectorAll('[data-week-target="2026-07-13"]'),
    ).toHaveLength(0);
  });

  it("keeps TPE, source-faithful transfer reasons, and actionable >3-turn diagnostics", async () => {
    const user = userEvent.setup();
    renderWithQuery(belowFold(baseSnapshot));

    expect(screen.queryByText(/không phải nguyên nhân đã chứng minh/)).toBeNull();
    expect(
      screen.getByRole("heading", {
        name: "Tín hiệu chuyển CS và ticket có hơn 3 lượt xử lý",
      }),
    ).toBeVisible();

    const tpeRegion = screen.getByRole("region", {
      name: "Transstatus và Step result",
    });
    expect(tpeRegion).toHaveAttribute("id", "tpeDistribution");
    // Collapsed by default; open it to reach the table underneath.
    await user.click(
      screen.getByRole("heading", { name: "Transstatus và Step result" }),
    );
    const tpeTable = within(tpeRegion).getByRole("table", {
      name: "Transstatus và Step result",
    });
    expect(tpeTable).toHaveAttribute("aria-describedby", "transferScope");
    // The base fixture's only week is also its latest, so the default
    // (nothing explicitly picked) now resolves to that week's own caption
    // rather than a whole-range one — the same default the KPI ledger uses.
    expect(tpeTable).toHaveAccessibleDescription(
      /^3 ticket đã chuyển CS trong tuần 20\/07–26\/07\./,
    );
    expect(
      within(tpeTable)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual([
      "Trạng thái",
      "Transstatus",
      "Step result",
      "Ticket",
      "Tỷ lệ ticket có mã này",
    ]);
    const tpeRow = within(tpeTable).getByRole("row", { name: /-365/ });
    expect(
      within(tpeRow).getByRole("rowheader", { name: "FAILED_FACE_AUTH" }),
    ).toBeVisible();
    expect(
      within(tpeRow).getByRole("button", {
        name: "Lọc Ticket Explorer theo Transstatus: -365",
      }),
    ).toBeVisible();
    expect(within(tpeRow).getByText("-1013")).toBeVisible();
    expect(within(tpeRow).getByText("2")).toBeVisible();
    // This row's own count (2) is the small-sample guard's numerator, not
    // the whole-table `observed_transfer_denominator` (3) — well under the
    // 20-sample threshold, so the share column hides the rate.
    expect(
      within(tpeRow).getAllByRole("cell").at(-1),
    ).toHaveTextContent("—");
    const missingRow = within(tpeTable).getByRole("row", { name: /-217/ });
    expect(
      within(missingRow).getByRole("rowheader", { name: "Chưa phân loại" }),
    ).toBeVisible();
    expect(
      within(missingRow).getByText("Không có Step result"),
    ).toBeVisible();
    // The Step-result coverage sentence and the TPE taxonomy caption were
    // removed as redundant narration; the table itself already shows which
    // rows have no Step result.
    expect(tpeRegion.querySelector("#stepResultCoverage")).toBeNull();
    expect(tpeRegion.querySelector("#tpeStatusCaption")).toBeNull();
    expect(tpeRegion.textContent).not.toMatch(/case|taxonomy|Đang xử lý/i);

    const conditionRegion = screen.getByRole("region", {
      name: "Lý do chuyển CS",
    });
    expect(conditionRegion).toHaveAttribute("id", "guardrailDistribution");
    const conditionTable = within(conditionRegion).getByRole("table", {
      name: "Lý do chuyển CS",
    });
    expect(
      within(conditionTable)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual([
      "Lý do chuyển CS",
      "Giá trị nguồn",
      "Nguồn phát hiện",
      "Skill",
      "Ticket",
      "Tỷ lệ",
    ]);
    const skillReason = within(conditionTable).getByRole("row", {
      name: /Skill đề xuất chuyển CS/,
    });
    expect(
      within(skillReason).getByRole("button", {
        name: "Lọc Ticket Explorer theo Lý do chuyển CS: Skill đề xuất chuyển CS",
      }),
    ).toBeVisible();
    expect(skillReason).toHaveTextContent("cs_escalation");
    expect(skillReason).toHaveTextContent(
      "skill_guardrail_checked · stage=output",
    );
    expect(skillReason).toHaveTextContent("interbank-fund-transfer");
    expect(skillReason).toHaveTextContent("1");
    // This row's own count (1) is well under the small-sample threshold
    // (20), so the shared guard hides the rate here too.
    expect(
      within(skillReason).getAllByRole("cell").at(-1),
    ).toHaveTextContent("—");
    const responseReason = within(conditionTable).getByRole("row", {
      name: /Phản hồi AI được nhận diện là cần chuyển CS/,
    });
    expect(responseReason).toHaveTextContent("cs_escalation");
    expect(responseReason).toHaveTextContent("output_guardrail");
    expect(responseReason).toHaveTextContent("—");

    const gt4Region = screen.getByRole("region", {
      name: "Ticket có hơn 3 lượt xử lý",
    });
    expect(gt4Region).toHaveAttribute("id", "ruleGt4Panel");
    expect(within(gt4Region).getByRole("row", { name: /^Tổng/ })).toHaveTextContent(
      "3",
    );
    expect(
      within(gt4Region).getByRole("row", { name: /^Đã chuyển CS/ }),
    ).toHaveTextContent("1");
    expect(
      within(gt4Region).getByRole("button", {
        name: "Lọc Ticket Explorer theo Trạng thái: Đã chuyển CS",
      }),
    ).toBeVisible();
    expect(
      within(gt4Region).getByRole("row", { name: /^Chưa chuyển CS/ }),
    ).toHaveTextContent("2");
    expect(
      within(gt4Region).getByRole("button", { name: "Xem 2 ticket chưa chuyển CS" }),
    ).toBeVisible();

    const escalationAnchor = document.getElementById("escalationPanel");
    expect(escalationAnchor).not.toBeNull();
    expect(escalationAnchor).toHaveAttribute("hidden");
    expect(escalationAnchor).toHaveTextContent("");
    expect(document.body).not.toHaveTextContent(
      /rule đã bắn|guard chặn|khoảng trống rule/i,
    );
  });

  it("opens stuck tickets in the same latest-week or whole-period scope being shown", async () => {
    const user = userEvent.setup();
    const onShowStuckTickets = vi.fn();
    const latestRender = renderWithQuery(
      belowFold(baseSnapshot, {
        onShowStuckTickets,
      }),
    );

    await user.click(
      screen.getByRole("button", { name: "Xem 2 ticket chưa chuyển CS" }),
    );
    expect(onShowStuckTickets).toHaveBeenLastCalledWith("2026-07-20");

    latestRender.unmount();
    renderWithQuery(
      belowFold(baseSnapshot, {
        allWeeks: true,
        onShowStuckTickets,
      }),
    );
    await user.click(
      screen.getByRole("button", { name: /ticket chưa chuyển CS/ }),
    );
    expect(onShowStuckTickets).toHaveBeenLastCalledWith("");
  });

  it("shows a readable reason and exact source when only guardrail data exists", () => {
    const emptyTransfer = {
      observed_transfer_denominator: 1,
      triggers: [
        {
          reason: "out_of_scope" as const,
          rule: "off_topic" as const,
          source: "skill_guardrail_checked" as const,
          stage: "input" as const,
          skill: "topup",
          count: 1,
        },
      ],
      step_result_missing: { count: 1, denominator: 1 },
      tpe: [],
      guardrail: [{ rule: "off_topic" as const, count: 1 }],
      escalation_guard_blocked: { count: 1, denominator: 1 },
    };
    const mon_sun = baseSnapshot.views.mon_sun;
    const latestWeek = mon_sun.weekly[0]?.cohort_week ?? "";
    const snapshot: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        ...baseSnapshot.views,
        mon_sun: {
          ...mon_sun,
          transfer_reasons: emptyTransfer,
          // The dashboard now defaults to the latest week's by_week entry, so
          // an empty-signal fixture must be empty there too, not only at the
          // whole-range level.
          by_week: {
            ...mon_sun.by_week,
            [latestWeek]: {
              segments: mon_sun.segments,
              transfer_reasons: emptyTransfer,
            },
          },
        },
      },
    };

    renderWithQuery(belowFold(snapshot));

    expect(
      screen.queryByText("Không có tín hiệu nào trong phạm vi đang chọn."),
    ).toBeNull();
    expect(
      screen.getByRole("region", { name: "Transstatus và Step result" }),
    ).toBeVisible();
    const reasonRow = screen.getByRole("row", {
      name: /Bộ kiểm tra xác định nội dung ngoài phạm vi hỗ trợ/,
    });
    expect(reasonRow).toHaveTextContent("off_topic");
    expect(reasonRow).toHaveTextContent("skill_guardrail_checked · stage=input");
    expect(reasonRow).toHaveTextContent("topup");
    expect(screen.queryByText(/Đã ở CS/i)).toBeNull();
  });

  it("shows a segment count with its share and switches dimension on the client", async () => {
    const user = userEvent.setup();
    renderWithQuery(belowFold(baseSnapshot));

    const table = screen.getByRole("table", { name: /Ticket: tỷ trọng trong tuần/ });
    // The fixture's total (10) is below the small-sample threshold (20), so
    // the guard shows the raw count instead of "count · rate".
    expect(within(table).getByText("10")).toBeVisible();

    await user.click(screen.getByRole("tab", { name: "Product Code" }));
    expect(screen.getByRole("tab", { name: "Product Code" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it.each([
    ["Category", "issue_category"],
    ["App", "app"],
    ["Product Code", "product_code"],
    ["Skill", "skill"],
    ["Intent", "intent"],
  ] as const)(
    "hides zero-ticket %s rows without hiding a positive row whose child metrics are zero",
    async (tabLabel, dimension) => {
      const user = userEvent.setup();
      const snapshot = snapshotWithActiveSegmentBuckets(dimension, {
        "Có ticket": { total: 6, ai_first: 0, transferred: 0, reopen: 0 },
        "Không có ticket": { total: 0, ai_first: 0, transferred: 0, reopen: 0 },
      });
      renderWithQuery(belowFold(snapshot, { activeWeek: "2026-07-20" }));

      await user.click(screen.getByRole("tab", { name: tabLabel }));
      const panel = screen.getByRole("tabpanel", { name: tabLabel });
      expect(
        within(panel).getByRole("button", {
          name: `Lọc Ticket Explorer theo ${tabLabel}: Có ticket`,
        }),
      ).toBeVisible();
      // total: 6 is below the small-sample threshold (20), so the guard
      // shows the raw count instead of "count · rate".
      expect(within(panel).getByText("6")).toBeVisible();
      expect(within(panel).queryByRole("button", { name: "Không có ticket" })).toBeNull();
      expect(within(panel).queryByRole("rowheader", { name: "Không có ticket" })).toBeNull();
    },
  );

  it("shows a real empty state when every bucket in the selected dimension has zero tickets", async () => {
    const user = userEvent.setup();
    const snapshot = snapshotWithActiveSkillBuckets({
      "Chưa ghi nhận": { total: 0, ai_first: 0, transferred: 0, reopen: 0 },
    });
    renderWithQuery(belowFold(snapshot, { activeWeek: "2026-07-20" }));

    await user.click(screen.getByRole("tab", { name: "Skill" }));
    const panel = screen.getByRole("tabpanel", { name: "Skill" });
    expect(within(panel).getByText("Không có ticket trong phạm vi đang chọn.")).toBeVisible();
    expect(within(panel).queryByRole("table")).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Chưa ghi nhận" })).toBeNull();
  });

  it("names ticket-source dimensions without redundant methodology copy", () => {
    renderWithQuery(belowFold(baseSnapshot));

    expect(
      screen.getByRole("heading", {
        name: "So sánh theo thuộc tính ticket",
      }),
    ).toBeVisible();
    expect(screen.queryByText(/không tự gộp hoặc diễn giải lại/)).toBeNull();
    expect(screen.getByRole("tab", { name: "Category" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Product Code" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Skill" })).toBeVisible();
    expect(screen.queryByText("Nhóm vấn đề")).toBeNull();
    expect(screen.queryByText("Nghiệp vụ")).toBeNull();
  });

  it("passes the active segment dimension and row value to cross-filtering", async () => {
    const user = userEvent.setup();
    const onSegmentSelect = vi.fn();
    renderWithQuery(belowFold(baseSnapshot, { onSegmentSelect }));

    await user.click(
      screen.getByRole("button", {
        name: "Lọc Ticket Explorer theo Category: Thanh toán-IBFT",
      }),
    );

    expect(onSegmentSelect).toHaveBeenCalledOnce();
    expect(onSegmentSelect).toHaveBeenCalledWith(
      "issue_category",
      "Thanh toán-IBFT",
    );
  });

  it("uses one count-and-rate grammar for every segment metric", () => {
    renderWithQuery(belowFold(baseSnapshot));

    const table = screen.getByRole("table", {
      name: /Ticket: tỷ trọng trong tuần/,
    });
    expect(
      within(table).getByRole("columnheader", { name: "Ticket" }),
    ).toBeVisible();
    const row = within(table)
      .getByRole("button", {
        name: "Lọc Ticket Explorer theo Category: Thanh toán-IBFT",
      })
      .closest("tr");
    expect(row).not.toBeNull();
    // Every denominator in this fixture (10, 8, 3, 2) is below the
    // small-sample threshold (20), so the shared guard falls back to the
    // raw count for all four columns instead of asserting a rate.
    expect(within(row as HTMLTableRowElement).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "10",
      "8",
      "3",
      "2",
    ]);
    expect(row).not.toHaveTextContent("(");
  });

  it("implements roving segment tabs for arrows, Home, and End", async () => {
    const user = userEvent.setup();
    renderWithQuery(belowFold(baseSnapshot));

    const issueTab = screen.getByRole("tab", { name: "Category" });
    issueTab.focus();

    await user.keyboard("{ArrowRight}");
    const appTab = screen.getByRole("tab", { name: "App" });
    expect(appTab).toHaveAttribute("aria-selected", "true");
    expect(appTab).toHaveFocus();

    await user.keyboard("{End}");
    const intentTab = screen.getByRole("tab", { name: "Intent" });
    expect(intentTab).toHaveAttribute("aria-selected", "true");
    expect(intentTab).toHaveFocus();

    await user.keyboard("{Home}");
    expect(issueTab).toHaveAttribute("aria-selected", "true");
    expect(issueTab).toHaveFocus();

    await user.keyboard("{ArrowLeft}");
    expect(intentTab).toHaveAttribute("aria-selected", "true");
    expect(intentTab).toHaveFocus();
  });

});

describe("Ticket Explorer", () => {
  it("shows, filters, and exports latest Admin CS satisfaction without leaking raw states", async () => {
    const user = userEvent.setup();
    const download = captureDownload();
    const states = ["positive", "neutral", "negative", "unrated", null] as const;
    const labels = ["Rất hài lòng", "Bình thường", "Rất tệ", "Chưa có đánh giá", "—"];
    const requests: URL[] = [];
    const baseTicket = {
      opened_at: "2026-07-20T02:00:00Z",
      cohort_week: "2026-07-20",
      cohort_status: "complete" as const,
      is_weekend_start: false,
      outcome: "ai_end_to_end" as const,
      ai_first: true,
      transferred: false,
      reopen_lifetime: 0,
      reopen_within_7d: 0,
      ai_reply_count: 1,
      turn_count: 2,
      gt4_turn: false,
      issue_category: "Thanh toán",
      app: "Zalopay",
      product_code: "IBFT",
      skill: "interbank-fund-transfer",
      intent: null,
      tpe_code: null,
      tpe_status: null,
      guardrail_rule: null,
      transfer_reason: null,
      escalation_guard_blocked: false,
      data_quality: "valid" as const,
      model_core: null,
    };
    const tickets = states.map((state, index) => ({
      ...baseTicket,
      ticket_id: String(7_100_001 + index),
      csat_satisfaction: state,
    }));
    server.use(
      http.get("/api/tickets", ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        const satisfaction = url.searchParams.get("csat_satisfaction");
        const items = satisfaction === null
          ? tickets
          : tickets.filter((ticket) => ticket.csat_satisfaction === satisfaction);
        return HttpResponse.json({ items, page: 1, page_size: 50, total: items.length });
      }),
    );

    function ControlledTicketExplorer() {
      const [filters, setFilters] = useState<TicketFilters>(EMPTY_TICKET_FILTERS);
      return (
        <TicketExplorer
          snapshot={baseSnapshot}
          weekDefinition="mon_sun"
          enabled
          filters={filters}
          onFiltersChange={setFilters}
        />
      );
    }

    renderWithQuery(<ControlledTicketExplorer />);
    const table = await screen.findByRole("table", { name: /ticket khớp bộ lọc/i });
    expect(
      screen.getByRole("region", { name: "5 ticket khớp bộ lọc." }),
    ).toBeVisible();
    const headers = within(table).getAllByRole("columnheader").map((header) => header.textContent);
    expect(headers.indexOf("CSAT")).toBe(headers.indexOf("Kết quả") + 1);
    for (const label of labels.filter((item) => item !== "—")) {
      expect(within(table).getByText(label)).toBeVisible();
    }
    expect(within(table).getAllByText("—").length).toBeGreaterThan(0);
    const ratedBadges = states.slice(0, 3).map((_, index) =>
      within(table).getByText(labels[index] as string),
    );
    expect(ratedBadges.every((badge) => badge.tagName === "SPAN" && badge.className !== "")).toBe(true);
    expect(within(table).getByText("Chưa có đánh giá")).toHaveAttribute(
      "data-satisfaction",
      "unrated",
    );

    await toggleMultiSelectOption(
      user,
      document.body,
      "csatSatisfactionInput",
      "CSAT",
      "Rất tệ",
    );
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.get("csat_satisfaction")).toBe("negative");
    });
    expect(screen.getByRole("region", {
      name: "Bộ lọc đang áp dụng trong Ticket Explorer",
    })).toHaveTextContent("CSAT: Rất tệ");
    expect(await within(table).findByText("Rất tệ")).toBeVisible();
    expect(within(table).queryByText("Rất hài lòng")).toBeNull();

    await toggleMultiSelectOption(
      user,
      document.body,
      "csatSatisfactionInput",
      "CSAT",
      "Rất tệ",
    );
    expect(multiSelectSummaryText(document.body, "CSAT")).toBe("Tất cả");
    await waitFor(() => expect(within(table).getByText("Rất hài lòng")).toBeVisible());

    await toggleMultiSelectOption(
      user,
      document.body,
      "transferReasonInput",
      "Lý do chuyển CS",
      "Skill đề xuất chuyển CS",
    );
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.get("transfer_reason")).toBe(
        "skill_suggested_transfer",
      );
    });
    expect(
      screen.getByRole("region", {
        name: "Bộ lọc đang áp dụng trong Ticket Explorer",
      }),
    ).toHaveTextContent("Lý do chuyển CS: Skill đề xuất chuyển CS");
    await toggleMultiSelectOption(
      user,
      document.body,
      "transferReasonInput",
      "Lý do chuyển CS",
      "Skill đề xuất chuyển CS",
    );

    await user.click(screen.getByRole("button", { name: "Tải CSV ticket" }));
    const exported = await download.text();
    for (const label of labels) {
      expect(exported).toContain(label);
    }
    expect(exported).not.toMatch(/positive|neutral|negative|unrated/);
  });

  it("links a valid ticket ID to the matching Freshdesk ticket and Langfuse traces safely", async () => {
    server.use(
      http.get("/api/tickets", () =>
        HttpResponse.json({
          items: [
            {
              ticket_id: "6991254",
              opened_at: "2026-07-20T02:00:00Z",
              cohort_week: "2026-07-20",
              cohort_status: "complete",
              is_weekend_start: false,
              outcome: "ai_end_to_end",
              ai_first: true,
              transferred: false,
              reopen_lifetime: 0,
              reopen_within_7d: 0,
              ai_reply_count: 1,
              turn_count: 2,
              gt4_turn: false,
              issue_category: "Thanh toán",
              app: "Zalopay",
              product_code: "IBFT",
              skill: null,
              intent: null,
              tpe_code: null,
              tpe_status: null,
              guardrail_rule: null,
              transfer_reason: null,
              escalation_guard_blocked: false,
              csat_satisfaction: null,
              data_quality: "valid",
              model_core: null,
            },
          ],
          page: 1,
          page_size: 50,
          total: 1,
        }),
      ),
    );

    renderWithQuery(
      <TicketExplorer
        snapshot={baseSnapshot}
        weekDefinition="mon_sun"
        enabled
        filters={EMPTY_TICKET_FILTERS}
        onFiltersChange={() => {}}
      />,
    );

    const freshdeskLink = await screen.findByRole("link", {
      name: "Mở ticket 6991254 trên Freshdesk trong thẻ mới",
    });
    expect(freshdeskLink).toHaveTextContent("6991254");
    expect(freshdeskLink).toHaveAttribute(
      "href",
      "https://vngzalopay.freshdesk.com/a/tickets/6991254",
    );
    expect(freshdeskLink).toHaveAttribute("target", "_blank");
    expect(freshdeskLink).toHaveAttribute("rel", "noopener noreferrer");

    const langfuseLink = screen.getByRole("link", {
      name: "Mở các trace của ticket 6991254 trên Langfuse trong thẻ mới",
    });
    expect(langfuseLink).not.toHaveTextContent("Langfuse");
    expect(langfuseLink).toHaveAttribute(
      "href",
      "https://langfuse.zalopay.vn/project/cmqubjzur000hz507ptubh2l9/traces?filter=sessionId%3BstringOptions%3B%3Bany%20of%3B6991254&dateRange=1784480400000-1785344399999",
    );
    expect(langfuseLink).toHaveAttribute("target", "_blank");
    expect(langfuseLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(langfuseLink).toHaveAttribute(
      "title",
      "Mở Tracing của ticket 6991254 trên Langfuse",
    );
    const langfuseIcon = langfuseLink.querySelector("img");
    expect(langfuseIcon).not.toBeNull();
    expect(langfuseIcon).toHaveAttribute("alt", "");
    expect(langfuseIcon).toHaveAttribute("aria-hidden", "true");
    expect(langfuseIcon?.getAttribute("src")).toContain("langfuse-icon.svg");

    // "Vì sao?" opens the WhyDrawer in place -- it must never navigate via
    // hash, unlike the Freshdesk/Langfuse links right next to it.
    const whyButton = screen.getByRole("button", {
      name: "Xem giải thích vì sao agent xử lý ticket 6991254",
    });
    expect(whyButton).toHaveTextContent("Vì sao?");
  });

  it("keeps the Vì sao? link next to Freshdesk/Langfuse even for malformed IDs it must hide for", () => {
    const { container } = render(
      <TicketIdentifier
        ticketId="ticket-6991254"
        traceRangeStart="2026-07-20"
        traceRangeEnd="2026-07-29T11:27:00Z"
        onOpenWhy={() => {}}
      />,
    );

    expect(container.textContent).toBe("ticket-6991254");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("uses the oldest snapshot week instead of a fixed relative Tracing range", () => {
    render(
      <TicketIdentifier
        ticketId="7007908"
        traceRangeStart="2025-01-06"
        traceRangeEnd="2026-07-30T19:45:29.032021Z"
        onOpenWhy={() => {}}
      />,
    );

    expect(
      screen.getByRole("link", {
        name: "Mở các trace của ticket 7007908 trên Langfuse trong thẻ mới",
      }),
    ).toHaveAttribute(
      "href",
      "https://langfuse.zalopay.vn/project/cmqubjzur000hz507ptubh2l9/traces?filter=sessionId%3BstringOptions%3B%3Bany%20of%3B7007908&dateRange=1736096400000-1785517199999",
    );
  });

  it.each(["ticket-6991254", "6991254 ", "06991254", "0"])(
    "keeps malformed ticket ID %s as plain text",
    (ticketId) => {
      const { container } = render(
        <TicketIdentifier
          ticketId={ticketId}
          traceRangeStart="2026-07-20"
          traceRangeEnd="2026-07-29T11:27:00Z"
          onOpenWhy={() => {}}
        />,
      );

      expect(container.textContent).toBe(ticketId);
      expect(screen.queryByRole("link")).toBeNull();
    },
  );

  it("persists only allowlisted columns and reports an empty result honestly", async () => {
    const user = userEvent.setup();
    renderWithQuery(
      <TicketExplorer
        snapshot={baseSnapshot}
        weekDefinition="mon_sun"
        enabled
        filters={EMPTY_TICKET_FILTERS}
        onFiltersChange={() => {}}
      />,
    );

    expect(
      await screen.findByText("Không có ticket nào khớp bộ lọc hiện tại."),
    ).toBeVisible();
    expect(
      screen.queryByText(/mã số hợp lệ vẫn được tính trong KPI/),
    ).toBeNull();
    expect(document.getElementById("tickets")).not.toHaveTextContent(
      /session|trace ID|observation ID|prompt/i,
    );

    await user.click(screen.getByText("Chọn cột hiển thị"));
    await user.click(screen.getByRole("checkbox", { name: "App" }));

    const stored: unknown = JSON.parse(
      localStorage.getItem(TICKET_COLUMN_STORAGE_KEY) ?? "null",
    );
    expect(stored).toContain("app");
    expect(stored).not.toContain("trace_id");
  });

  it("surfaces quick filters and a locally scoped active-filter list", async () => {
    const user = userEvent.setup();

    function ControlledTicketExplorer() {
      const [filters, setFilters] = useState<TicketFilters>(EMPTY_TICKET_FILTERS);
      return (
        <TicketExplorer
          snapshot={baseSnapshot}
          weekDefinition="mon_sun"
          enabled
          filters={filters}
          onFiltersChange={setFilters}
        />
      );
    }

    renderWithQuery(<ControlledTicketExplorer />);

    await user.click(
      screen.getByRole("button", { name: ">3 lượt xử lý chưa chuyển" }),
    );

    const explorerChips = screen.getByRole("region", {
      name: "Bộ lọc đang áp dụng trong Ticket Explorer",
    });
    expect(explorerChips).toHaveTextContent(">3 lượt xử lý: Có");
    expect(explorerChips).toHaveTextContent("Đã chuyển CS: Không");

    await user.click(
      screen.getByRole("button", {
        name: "Bỏ lọc >3 lượt xử lý: Có (Ticket Explorer)",
      }),
    );
    expect(explorerChips).toHaveTextContent("Đã chuyển CS: Không");
    expect(explorerChips).not.toHaveTextContent(">3 lượt xử lý: Có");

    const intentInput = screen.getByRole("combobox", { name: "Intent" });
    expect(intentInput).toHaveAttribute("list", "intentOptions");
    expect(intentInput.closest("label")).not.toBeNull();
    expect(
      screen.queryByText(/giá trị intent, nhiều biến thể viết khác nhau/),
    ).toBeNull();
    expect(screen.queryByText(/tăng dần|giảm dần/)).toBeNull();
  });

  it("puts an explicit observed-week filter first in Ticket Explorer", async () => {
    const user = userEvent.setup();
    const snapshot = snapshotWithWeeks([
      weekRow({ cohort_week: "2026-07-06", has_data: true }),
      weekRow({ cohort_week: "2026-07-13", has_data: false }),
      weekRow({ cohort_week: "2026-07-20", has_data: true }),
    ]);

    function ControlledTicketExplorer() {
      const [filters, setFilters] = useState<TicketFilters>(EMPTY_TICKET_FILTERS);
      return (
        <TicketExplorer
          snapshot={snapshot}
          weekDefinition="mon_sun"
          enabled
          filters={filters}
          onFiltersChange={setFilters}
        />
      );
    }

    renderWithQuery(<ControlledTicketExplorer />);

    const filterGrid = document.getElementById("ticketFilters");
    expect(filterGrid).not.toBeNull();
    const firstField = filterGrid?.firstElementChild as HTMLElement;
    const weekFilter = within(firstField).getByRole("combobox", {
      name: "Tuần",
    });
    expect(
      within(weekFilter)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Tất cả tuần", "20/07–26/07", "06/07–12/07"]);

    await user.selectOptions(weekFilter, "2026-07-06");
    expect(
      screen.getByRole("region", {
        name: "Bộ lọc đang áp dụng trong Ticket Explorer",
      }),
    ).toHaveTextContent("Tuần: 06/07–12/07");
  });

  it("translates data-quality enums before rendering or exporting them", async () => {
    localStorage.setItem(
      TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["ticket_id", "data_quality"]),
    );
    server.use(
      http.get("/api/tickets", () =>
        HttpResponse.json({
          items: [
            {
              ticket_id: "123456",
              opened_at: "2026-07-20T02:00:00Z",
              cohort_week: "2026-07-20",
              cohort_status: "complete",
              is_weekend_start: false,
              outcome: "ai_end_to_end",
              ai_first: true,
              transferred: false,
              reopen_lifetime: 0,
              reopen_within_7d: 0,
              ai_reply_count: 1,
              turn_count: 2,
              gt4_turn: false,
              issue_category: "Thanh toán",
              app: "Zalopay",
              product_code: "IBFT",
              skill: null,
              intent: null,
              tpe_code: null,
              tpe_status: null,
              guardrail_rule: null,
              transfer_reason: null,
              escalation_guard_blocked: false,
              csat_satisfaction: null,
              data_quality: "missing_turn0",
              model_core: null,
            },
          ],
          page: 1,
          page_size: 50,
          total: 1,
        }),
      ),
    );

    renderWithQuery(
      <TicketExplorer
        snapshot={baseSnapshot}
        weekDefinition="mon_sun"
        enabled
        filters={EMPTY_TICKET_FILTERS}
        onFiltersChange={() => {}}
      />,
    );

    expect(await screen.findByText("Thiếu lượt trả lời đầu tiên")).toBeVisible();
    expect(screen.queryByText("missing_turn0")).toBeNull();
  });
});

describe("selectors", () => {
  it("never compares against a week-to-date row", () => {
    const snapshot = snapshotWithWeeks([
      weekRow({ cohort_week: "2026-07-06" }),
      weekRow({ cohort_week: "2026-07-13", cohort_status: "wtd" }),
      weekRow({ cohort_week: "2026-07-20" }),
    ]);
    const view = selectView(snapshot, "mon_sun");

    expect(selectPreviousWeek(view, selectLatestWeek(view))?.cohort_week).toBe(
      "2026-07-06",
    );
  });

  it("raises only actionable warnings, each with a next step", () => {
    const items = selectAttentionItems(baseSnapshot, "mon_sun");

    expect(items.map((item) => item.id)).toContain("attention-gt4");
    expect(items.every((item) => item.action.length > 0)).toBe(true);
  });
});
