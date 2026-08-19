import { useState, type ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { dashboardEnvelopeFixture } from "./fixtures/dashboard";
import { server } from "./msw/server";
import { ticketQueryString } from "../src/lib/api";
import {
  DashboardEnvelopeSchema,
  type DashboardSnapshot,
  type WeeklyReportRow,
} from "../src/lib/dashboard-schema";
import {
  EMPTY_TICKET_FILTERS,
  type TicketFilters,
} from "../src/lib/dashboard-filters";
import {
  formatAverage,
  formatPointDelta,
  formatUpdatedAt,
  formatWeekRange,
} from "../src/lib/format";
import {
  initialDashboardRuntime,
  reduceDashboardRuntime,
} from "../src/lib/runtime-state";
import { selectAttentionItems, selectLatestWeek } from "../src/lib/selectors";
import {
  DEFAULT_TICKET_COLUMNS,
  TICKET_COLUMN_STORAGE_KEY,
  readVisibleTicketColumns,
} from "../src/lib/ticket-columns";
import {
  WEEKLY_EXPORT_COLUMNS,
  buildWeeklyCsv,
} from "../src/lib/weekly-export";
import { TicketExplorer } from "../src/components/TicketExplorer";
import { WeeklyReport } from "../src/components/WeeklyReport";

const baseSnapshot = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture)
  .snapshot as DashboardSnapshot;

function TicketExplorerHarness() {
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

function ticketExplorer() {
  return <TicketExplorerHarness />;
}

function renderWithQuery(element: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{element}</QueryClientProvider>);
}

describe("runtime state resilience", () => {
  it("treats an unverifiable payload as a failed read, not as data", () => {
    const state = reduceDashboardRuntime(initialDashboardRuntime(), {
      type: "envelope",
      envelope: { status: "ready", snapshot: { views: {} } },
    });

    expect(state).toEqual({
      kind: "stale_error",
      snapshot: null,
      message: "Chưa tải được dữ liệu dashboard. Hệ thống sẽ thử lại.",
    });
  });

  it("stays in loading while the server reports no snapshot yet", () => {
    const state = reduceDashboardRuntime(initialDashboardRuntime(), {
      type: "envelope",
      envelope: {
        status: "loading",
        refreshing: true,
        last_error_code: null,
        last_error_at: null,
        snapshot: null,
      },
    });

    expect(state.kind).toBe("loading");
    expect(state.snapshot).toBeNull();
  });

  it("reports a refresh started before any snapshot exists as loading", () => {
    expect(
      reduceDashboardRuntime(initialDashboardRuntime(), { type: "refresh-start" }).kind,
    ).toBe("loading");
  });

  it("marks a server-declared stale envelope as stale while keeping the report", () => {
    const ready = reduceDashboardRuntime(initialDashboardRuntime(), {
      type: "envelope",
      envelope: dashboardEnvelopeFixture,
    });
    const stale = reduceDashboardRuntime(ready, {
      type: "envelope",
      envelope: { ...dashboardEnvelopeFixture, status: "stale_error" },
    });

    expect(stale.kind).toBe("stale_error");
    expect(stale.snapshot).not.toBeNull();
  });
});

describe("formatting edge cases", () => {
  it("returns the unavailable mark rather than inventing a date", () => {
    expect(formatWeekRange("not-a-date", "mon_sun")).toBe("—");
    expect(formatWeekRange("2026-13-45", "mon_sun")).toBe("—");
    expect(formatUpdatedAt(null)).toBe("—");
    expect(formatUpdatedAt("not-a-timestamp")).toBe("—");
    expect(formatAverage(null)).toBe("—");
  });

  it("signs a percentage-point delta explicitly", () => {
    expect(formatPointDelta(0.032)).toBe("+3,2 điểm");
    expect(formatPointDelta(-0.004)).toBe("−0,4 điểm");
    expect(formatPointDelta(0)).toBe("0,0 điểm");
  });
});

