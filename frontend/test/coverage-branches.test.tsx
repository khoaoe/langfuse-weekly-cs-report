import { useState, type ComponentProps, type ReactElement } from "react";
import {
  act,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "../src/components/AppShell";
import { BelowFold } from "../src/components/BelowFold";
import { DashboardScreen } from "../src/components/DashboardScreen";
import { TicketExplorer } from "../src/components/TicketExplorer";
import {
  DashboardEnvelopeSchema,
  type DashboardSnapshot,
  type Segments,
  type TicketRow,
  type TransferReasons,
} from "../src/lib/dashboard-schema";
import {
  EMPTY_TICKET_FILTERS,
  type TicketFilters,
} from "../src/lib/dashboard-filters";
import {
  calculateDataQualityScore,
  formatDataAge,
} from "../src/lib/data-quality-score";
import {
  TICKET_COLUMNS,
  TICKET_COLUMN_STORAGE_KEY,
} from "../src/lib/ticket-columns";
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

function shell(
  snapshot: DashboardSnapshot | null,
  overrides: Partial<ComponentProps<typeof AppShell>> = {},
) {
  return (
    <AppShell
      weekDefinition="mon_sun"
      onWeekDefinitionChange={() => {}}
      snapshot={snapshot}
      statusMessage=""
      onRefresh={() => {}}
      refreshDisabled={false}
      refreshHint="Có thể làm mới"
      runtimeKind={snapshot === null ? "loading" : "ready"}
      activeFilters={[]}
      onRemoveFilter={() => {}}
      onResetFilters={() => {}}
      {...overrides}
    >
      <section id="weekly">Tuần</section>
      <section id="tickets">Ticket</section>
    </AppShell>
  );
}

describe("App shell operating states", () => {
  it("marks the ready status with the dedicated success treatment", () => {
    render(shell({ ...baseSnapshot, generated_at: new Date().toISOString() }));

    const status = document.getElementById("statusChip");
    expect(status).toHaveAttribute("data-state", "ready");
    expect(status?.className).toMatch(/runtimeReady/);
  });

  it("never renders the retired per-dimension coverage badge or the quality chip", () => {
    // 2026-08-01-dashboard-clarity-round2-design.md retired `#dqBadge` (a
    // single mismatched-scope coverage dimension, e.g. "Skill: thiếu 38,7%
    // ticket"). Task 6 of the 2026-08-18 critique remediation later added a
    // governed `qualityChip` composite in its place; the 2026-08-18 request
    // to drop "Độ tin cậy" retired that chip too. Both stay gone for good.
    const current = new Date().toISOString();
    const allHealthy: DashboardSnapshot = {
      ...baseSnapshot,
      generated_at: current,
      coverage: {
        issue_category: 0.9,
        app: 0.85,
        tpe: 0.9,
        intent: 0.82,
        skill: 0.8,
      },
      gate_status: {
        ...baseSnapshot.gate_status,
        structural_invalid_rate: 0,
      },
    };
    const oneWeak: DashboardSnapshot = {
      ...allHealthy,
      coverage: { ...allHealthy.coverage, skill: 0.5 },
    };
    const weakerStill: DashboardSnapshot = {
      ...allHealthy,
      coverage: { ...allHealthy.coverage, skill: 0.1 },
    };

    const view = render(shell(null));
    expect(document.getElementById("dqBadge")).toBeNull();
    expect(screen.queryByTestId("qualityChip")).toBeNull();

    view.rerender(shell(allHealthy));
    expect(document.getElementById("dqBadge")).toBeNull();
    expect(screen.queryByTestId("qualityChip")).toBeNull();

    view.rerender(shell(oneWeak));
    expect(document.getElementById("dqBadge")).toBeNull();
    expect(screen.queryByText(/Skill: thiếu 50,0% ticket/)).toBeNull();
    expect(screen.queryByTestId("qualityChip")).toBeNull();

    view.rerender(shell(weakerStill));
    expect(document.getElementById("dqBadge")).toBeNull();
    expect(screen.queryByTestId("qualityChip")).toBeNull();
  });

  it("tracks the section whose top has scrolled under the sticky header, and stops updating after unmount", () => {
    const view = render(shell(baseSnapshot));
    const header = screen.getByRole("banner");
    const weekly = document.getElementById("weekly");
    const tickets = document.getElementById("tickets");
    if (weekly === null || tickets === null) {
      throw new Error("fixture is missing the weekly/tickets sections");
    }

    vi.spyOn(header, "getBoundingClientRect").mockReturnValue({
      height: 100,
    } as unknown as DOMRect);
    const weeklyRect = vi.spyOn(weekly, "getBoundingClientRect");
    const ticketsRect = vi.spyOn(tickets, "getBoundingClientRect");

    // Both sections have scrolled past the header — the last one wins.
    weeklyRect.mockReturnValue({ top: -400 } as unknown as DOMRect);
    ticketsRect.mockReturnValue({ top: 50 } as unknown as DOMRect);
    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });
    expect(
      screen.getByRole("link", { name: "Ticket Explorer" }),
    ).toHaveAttribute("aria-current", "location");
    expect(
      screen.getByRole("link", { name: "Báo cáo tuần" }),
    ).not.toHaveAttribute("aria-current");

    // Ticket Explorer scrolls back below the header — Báo cáo tuần leads again.
    ticketsRect.mockReturnValue({ top: 500 } as unknown as DOMRect);
    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });
    expect(
      screen.getByRole("link", { name: "Báo cáo tuần" }),
    ).toHaveAttribute("aria-current", "location");

    const removeListener = vi.spyOn(window, "removeEventListener");
    view.unmount();
    expect(removeListener).toHaveBeenCalledWith(
      "scroll",
      expect.any(Function),
    );
    expect(removeListener).toHaveBeenCalledWith(
      "resize",
      expect.any(Function),
    );
  });
});

