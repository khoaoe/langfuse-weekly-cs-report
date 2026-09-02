import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";

import { BelowFold } from "../src/components/BelowFold";
import { WeeklyReport } from "../src/components/WeeklyReport";
import { TicketExplorer } from "../src/components/TicketExplorer";
import { EMPTY_TICKET_FILTERS } from "../src/lib/dashboard-filters";
import {
  DashboardEnvelopeSchema,
  type DashboardSnapshot,
  type WeeklyReportRow,
} from "../src/lib/dashboard-schema";
import { dashboardEnvelopeFixture } from "./fixtures/dashboard";
import { server } from "./msw/server";

const baseSnapshot = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture)
  .snapshot as DashboardSnapshot;

function renderWithQuery(element: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{element}</QueryClientProvider>,
  );
}

function rowHeaders(table: HTMLElement): string[] {
  return within(table)
    .getAllByRole("rowheader")
    .map((cell) => cell.textContent?.trim() ?? "");
}

// The TPE table's row header (first column) is now the governed Trạng thái
// label, not the Transstatus code — this reads the Transstatus column
// (second column) directly to check sort order on the exact-source code.
function transstatusCells(table: HTMLElement): string[] {
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0]?.textContent?.trim() ?? "");
}

function weekRow(
  cohortWeek: string,
  totalTickets: number,
): WeeklyReportRow {
  const template = baseSnapshot.views.mon_sun.weekly[0] as WeeklyReportRow;
  return {
    ...template,
    cohort_week: cohortWeek,
    total_tickets: totalTickets,
  };
}

function snapshotWithWeekly(
  weekly: readonly WeeklyReportRow[],
): DashboardSnapshot {
  return {
    ...baseSnapshot,
    views: {
      ...baseSnapshot.views,
      mon_sun: {
        ...baseSnapshot.views.mon_sun,
        weekly: [...weekly],
      },
    },
  };
}

function analysisSnapshot(): DashboardSnapshot {
  const issueCategory = {
    "Nhóm 10": { total: 4, ai_first: 1, transferred: 2, reopen: 0 },
    "Nhóm 2": { total: 4, ai_first: 3, transferred: 1, reopen: 2 },
    "Áp dụng": { total: 2, ai_first: 2, transferred: 0, reopen: 1 },
  };
  const transferReasons = {
    observed_transfer_denominator: 12,
    triggers: [
      {
        reason: "out_of_scope" as const,
        rule: "off_topic" as const,
        source: "input_guardrail" as const,
        stage: null,
        skill: null,
        count: 4,
      },
      {
        reason: "skill_suggested_transfer" as const,
        rule: "cs_escalation" as const,
        source: "skill_guardrail_checked" as const,
        stage: "output" as const,
        skill: "topup",
        count: 4,
      },
      {
        reason: "missing_transaction_id" as const,
        rule: "missing_transaction_id" as const,
        source: "skill_guardrail_checked" as const,
        stage: "input" as const,
        skill: "interbank-fund-transfer",
        count: 2,
      },
      {
        reason: "max_replies_exceeded" as const,
        rule: "max_replies_exceeded" as const,
        source: "input_guardrail" as const,
        stage: null,
        skill: null,
        count: 2,
      },
    ],
    step_result_missing: { count: 5, denominator: 12 },
    tpe: [
      {
        transstatus: "-383",
        step_result: "-1013",
        count: 2,
        status: null,
      },
      {
        transstatus: "-2",
        step_result: null,
        count: 5,
        status: null,
      },
      {
        transstatus: "-10",
        step_result: "-1006",
        count: 5,
        status: null,
      },
    ],
    guardrail: [
      { rule: "missing_transaction_id" as const, count: 2 },
      { rule: "off_topic" as const, count: 5 },
      { rule: "cs_escalation" as const, count: 5 },
    ],
    escalation_guard_blocked: { count: 1, denominator: 12 },
  };

  const segments = {
    ...baseSnapshot.views.mon_sun.segments,
    issue_category: issueCategory,
  };
  const latestWeek = baseSnapshot.views.mon_sun.weekly[0]?.cohort_week ?? "";

  return {
    ...baseSnapshot,
    views: {
      ...baseSnapshot.views,
      mon_sun: {
        ...baseSnapshot.views.mon_sun,
        segments,
        transfer_reasons: transferReasons,
        // Kept in sync with the latest week's by_week entry, mirroring the
        // production invariant that every observed week carries its own
        // segments/transfer_reasons — this dashboard now reads that entry by
        // default instead of the whole-range totals.
        by_week: { [latestWeek]: { segments, transfer_reasons: transferReasons } },
      },
    },
  };
}