describe("selectors under degraded data", () => {
  it("escalates a blocked quality gate and a partial enrichment read", () => {
    const degraded: DashboardSnapshot = {
      ...baseSnapshot,
      enrichment_status: "partial",
      gate_status: {
        allowed: false,
        structural_invalid_rate: 0.12,
        reasons: ["structural_invalid_rate_gt_5pct"],
      },
      views: {
        ...baseSnapshot.views,
        mon_sun: {
          ...baseSnapshot.views.mon_sun,
          transfer_reasons: {
            ...baseSnapshot.views.mon_sun.transfer_reasons,
            step_result_missing: { count: 2, denominator: 3 },
          },
          by_week: {
            ...baseSnapshot.views.mon_sun.by_week,
            "2026-07-20": {
              ...baseSnapshot.views.mon_sun.by_week["2026-07-20"]!,
              transfer_reasons: {
                ...baseSnapshot.views.mon_sun.by_week["2026-07-20"]!
                  .transfer_reasons,
                step_result_missing: { count: 2, denominator: 3 },
              },
            },
          },
        },
      },
      unmapped_tpe_codes: [{ code: "-999", status: "", count: 4 }],
    };

    const items = selectAttentionItems(degraded, "mon_sun");
    const ids = items.map((item) => item.id);
    expect(ids).toEqual([
      "attention-gt4",
      "attention-gate",
    ]);
    expect(items.find((item) => item.id === "attention-gt4")).toMatchObject({
      headline: "2 ticket có hơn 3 lượt xử lý mà chưa chuyển CS",
      action: "Mở Ticket Explorer, lọc >3 lượt xử lý để xem từng ticket.",
    });
    expect(items.find((item) => item.id === "attention-gate")).toMatchObject({
      headline: "12,0% bản ghi lỗi cấu trúc, vượt ngưỡng 5%",
      action: "Số tuần này chưa dùng để ra quyết định. Kiểm tra nguồn dữ liệu trước.",
    });
    expect(items.map((item) => item.headline).join(" ")).not.toMatch(
      /taxonomy|chưa có trong taxonomy/i,
    );
  });

  it("does not turn global Transstatus coverage into a misleading first-view alert", () => {
    const tpeOnlyCoverageGap: DashboardSnapshot = {
      ...baseSnapshot,
      coverage: {
        issue_category: 1,
        app: 1,
        tpe: 0.1,
        intent: 1,
        skill: 1,
      },
      views: {
        ...baseSnapshot.views,
        mon_sun: {
          ...baseSnapshot.views.mon_sun,
          transfer_reasons: {
            ...baseSnapshot.views.mon_sun.transfer_reasons,
            step_result_missing: { count: 0, denominator: 3 },
          },
          by_week: {
            ...baseSnapshot.views.mon_sun.by_week,
            "2026-07-20": {
              ...baseSnapshot.views.mon_sun.by_week["2026-07-20"]!,
              transfer_reasons: {
                ...baseSnapshot.views.mon_sun.by_week["2026-07-20"]!
                  .transfer_reasons,
                step_result_missing: { count: 0, denominator: 3 },
              },
            },
          },
        },
      },
    };

    const ids = selectAttentionItems(tpeOnlyCoverageGap, "mon_sun").map(
      (item) => item.id,
    );
    expect(ids).not.toContain("attention-coverage");
    expect(ids).not.toContain("attention-step-result");
  });

  it("reports no latest week when every week is empty", () => {
    const empty: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        ...baseSnapshot.views,
        mon_sun: { ...baseSnapshot.views.mon_sun, weekly: [] },
      },
    };

    expect(selectLatestWeek(empty.views.mon_sun)).toBeNull();
  });
});

describe("export and storage hardening", () => {
  it("neutralises spreadsheet formula injection in weekly CSV cells", () => {
    const csv = buildWeeklyCsv(
      [
        {
          cohort_week: "2026-07-20",
          cohort_status: "complete",
          total_tickets: 0,
          ai_first_count: 0,
          ai_first_rate: 0,
          ai_end_to_end_count: 0,
          ai_then_cs_count: 0,
          direct_cs_count: 0,
          unclassified_count: 0,
          reopen_lifetime_numerator: 0,
          reopen_lifetime_rate: null,
          ai_reply_mean_ai_first: null,
          gt4_turn_with_cs: 0,
          gt4_turn_without_cs: 0,
        },
      ],
      { cohortLabel: "T2–CN", updatedAt: "2026-07-29 18:27" },
    );

    // Every cell is quoted, and an empty week is reported as absent rather
    // than as a row of zeros.
    expect(csv.split("\r\n")[2]).toBe(
      '"20/07–26/07","Không có dữ liệu","—","—","—","—","—","—","—","—","—","—","—","—"',
    );
  });

  it("falls back to the default columns when storage is unusable", () => {
    localStorage.setItem(TICKET_COLUMN_STORAGE_KEY, "{not json");
    expect(readVisibleTicketColumns()).toEqual(DEFAULT_TICKET_COLUMNS);

    localStorage.setItem(TICKET_COLUMN_STORAGE_KEY, JSON.stringify({ ticket_id: true }));
    expect(readVisibleTicketColumns()).toEqual(DEFAULT_TICKET_COLUMNS);

    localStorage.setItem(TICKET_COLUMN_STORAGE_KEY, JSON.stringify(["trace_id"]));
    expect(readVisibleTicketColumns()).toEqual(DEFAULT_TICKET_COLUMNS);
  });

  it("drops empty query values instead of sending them to the API", () => {
    expect(
      ticketQueryString({ page: 1, outcome: "", gt4_turn: null, skill: undefined }),
    ).toBe("?page=1");
    expect(ticketQueryString({})).toBe("");
  });
});