describe("dashboard cross-filter orchestration", () => {
  it("scrolls to a selected segment and supports removing only that filter", async () => {
    const user = userEvent.setup();
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    try {
      render(<DashboardScreen />);

      await user.click(
        await screen.findByRole("button", {
          name: "Lọc Ticket Explorer theo Category: Thanh toán-IBFT",
        }),
      );
      expect(
        screen.getByRole("region", { name: "Bộ lọc đang áp dụng" }),
      ).toHaveTextContent("Category: Thanh toán-IBFT");
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
      await waitFor(() =>
        expect(
          screen.getByRole("heading", { name: "Ticket Explorer" }),
        ).toHaveFocus(),
      );

      await user.click(
        screen.getByRole("button", {
          name: "Bỏ lọc Category: Thanh toán-IBFT",
        }),
      );
      expect(
        screen.queryByRole("region", { name: "Bộ lọc đang áp dụng" }),
      ).toBeNull();
      expect(
        screen.getByRole("region", {
          name: "Bộ lọc đang áp dụng trong Ticket Explorer",
        }),
      ).toHaveTextContent("Tuần: 20/07–24/07");
    } finally {
      Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    }
  });
});

const zeroCounts = {
  total: 0,
  ai_first: 0,
  transferred: 0,
  reopen: 0,
} as const;

const sparseSegments: Segments = {
  issue_category: { "Không xác định": zeroCounts },
  app: {},
  product_code: {},
  skill: {},
  intent: {},
  tpe: {},
  guardrail_rule: {},
  entry_point: {},
};

function belowFoldSnapshot(
  transferReasons: TransferReasons,
): DashboardSnapshot {
  const activeRow = baseSnapshot.views.mon_sun.weekly[0];
  if (activeRow === undefined) {
    throw new Error("Fixture must have an observed week.");
  }
  return {
    ...baseSnapshot,
    data_range: {
      ...baseSnapshot.data_range,
      weeks_without_data: ["2026-07-13"],
    },
    data_quality: {
      ...baseSnapshot.data_quality,
      counts: { invalid_turn: 2 },
    },
    unmapped_tpe_codes: [
      { code: "-999", status: "", count: 1 },
      { code: "-998", status: "Chờ map", count: 2 },
    ],
    views: {
      ...baseSnapshot.views,
      mon_sun: {
        ...baseSnapshot.views.mon_sun,
        weekly: [
          {
            ...activeRow,
            gt4_turn_with_cs: 0,
            gt4_turn_without_cs: 0,
            max_replies_rule_fired: 0,
          },
        ],
        segments: sparseSegments,
        transfer_reasons: transferReasons,
        by_week: {
          ...baseSnapshot.views.mon_sun.by_week,
          "2026-07-20": {
            segments: sparseSegments,
            transfer_reasons: transferReasons,
          },
        },
      },
    },
  };
}