function belowFold(snapshot: DashboardSnapshot) {
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
    />
  );
}

describe("sorting bảng dữ liệu", () => {
  it("shows the ticket-opened date and time and delegates its sort to the backend", async () => {
    const requestedSorts: string[] = [];
    server.use(
      http.get("/api/tickets", ({ request }) => {
        requestedSorts.push(new URL(request.url).searchParams.get("sort_by") ?? "");
        return HttpResponse.json({
          items: [
            {
              ticket_id: "7000001",
              opened_at: "2026-07-20T02:00:00Z",
              cohort_week: "2026-07-20",
              cohort_status: "complete",
              is_weekend_start: false,
              outcome: "ai_then_cs",
              ai_first: true,
              transferred: true,
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
              transfer_reason: "max_replies_exceeded",
              escalation_guard_blocked: false,
              csat_satisfaction: "positive",
              data_quality: "valid",
              model_core: null,
            },
          ],
          page: 1,
          page_size: 50,
          total: 1,
        });
      }),
    );
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

    const openedAt = await screen.findByText(/20\/7\/26/);
    expect(openedAt).toHaveTextContent("09:00");
    expect(openedAt.tagName).toBe("TIME");
    expect(openedAt).toHaveAttribute("datetime", "2026-07-20T02:00:00Z");
    expect(screen.getByText("Khách tiếp tục hỏi sau 3 phản hồi AI")).toBeVisible();

    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo Lý do chuyển CS/ }),
    );
    await waitFor(() => expect(requestedSorts.at(-1)).toBe("transfer_reason"));

    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo Thời gian mở/ }),
    );
    await waitFor(() => expect(requestedSorts.at(-1)).toBe("opened_at"));
    expect(
      screen.getByRole("columnheader", { name: /Thời gian mở/ }),
    ).toHaveAttribute("aria-sort", "ascending");
  });

  it("requests semantic satisfaction sorting from the Ticket Explorer backend", async () => {
    const user = userEvent.setup();
    const requestedSorts: string[] = [];
    server.use(
      http.get("/api/tickets", ({ request }) => {
        requestedSorts.push(new URL(request.url).searchParams.get("sort_by") ?? "");
        return HttpResponse.json({ items: [], page: 1, page_size: 50, total: 0 });
      }),
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

    await user.click(await screen.findByRole("button", {
      name: /Sắp xếp theo CSAT/,
    }));
    await waitFor(() => expect(requestedSorts.at(-1)).toBe("csat_satisfaction"));
  });
  it("sorts the weekly report by raw numeric values without changing governed export order", async () => {
    const user = userEvent.setup();
    const snapshot = snapshotWithWeekly([
      weekRow("2026-07-06", 10),
      weekRow("2026-07-13", 20),
      weekRow("2026-07-20", 5),
    ]);
    renderWithQuery(
      <WeeklyReport snapshot={snapshot} weekDefinition="mon_sun" />,
    );

    const table = screen.getByRole("table", { name: /Báo cáo tuần/ });
    expect(rowHeaders(table)).toEqual([
      "20/07–26/07",
      "13/07–19/07",
      "06/07–12/07",
    ]);
    expect(
      within(table).getByRole("columnheader", { name: /Tuần/ }),
    ).toHaveAttribute("aria-sort", "descending");
    expect(
      within(table).getByRole("button", {
        name: "Sắp xếp theo Tuần; hiện giảm dần, bấm để tăng dần",
      }),
    ).toHaveAccessibleDescription(
      "Đang giảm dần; nhấn để chuyển sang tăng dần.",
    );

    await user.click(
      within(table).getByRole("button", {
        name: /Sắp xếp theo Tổng ticket/,
      }),
    );
    expect(
      within(table).getByRole("columnheader", { name: /Tổng ticket/ }),
    ).toHaveAttribute("aria-sort", "descending");
    expect(
      within(table).getByRole("button", {
        name: /Sắp xếp theo Tổng ticket/,
      }),
    ).toHaveAccessibleDescription(
      "Đang giảm dần; nhấn để chuyển sang tăng dần.",
    );
    expect(rowHeaders(table)).toEqual([
      "13/07–19/07",
      "06/07–12/07",
      "20/07–26/07",
    ]);

    await user.click(
      within(table).getByRole("button", {
        name: /Sắp xếp theo Tổng ticket/,
      }),
    );
    expect(rowHeaders(table)).toEqual([
      "20/07–26/07",
      "06/07–12/07",
      "13/07–19/07",
    ]);

    await user.click(screen.getByRole("button", { name: "Chép TSV" }));
    const exportedWeeks = (await navigator.clipboard.readText())
      .split("\n")
      .slice(1)
      .map((line) => line.split("\t")[0]);
    expect(exportedWeeks).toEqual([
      "20/07–26/07",
      "13/07–19/07",
      "06/07–12/07",
    ]);
    expect(
      screen.getByText(/TSV và CSV vẫn giữ thứ tự tuần mới nhất/),
    ).toBeVisible();
  });

  it("mentions the export order only while a non-default sort is applied", () => {
    renderWithQuery(
      <WeeklyReport snapshot={baseSnapshot} weekDefinition="mon_sun" />,
    );

    // On the default newest-first sort the export matches what is on screen,
    // so the caveat describes nothing and would be one more line to read past.
    expect(
      screen.queryByText(/TSV và CSV vẫn giữ thứ tự tuần mới nhất/),
    ).toBeNull();
    // Conventions the reader can see — the WTD marker, the empty-week label —
    // do not need a paragraph restating them.
    expect(
      screen.queryByText(/Tuần đang chạy \(WTD\) được đánh dấu riêng/),
    ).toBeNull();
    expect(screen.queryByText(/đủ 14 cột/)).toBeNull();
  });

  it("resets a hidden weekly sort when the mobile column set is collapsed", async () => {
    const user = userEvent.setup();
    renderWithQuery(
      <WeeklyReport snapshot={baseSnapshot} weekDefinition="mon_sun" />,
    );

    const table = screen.getByRole("table", { name: /Báo cáo tuần/ });
    await user.click(screen.getByRole("button", { name: "Xem đủ cột" }));
    await user.click(
      within(table).getByRole("button", {
        name: /Sắp xếp theo AI xử lý trọn/,
      }),
    );
    expect(
      within(table).getByRole("columnheader", { name: /AI xử lý trọn/ }),
    ).toHaveAttribute("aria-sort", "descending");

    await user.click(screen.getByRole("button", { name: "Rút gọn cột" }));
    expect(
      within(table).getByRole("columnheader", { name: /Tuần/ }),
    ).toHaveAttribute("aria-sort", "descending");
  });

  it("sorts segment rows by natural labels and raw metrics", async () => {
    const user = userEvent.setup();
    renderWithQuery(belowFold(analysisSnapshot()));

    const table = screen.getByRole("table", {
      name: /Xếp theo số ca chuyển CS nhiều nhất/,
    });
    expect(document.getElementById("segmentCaption")).toHaveTextContent(
      "Xếp theo số ca chuyển CS nhiều nhất. Ticket: tỷ trọng trong tuần. AI First, Chuyển CS, Reopen: tỷ lệ trong chính nhóm đó. Nhóm dưới 20 ticket chỉ hiện số ca, không hiện tỷ lệ.",
    );
    expect(document.getElementById("segmentCaption")).not.toHaveTextContent(
      /tăng dần|giảm dần|Đang sắp xếp/,
    );
    // Default rank is CS handoffs caused, so the segment to fix comes first.
    expect(
      within(table).getByRole("columnheader", { name: /Chuyển CS/ }),
    ).toHaveAttribute("aria-sort", "descending");
    expect(rowHeaders(table)).toEqual(["Nhóm 10", "Nhóm 2", "Áp dụng"]);

    await user.click(
      within(table).getByRole("button", { name: /Sắp xếp theo Giá trị/ }),
    );
    expect(
      within(table).getByRole("columnheader", { name: /Giá trị/ }),
    ).toHaveAttribute("aria-sort", "ascending");
    expect(rowHeaders(table)).toEqual(["Áp dụng", "Nhóm 2", "Nhóm 10"]);

    await user.click(
      within(table).getByRole("button", { name: /Sắp xếp theo AI First/ }),
    );
    expect(rowHeaders(table)).toEqual(["Nhóm 2", "Áp dụng", "Nhóm 10"]);
  });

  it("sorts TPE rows by signed code, raw step result, and ticket count", async () => {
    const user = userEvent.setup();
    renderWithQuery(belowFold(analysisSnapshot()));

    const region = screen.getByRole("region", {
      name: "Transstatus và Step result",
    });
    await user.click(
      within(region).getByRole("heading", { name: "Transstatus và Step result" }),
    );
    const table = within(region).getByRole("table", {
      name: "Transstatus và Step result",
    });
    expect(within(region).queryByText(/tăng dần|giảm dần|Đang sắp xếp/)).toBeNull();
    expect(
      within(table).getByRole("columnheader", { name: /Ticket/ }),
    ).toHaveAttribute("aria-sort", "descending");
    expect(transstatusCells(table)).toEqual(["-10", "-2", "-383"]);

    await user.click(
      within(table).getByRole("button", { name: /Sắp xếp theo Transstatus/ }),
    );
    expect(transstatusCells(table)).toEqual(["-383", "-10", "-2"]);

    await user.click(
      within(table).getByRole("button", { name: /Sắp xếp theo Step result/ }),
    );
    expect(transstatusCells(table)).toEqual(["-383", "-10", "-2"]);
  });

  it("sorts transfer reasons and shows exact source values for CS and Dev", async () => {
    const user = userEvent.setup();
    renderWithQuery(belowFold(analysisSnapshot()));

    const table = within(
      screen.getByRole("region", {
        name: "Lý do chuyển CS",
      }),
    ).getByRole("table", {
      name: "Lý do chuyển CS",
    });
    expect(rowHeaders(table)).toEqual([
      "Bộ kiểm tra xác định nội dung ngoài phạm vi hỗ trợ",
      "Skill đề xuất chuyển CS",
      "Khách tiếp tục hỏi sau 3 phản hồi AI",
      "Skill cần mã giao dịch nhưng ticket chưa có",
    ]);
    expect(within(table).getByText("off_topic")).toBeVisible();
    expect(within(table).getByText("cs_escalation")).toBeVisible();
    expect(
      within(table).getAllByText("skill_guardrail_checked · stage=output"),
    ).toHaveLength(1);
    expect(
      within(table).getByRole("columnheader", { name: /Ticket/ }),
    ).toHaveAttribute("aria-sort", "descending");
    expect(
      within(table).getAllByRole("button", { name: /^Sắp xếp theo/ }),
    ).toHaveLength(6);

    await user.click(
      within(table).getByRole("button", { name: /Sắp xếp theo Lý do chuyển CS/ }),
    );
    expect(rowHeaders(table)).toEqual([
      "Bộ kiểm tra xác định nội dung ngoài phạm vi hỗ trợ",
      "Khách tiếp tục hỏi sau 3 phản hồi AI",
      "Skill cần mã giao dịch nhưng ticket chưa có",
      "Skill đề xuất chuyển CS",
    ]);
  });
});