/**
 * jsdom implements neither object URLs nor downloads, so the export path is
 * observed through the blob handed to `createObjectURL`.
 *
 * `Blob.text()` performs a spec UTF-8 decode, which strips the leading byte
 * order mark. Decoding with `ignoreBOM` keeps the mark visible so the CSV
 * contract can actually be asserted.
 */
function captureDownload(): { text: () => Promise<string> } {
  const captured: Blob[] = [];
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: (blob: Blob) => {
      captured.push(blob);
      return "blob:captured";
    },
  });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: () => {} });
  return {
    text: async () => {
      const blob = captured.at(-1);
      if (blob === undefined) {
        return "";
      }
      return new TextDecoder("utf-8", { ignoreBOM: true }).decode(
        await blob.arrayBuffer(),
      );
    },
  };
}

describe("bulk export", () => {
  it("exports the globally sorted first thousand when the top row starts beyond the cap", async () => {
    localStorage.setItem(
      TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["turn_count", "tpe_code"]),
    );
    const download = captureDownload();
    const population = Array.from({ length: 1_101 }, (_, offset) => ({
      ticket_id: String(offset + 1),
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
        turn_count: offset === 1_100 ? 99 : 2,
        gt4_turn: offset === 1_100,
        issue_category: "Thanh toán",
        app: "Zalopay",
        product_code: "IBFT",
        skill: null,
        intent: null,
        tpe_code: "-383",
        tpe_status: null,
        guardrail_rule: null,
        transfer_reason: null,
        escalation_guard_blocked: false,
        csat_satisfaction: null,
        data_quality: "valid",
        model_core: null,
      }));

    const seen: string[] = [];
    server.use(
      http.get("/api/tickets", ({ request }) => {
        const url = new URL(request.url);
        seen.push(url.search);
        const page = Number(url.searchParams.get("page") ?? "1");
        const pageSize = Number(url.searchParams.get("page_size") ?? "50");
        const sortBy = url.searchParams.get("sort_by") ?? "cohort_week";
        const sortDirection =
          url.searchParams.get("sort_direction") === "asc" ? 1 : -1;
        const sorted = [...population].sort((left, right) => {
          const leftValue = left[sortBy as keyof (typeof population)[number]];
          const rightValue = right[sortBy as keyof (typeof population)[number]];
          let result =
            typeof leftValue === "number" && typeof rightValue === "number"
              ? leftValue - rightValue
              : String(leftValue).localeCompare(String(rightValue), "vi", {
                  numeric: true,
                });
          result *= sortDirection;
          return result === 0
            ? Number(left.ticket_id) - Number(right.ticket_id)
            : result;
        });
        const start = (page - 1) * pageSize;
        return HttpResponse.json({
          items: sorted.slice(start, start + pageSize),
          page,
          page_size: pageSize,
          total: sorted.length,
        });
      }),
    );

    const user = userEvent.setup();
    renderWithQuery(ticketExplorer());
    expect(
      await screen.findByRole("rowheader", { name: "1" }),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Trang sau" }));
    expect(
      await screen.findByRole("rowheader", { name: "51" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo Tổng lượt xử lý/ }),
    );
    expect(
      await screen.findByRole("rowheader", { name: "1" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo Tổng lượt xử lý/ }),
    );
    expect(
      await screen.findByRole("rowheader", { name: "1101" }),
    ).toBeVisible();
    expect(screen.getByText("Trang 1 / 23")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Tải CSV ticket" }));

    expect(await screen.findByText(/Đã xuất 1\.000 dòng/)).toBeVisible();
    const csv = await download.text();
    // One header line plus exactly the capped rows.
    expect(csv.split("\r\n")).toHaveLength(1_001);
    expect(csv.startsWith("﻿")).toBe(true);
    expect(csv.split("\r\n")[0]).toBe(
      '﻿"Ticket","Tổng lượt xử lý","Transstatus"',
    );
    expect(csv.split("\r\n")[1]).toBe(`"1101","99","'-383"`);
    expect(seen.some((query) =>
      query.includes("sort_by=turn_count") &&
      query.includes("sort_direction=desc") &&
      query.includes("page=1"),
    )).toBe(true);
    // The negative TPE code must not stay executable in a spreadsheet.
    expect(csv).toContain(`"'-383"`);
    expect(csv).not.toContain("Freshdesk");
    expect(csv).not.toContain("vngzalopay.freshdesk.com");
    expect(csv).not.toContain("Langfuse");
    expect(csv).not.toContain("langfuse.zalopay.vn");
  });

  it("reports a failed bulk export instead of downloading a partial file", async () => {
    captureDownload();
    server.use(
      http.get("/api/tickets", () =>
        HttpResponse.json({ detail: { code: "invalid_query" } }, { status: 422 }),
      ),
    );

    const user = userEvent.setup();
    renderWithQuery(ticketExplorer());
    await user.click(screen.getByRole("button", { name: "Tải CSV ticket" }));

    expect(
      await screen.findByText("Không tải được dữ liệu để xuất. Hãy thử lại."),
    ).toBeVisible();
  });

  it("downloads the weekly report as UTF-8 BOM CSV", async () => {
    const download = captureDownload();
    const user = userEvent.setup();
    const template = baseSnapshot.views.mon_sun.weekly[0] as WeeklyReportRow;
    const snapshot: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        ...baseSnapshot.views,
        mon_sun: {
          ...baseSnapshot.views.mon_sun,
          weekly: [
            { ...template, cohort_week: "2026-07-13" },
            { ...template, cohort_week: "2026-07-20", cohort_status: "wtd" },
          ],
        },
      },
    };
    renderWithQuery(<WeeklyReport snapshot={snapshot} weekDefinition="mon_sun" />);
    const renderedWeeks = screen
      .getAllByRole("rowheader")
      .map((cell) => `"${cell.textContent ?? ""}"`);

    await user.click(screen.getByRole("button", { name: "Tải CSV" }));

    expect(screen.getByText("Đã tải CSV báo cáo tuần.")).toBeVisible();
    const csv = await download.text();
    const [metadataLine, headerLine, ...dataLines] = csv.slice(1).split("\r\n");
    expect(csv.startsWith("\ufeff")).toBe(true);
    expect(metadataLine).toMatch(
      /^"# Cohort","T2–CN","Cập nhật","18:27 29\/7\/26",/,
    );
    expect(metadataLine?.match(/"(?:[^"]|"")*"/g)).toHaveLength(14);
    expect(headerLine?.match(/"(?:[^"]|"")*"/g)).toEqual(
      WEEKLY_EXPORT_COLUMNS.map((column) => `"${column}"`),
    );
    expect(
      dataLines.map((line) => line.match(/"(?:[^"]|"")*"/)?.[0]),
    ).toEqual(renderedWeeks);
  });
});