function renderBelowFold(snapshot: DashboardSnapshot) {
  return render(
    <BelowFold
      snapshot={snapshot}
      weekDefinition="mon_sun"
      activeWeek="2026-07-20"
      onWeekSelect={() => {}}
      onSegmentSelect={() => {}}
      activeCsatBreakdownFilters={{ outcome: "", skill: "", issue_category: "" }}
      onCsatBreakdownSelect={() => {}}
      onCsatBreakdownGroupingChange={() => {}}
    />,
  );
}

describe("below-fold degraded states", () => {
  it("explains zero-volume segments, empty diagnostics, and concrete quality gaps", () => {
    const snapshot = belowFoldSnapshot({
      observed_transfer_denominator: 0,
      triggers: [],
      step_result_missing: { count: 0, denominator: 0 },
      tpe: [],
      guardrail: [],
      escalation_guard_blocked: { count: 0, denominator: 0 },
    });

    renderBelowFold(snapshot);

    expect(
      screen.getByText("Không có ticket trong phạm vi đang chọn."),
    ).toBeVisible();
    expect(
      screen.getByText("Không có tín hiệu nào trong phạm vi đang chọn."),
    ).toBeVisible();
    expect(screen.getByText(/trong tuần 20\/07–26\/07/)).toBeVisible();
    expect(
      screen.queryByRole("button", { name: />3 lượt xử lý chưa chuyển CS/ }),
    ).toBeNull();
    expect(screen.queryByText("Số lượt trả lời không hợp lệ: 2")).toBeNull();
    expect(
      screen.getAllByText(
        "Chưa có ticket chuyển CS trong phạm vi đang chọn để đo độ phủ Step result.",
      ),
    ).toHaveLength(1);
    expect(document.getElementById("qualityGrid")).toBeNull();
    expect(document.getElementById("gateGrid")).toBeNull();
    expect(screen.queryByText("-999 · 1 ticket")).toBeNull();
    expect(screen.queryByText("-998 · Chờ map · 2 ticket")).toBeNull();
    // "taxonomy" now legitimately appears in the TPE status caption
    // (#tpeStatusCaption); only the legacy map/case wording it replaced is
    // still disallowed here.
    expect(
      screen.queryByText(/taxonomy/i, { ignore: "#tpeStatusCaption" }),
    ).toBeNull();
  });

  it("renders exact-source TPE signals without dividing by zero", async () => {
    const user = userEvent.setup();
    const snapshot = belowFoldSnapshot({
      observed_transfer_denominator: 0,
      triggers: [],
      step_result_missing: { count: 0, denominator: 0 },
      guardrail: [{ rule: "off_topic", count: 1 }],
      tpe: [
        { transstatus: "-1", step_result: null, count: 1, status: null },
        { transstatus: "-2", step_result: "-1006", count: 1, status: null },
      ],
      escalation_guard_blocked: { count: 0, denominator: 0 },
    });

    renderBelowFold(snapshot);
    await user.click(
      screen.getByRole("heading", { name: "Transstatus và Step result" }),
    );

    const tpeTable = screen.getByRole("table", {
      name: "Transstatus và Step result",
    });
    expect(tpeTable).toHaveAccessibleDescription(/0 ticket đã chuyển CS/);
    expect(
      within(tpeTable).getByText("Không có Step result"),
    ).toBeVisible();
    expect(within(tpeTable).getAllByText("—")).toHaveLength(2);
    expect(within(tpeTable).queryByText(/map|taxonomy|case/i)).toBeNull();

    expect(
      screen.queryByRole("region", { name: "Lý do chuyển CS" }),
    ).toBeNull();
  });

  it("keeps Step result diagnostics in the transfer section instead of duplicating them in quality", () => {
    const snapshot = belowFoldSnapshot({
      observed_transfer_denominator: 5,
      triggers: [
        {
          reason: "unknown",
          rule: null,
          source: null,
          stage: null,
          skill: null,
          count: 5,
        },
      ],
      step_result_missing: { count: 2, denominator: 5 },
      guardrail: [],
      tpe: [{ transstatus: "-365", step_result: "-1024", count: 3, status: null }],
      escalation_guard_blocked: { count: 0, denominator: 5 },
    });

    renderBelowFold(snapshot);

    expect(screen.queryByRole("heading", { name: "Độ phủ Step result" })).toBeNull();
    expect(
      screen.getAllByText(
        "2/5 ticket chuyển CS (40,0%) không có Step result. Các ca này hiện chưa truy được tới bước lỗi cụ thể.",
      ),
    ).toHaveLength(1);
    expect(document.getElementById("stepResultCoveragePanel")).toBeNull();
    // "taxonomy" now legitimately appears in the TPE status caption
    // (#tpeStatusCaption); only the legacy map/case wording it replaced is
    // still disallowed here.
    expect(
      screen.queryByText(/taxonomy/i, { ignore: "#tpeStatusCaption" }),
    ).toBeNull();
  });

  it("calls out a majority once in transfer diagnostics when most transfers lack Step result", () => {
    const snapshot = belowFoldSnapshot({
      observed_transfer_denominator: 5,
      triggers: [
        {
          reason: "unknown",
          rule: null,
          source: null,
          stage: null,
          skill: null,
          count: 5,
        },
      ],
      step_result_missing: { count: 4, denominator: 5 },
      guardrail: [],
      tpe: [{ transstatus: "-365", step_result: "-1024", count: 1, status: null }],
      escalation_guard_blocked: { count: 0, denominator: 5 },
    });

    renderBelowFold(snapshot);

    expect(
      screen.getAllByText(
        "4/5 ticket chuyển CS (80,0%) không có Step result. Phần lớn ca chuyển CS hiện chưa truy được tới bước lỗi cụ thể.",
      ),
    ).toHaveLength(1);
  });
});