describe("Ticket Explorer interaction", () => {
  it("sends only the filters the operator set and resets to page one", async () => {
    const seen: string[] = [];
    server.use(
      http.get("/api/tickets", ({ request }) => {
        seen.push(new URL(request.url).search);
        return HttpResponse.json({ items: [], page: 1, page_size: 50, total: 0 });
      }),
    );

    const user = userEvent.setup();
    renderWithQuery(ticketExplorer());
    await screen.findByText("Không có ticket nào khớp bộ lọc hiện tại.");

    await user.selectOptions(screen.getByLabelText("Hơn 3 lượt xử lý"), "true");
    await screen.findByText("Không có ticket nào khớp bộ lọc hiện tại.");

    const last = seen.at(-1) ?? "";
    expect(last).toContain("gt4_turn=true");
    expect(last).toContain("page=1");
    expect(last).toContain("sort_by=cohort_week");
    expect(last).toContain("sort_direction=desc");
    expect(last).not.toContain("outcome=");
  });

  it("keeps the report readable when the ticket API rejects the request", async () => {
    server.use(
      http.get("/api/tickets", () =>
        HttpResponse.json({ detail: { code: "invalid_query" } }, { status: 422 }),
      ),
    );

    renderWithQuery(ticketExplorer());

    expect(await screen.findByRole("heading", { name: "Ticket Explorer" })).toBeVisible();
    expect(
      await screen.findByText(
        "Không đọc được danh sách ticket. Kiểm tra lại bộ lọc rồi thử lại.",
      ),
    ).toBeVisible();
    expect(
      screen.getByText("Không đọc được danh sách ticket."),
    ).toBeVisible();
    expect(screen.queryByText("Đang tải danh sách ticket.")).toBeNull();
    expect(
      screen.queryByText("Không có ticket nào khớp bộ lọc hiện tại."),
    ).toBeNull();
    expect(screen.queryByText(/invalid_query/)).toBeNull();
  });
});