function ticketRow(overrides: Partial<TicketRow>): TicketRow {
  const transferred = overrides.transferred ?? false;
  return {
    ticket_id: "1",
    opened_at: "2026-07-20T02:00:00Z",
    cohort_week: "2026-07-20",
    cohort_status: "complete",
    is_weekend_start: false,
    outcome: "ai_end_to_end",
    ai_first: true,
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
    escalation_guard_blocked: false,
    csat_satisfaction: null,
    data_quality: "valid",
    ...overrides,
    transferred,
    transfer_reason: overrides.transfer_reason ?? (transferred ? "unknown" : null),
  };
}

function ExplorerHarness() {
  const [filters, setFilters] =
    useState<TicketFilters>(EMPTY_TICKET_FILTERS);
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

describe("Ticket Explorer behavioral branches", () => {
  it("sorts null, numeric, and boolean values and pages in both directions", async () => {
    localStorage.setItem(
      TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(TICKET_COLUMNS.map((column) => column.key)),
    );
    const firstPage = [
      ticketRow({
        ticket_id: "2",
        opened_at: "2026-07-22T02:00:00Z",
        cohort_week: "2026-07-20",
        turn_count: 10,
        skill: null,
        data_quality: "missing_turn0",
      }),
      ticketRow({
        ticket_id: "10",
        opened_at: "2026-07-20T01:00:00Z",
        cohort_week: "2026-07-13",
        turn_count: 2,
        transferred: true,
        skill: "alpha",
      }),
      ticketRow({
        ticket_id: "3",
        opened_at: "2026-07-21T03:00:00Z",
        cohort_week: "2026-07-06",
        turn_count: 5,
        skill: "beta",
      }),
    ];
    const secondPage = [
      ticketRow({ ticket_id: "99", cohort_week: "2026-06-29" }),
    ];
    server.use(
      http.get("/api/tickets", ({ request }) => {
        const params = new URL(request.url).searchParams;
        const page = Number(params.get("page") ?? 1);
        const sortBy = params.get("sort_by") as keyof TicketRow | null;
        const direction = params.get("sort_direction") === "desc" ? -1 : 1;
        const pageRows = page === 2 ? secondPage : firstPage;
        const items =
          sortBy === null
            ? pageRows
            : [...pageRows].sort((left, right) => {
                const leftValue = left[sortBy];
                const rightValue = right[sortBy];
                if (leftValue === null && rightValue !== null) {
                  return 1;
                }
                if (leftValue !== null && rightValue === null) {
                  return -1;
                }
                if (typeof leftValue === "number" && typeof rightValue === "number") {
                  return direction * (leftValue - rightValue);
                }
                if (
                  typeof leftValue === "boolean" &&
                  typeof rightValue === "boolean"
                ) {
                  return direction * (Number(leftValue) - Number(rightValue));
                }
                return (
                  direction *
                  String(leftValue ?? "").localeCompare(
                    String(rightValue ?? ""),
                    "vi",
                    { numeric: true },
                  )
                );
              });
        return HttpResponse.json({
          items,
          page,
          page_size: 50,
          total: 60,
        });
      }),
    );

    const user = userEvent.setup();
    renderWithQuery(<ExplorerHarness />);
    await screen.findByRole("rowheader", { name: "2" });

    const table = screen.getByRole("table", {
      name: /60 ticket khớp bộ lọc/,
    });
    expect(screen.getByRole("columnheader", { name: /Tuần/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    expect(document.getElementById("tickets-caption")).toHaveAttribute(
      "aria-live",
      "polite",
    );
    const rowIds = () =>
      within(table)
        .getAllByRole("rowheader")
        .map((cell) => cell.getAttribute("aria-label") ?? cell.textContent);

    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo Thời gian mở/ }),
    );
    expect(rowIds()).toEqual(["10", "3", "2"]);
    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo Thời gian mở/ }),
    );
    expect(rowIds()).toEqual(["2", "3", "10"]);

    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo Tổng lượt xử lý/ }),
    );
    expect(
      screen.getByRole("columnheader", { name: /Tổng lượt xử lý/ }),
    ).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    expect(screen.getByRole("columnheader", { name: /Tuần/ })).toHaveAttribute(
      "aria-sort",
      "none",
    );
    expect(rowIds()).toEqual(["10", "3", "2"]);

    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo Tổng lượt xử lý/ }),
    );
    expect(rowIds()).toEqual(["2", "3", "10"]);

    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo Skill/ }),
    );
    expect(rowIds()).toEqual(["10", "3", "2"]);

    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo Skill/ }),
    );
    expect(rowIds()).toEqual(["3", "10", "2"]);

    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo Đã chuyển CS/ }),
    );
    expect(rowIds().at(-1)).toBe("10");
    expect(screen.getByText("Thiếu lượt trả lời đầu tiên")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Trang sau" }));
    expect(
      await screen.findByRole("rowheader", { name: "99" }),
    ).toBeVisible();
    expect(screen.getByText("Trang 2 / 2")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Trang trước" }));
    expect(
      await screen.findByRole("rowheader", { name: "2" }),
    ).toBeVisible();
    expect(screen.getByText("Trang 1 / 2")).toBeVisible();
  });

  it("returns to a visible default sort when the active column is hidden", async () => {
    localStorage.setItem(
      TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(TICKET_COLUMNS.map((column) => column.key)),
    );
    const user = userEvent.setup();
    renderWithQuery(<ExplorerHarness />);
    await screen.findByText("Không có ticket nào khớp bộ lọc hiện tại.");

    await user.click(
      screen.getByRole("button", { name: /Sắp xếp theo AI First/ }),
    );
    expect(
      screen.getByRole("columnheader", { name: /AI First/ }),
    ).toHaveAttribute("aria-sort", "ascending");

    await user.click(screen.getByText("Chọn cột hiển thị"));
    await user.click(screen.getByRole("checkbox", { name: "AI First" }));

    expect(
      screen.queryByRole("columnheader", { name: /AI First/ }),
    ).not.toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByRole("columnheader", { name: /Tuần/ }),
      ).toHaveAttribute("aria-sort", "descending");
    });
    expect(document.getElementById("tickets-caption")).toHaveTextContent(
      "0 ticket khớp bộ lọc.",
    );
    expect(document.getElementById("tickets-caption")).not.toHaveTextContent(
      /tăng dần|giảm dần/,
    );

    await user.click(screen.getByRole("checkbox", { name: "Tuần" }));
    expect(
      screen.queryByRole("columnheader", { name: /Tuần/ }),
    ).not.toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByRole("columnheader", { name: /Ticket/ }),
      ).toHaveAttribute("aria-sort", "ascending");
    });
    expect(document.getElementById("tickets-caption")).toHaveTextContent(
      "0 ticket khớp bộ lọc.",
    );
  });

  it("restores Ticket as the row header before legacy-selected fields", async () => {
    localStorage.setItem(
      TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["cohort_week", "turn_count"]),
    );
    server.use(
      http.get("/api/tickets", () =>
        HttpResponse.json({
          items: [ticketRow({ ticket_id: "7", turn_count: 3 })],
          page: 1,
          page_size: 50,
          total: 1,
        }),
      ),
    );

    renderWithQuery(<ExplorerHarness />);

    const table = await screen.findByRole("table", {
      name: /1 ticket khớp bộ lọc/,
    });
    expect(
      within(table).getByRole("rowheader", { name: "7" }),
    ).toBeVisible();
    const dataRow = within(table).getAllByRole("row")[1];
    expect(dataRow).toBeDefined();
    expect(within(dataRow as HTMLElement).getAllByRole("cell")).toHaveLength(2);
    expect(
      within(table).getAllByRole("columnheader").map((header) => header.textContent),
    ).toEqual(["Ticket", "Tuần", "Tổng lượt xử lý"]);
    expect(
      within(table).getByRole("columnheader", { name: /Tuần/ }),
    ).toHaveAttribute("aria-sort", "descending");
  });

  it("explains that Ticket is mandatory and does not offer a hide control", async () => {
    localStorage.setItem(
      TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["ticket_id"]),
    );
    const user = userEvent.setup();
    renderWithQuery(<ExplorerHarness />);
    await screen.findByText("Không có ticket nào khớp bộ lọc hiện tại.");

    await user.click(screen.getByText("Chọn cột hiển thị"));

    expect(
      screen.getByText("Cột Ticket luôn hiển thị để giữ định danh điều tra."),
    ).toBeVisible();
    expect(screen.queryByRole("checkbox", { name: "Ticket" })).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Sắp xếp theo Ticket/ }),
    ).toBeVisible();
  });

  it("rejects a successful HTTP response whose export payload violates schema", async () => {
    server.use(
      http.get("/api/tickets", () =>
        HttpResponse.json({ items: "not-an-array", page: 1, total: 1 }),
      ),
    );
    const user = userEvent.setup();
    renderWithQuery(<ExplorerHarness />);

    await user.click(screen.getByRole("button", { name: "Tải CSV ticket" }));

    expect(
      await screen.findByText("Không tải được dữ liệu để xuất. Hãy thử lại."),
    ).toBeVisible();
  });
});

describe("data-quality boundary formatting", () => {
  it("treats invalid and future timestamps safely and names every age band", () => {
    const invalid = calculateDataQualityScore(
      { ...baseSnapshot, generated_at: "not-a-date" },
      Date.parse("2026-07-30T00:00:00Z"),
    );
    const future = calculateDataQualityScore(
      { ...baseSnapshot, generated_at: "2026-07-30T00:01:00Z" },
      Date.parse("2026-07-30T00:00:00Z"),
    );
    const farFuture = calculateDataQualityScore(
      { ...baseSnapshot, generated_at: "2026-07-30T00:05:00Z" },
      Date.parse("2026-07-30T00:00:00Z"),
    );

    expect(invalid).toMatchObject({
      ageMs: null,
      freshnessOk: false,
    });
    expect(future).toMatchObject({
      ageMs: -60_000,
      freshnessOk: true,
    });
    expect(farFuture).toMatchObject({
      ageMs: -5 * 60_000,
      freshnessOk: false,
    });
    expect(formatDataAge(null)).toBe("không xác định");
    expect(formatDataAge(-1)).toBe("đồng hồ thiết bị lệch");
    expect(formatDataAge(30_000)).toBe("dưới 1 phút");
    expect(formatDataAge(12 * 60_000)).toBe("12 phút");
    expect(formatDataAge(2 * 60 * 60_000 + 5 * 60_000)).toBe(
      "2 giờ 5 phút",
    );
  });
});
