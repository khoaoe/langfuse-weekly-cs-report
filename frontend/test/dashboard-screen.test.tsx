import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  divergentCohortEnvelope,
  equivalentWtdCohortEnvelope,
  staleViewLevelRuleGt4Envelope,
  tpeStatusDiagnosticsEnvelope,
} from "./fixtures/cohort";
import { dashboardEnvelopeFixture, loadingEnvelopeFixture } from "./fixtures/dashboard";
import { multiSelectSummaryText, toggleMultiSelectOption } from "./multi-select";
import { server } from "./msw/server";
import { DashboardScreen } from "../src/components/DashboardScreen";

describe("DashboardScreen", () => {
  function envelopeWithTwoObservedWeeks() {
    const base = dashboardEnvelopeFixture;
    const monFri = base.snapshot.views.mon_fri;
    const monSun = base.snapshot.views.mon_sun;
    const currentFri = monFri.weekly[0];
    const currentSun = monSun.weekly[0];
    const detailFri = monFri.by_week["2026-07-20"];
    const detailSun = monSun.by_week["2026-07-20"];
    if (
      currentFri === undefined ||
      currentSun === undefined ||
      detailFri === undefined ||
      detailSun === undefined
    ) {
      throw new Error("fixture must contain the current observed week");
    }
    return {
      ...base,
      snapshot: {
        ...base.snapshot,
        views: {
          mon_fri: {
            ...monFri,
            weekly: [
              {
                ...currentFri,
                cohort_week: "2026-07-13",
                cohort_status: "complete" as const,
              },
              currentFri,
            ],
            by_week: {
              ...monFri.by_week,
              "2026-07-13": detailFri,
            },
          },
          mon_sun: {
            ...monSun,
            weekly: [
              {
                ...currentSun,
                cohort_week: "2026-07-13",
                cohort_status: "complete" as const,
              },
              currentSun,
            ],
            by_week: {
              ...monSun.by_week,
              "2026-07-13": detailSun,
            },
          },
        },
      },
    };
  }

  function envelopeWithCsatBreakdown() {
    const zero = { ticket_count: 0, positive: 0, neutral: 0, negative: 0 };
    const week = {
      response_count: 2,
      ticket_count: 2,
      positive: 1,
      neutral: 0,
      negative: 1,
      by_outcome: {
        ai_end_to_end: { ticket_count: 1, positive: 1, neutral: 0, negative: 0 },
        ai_then_cs: zero,
        direct_cs: { ticket_count: 1, positive: 0, neutral: 0, negative: 1 },
        unclassified: zero,
      },
      by_dimension: {
        skill: [
          { value: "interbank-fund-transfer", ticket_count: 1, positive: 1, neutral: 0, negative: 0 },
          { value: "Nhiều skill", ticket_count: 1, positive: 0, neutral: 0, negative: 1 },
        ],
        issue_category: [
          { value: "Chuyển tiền", ticket_count: 1, positive: 1, neutral: 0, negative: 0 },
          { value: "Không xác định", ticket_count: 1, positive: 0, neutral: 0, negative: 1 },
        ],
      },
      feedback_entries: [
        {
          ticket_id: "6991254",
          responded_at: "2026-07-21T01:00:00Z",
          satisfaction_bucket: "positive" as const,
          outcome: "ai_end_to_end" as const,
          skill: "interbank-fund-transfer",
          issue_category: "Chuyển tiền",
          text: "Phản hồi outcome A",
          response_number: 1,
          response_total: 1,
          is_latest_for_ticket: true,
        },
        {
          ticket_id: "6991255",
          responded_at: "2026-07-22T01:00:00Z",
          satisfaction_bucket: "negative" as const,
          outcome: "direct_cs" as const,
          skill: "Nhiều skill",
          issue_category: "Không xác định",
          text: "Phản hồi outcome B",
          response_number: 1,
          response_total: 1,
          is_latest_for_ticket: true,
        },
      ],
    };
    const patchView = (view: typeof dashboardEnvelopeFixture.snapshot.views.mon_fri) => ({
      ...view,
      segments: {
        ...view.segments,
        skill: {
          "interbank-fund-transfer": { total: 4, ai_first: 4, transferred: 1, reopen: 1 },
          "Nhiều skill": { total: 3, ai_first: 1, transferred: 2, reopen: 1 },
          "Chưa ghi nhận": { total: 3, ai_first: 3, transferred: 0, reopen: 0 },
        },
        issue_category: {
          "Chuyển tiền": { total: 5, ai_first: 4, transferred: 1, reopen: 1 },
          "Không xác định": { total: 5, ai_first: 4, transferred: 2, reopen: 1 },
        },
      },
      csat: {
        source: "freshdesk" as const,
        fetched_at: "2026-08-03T01:00:00Z",
        by_week: { "2026-07-20": week },
      },
    });
    return {
      ...dashboardEnvelopeFixture,
      snapshot: {
        ...dashboardEnvelopeFixture.snapshot,
        views: {
          mon_fri: patchView(dashboardEnvelopeFixture.snapshot.views.mon_fri),
          mon_sun: patchView(dashboardEnvelopeFixture.snapshot.views.mon_sun),
        },
      },
    };
  }

  it("lets the reader override and persist the light or dark interface", async () => {
    const user = userEvent.setup();
    const firstRender = render(<DashboardScreen />);

    const toggle = screen.getByRole("button", {
      name: "Giao diện hiện tại: Sáng; chuyển sang Tối",
    });
    expect(toggle).toHaveTextContent("Sáng");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(document.documentElement).toHaveAttribute("data-theme", "light");

    await user.click(toggle);

    expect(toggle).toHaveTextContent("Tối");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("weekly-cs-theme-v1")).toBe("dark");

    firstRender.unmount();
    render(<DashboardScreen />);

    expect(
      screen.getByRole("button", {
        name: "Giao diện hiện tại: Tối; chuyển sang Sáng",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });

  it("falls back from an invalid saved theme to the system preference", () => {
    const darkMediaQuery = {
      matches: true,
      media: "(prefers-color-scheme: dark)",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(() => true),
    } satisfies MediaQueryList;
    localStorage.setItem("weekly-cs-theme-v1", "contrast");
    vi.stubGlobal("matchMedia", vi.fn(() => darkMediaQuery));

    try {
      render(<DashboardScreen />);

      expect(
        screen.getByRole("button", {
          name: "Giao diện hiện tại: Tối; chuyển sang Sáng",
        }),
      ).toHaveAttribute("aria-pressed", "true");
      expect(document.documentElement).toHaveAttribute("data-theme", "dark");
      expect(localStorage.getItem("weekly-cs-theme-v1")).toBe("contrast");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("uses the exact Zalopay casing and renders loading before the first snapshot", async () => {
    server.use(http.get("/api/dashboard", () => HttpResponse.json(loadingEnvelopeFixture, { status: 202 })));

    render(<DashboardScreen />);

    expect(screen.getByRole("banner")).toHaveTextContent("Zalopay");
    expect(await screen.findByRole("status")).toHaveTextContent("Đang tải dữ liệu dashboard.");
    const skeleton = await screen.findByTestId("dashboard-skeleton");
    expect(skeleton).toBeInTheDocument();

    const skipLink = screen.getByRole("link", { name: "Tới nội dung chính" });
    expect(skipLink).toHaveAttribute("href", "#dashboardMain");
    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", "dashboardMain");
    expect(main).toHaveAttribute("tabindex", "-1");
    expect(main).toContainElement(skeleton);
  });

  it("switches the client-only cohort view using the values already in the envelope", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/dashboard", () =>
        HttpResponse.json(divergentCohortEnvelope()),
      ),
    );
    render(<DashboardScreen />);

    const cohortToggle = screen.getByRole("group", {
      name: "Định nghĩa tuần",
    });
    expect(
      within(cohortToggle)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["T2–T6", "T2–CN"]);
    expect(
      within(cohortToggle).getByRole("button", { name: "T2–T6" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByRole("heading", { name: /T2–T6.*20 ticket/i })).toBeVisible();
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveTextContent(
      /đang chạy|đủ điều kiện/i,
    );
    expect(document.getElementById("narrativeSummary")).not.toHaveTextContent(
      /50,0% \(10 ticket\)|Reopen sau AI First 40,0%/,
    );
    expect(document.getElementById("ledger-ai-first")).toHaveTextContent(
      "1050,0% trong 20 ticket tuần này",
    );
    expect(document.getElementById("ledger-transfer")).toHaveTextContent(
      "Tổng chuyển CS7",
    );
    expect(document.getElementById("ledger-reopen")).toHaveTextContent(
      "Reopen sau AI First4",
    );
    expect(document.getElementById("ledger-gt4")).toHaveTextContent(
      ">3 lượt xử lý chưa chuyển CS3",
    );

    await user.click(screen.getByRole("button", { name: "T2–CN" }));
    expect(await screen.findByRole("heading", { name: /T2–CN.*10 ticket/i })).toBeVisible();
    expect(document.getElementById("narrativeSummary")).not.toHaveTextContent(
      /80,0% \(8 ticket\)|Reopen sau AI First 25,0%/,
    );
    expect(document.getElementById("ledger-ai-first")).toHaveTextContent(
      "880,0% trong 10 ticket tuần này",
    );
    expect(document.getElementById("ledger-transfer")).toHaveTextContent(
      "Tổng chuyển CS3",
    );
    expect(document.getElementById("ledger-reopen")).toHaveTextContent(
      "Reopen sau AI First2",
    );
    expect(document.getElementById("ledger-gt4")).toHaveTextContent(
      ">3 lượt xử lý chưa chuyển CS2",
    );
    // The title already names the selected week; repeating it above the KPI
    // cells adds no information.
    expect(document.getElementById("ledger-scope")).toBeNull();
    expect(
      screen.queryByText(/Bốn ô dưới đây|So sánh nhiều tuần nằm ở/),
    ).toBeNull();
    expect(screen.queryByText(/T2–CN và T2–T6 bằng nhau/)).toBeNull();
  });

  it("selects multiple report weeks while Ticket Explorer can override its own week", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/dashboard", () =>
        HttpResponse.json(envelopeWithTwoObservedWeeks()),
      ),
    );
    render(<DashboardScreen />);

    await screen.findByRole("heading", { name: /T2–T6.*7 ticket/i });
    const banner = await screen.findByRole("banner");
    const reportScope = within(banner).getByLabelText(
      "Phạm vi báo cáo: 20/07–24/07",
    );
    await user.click(reportScope);
    const latestWeek = within(banner).getByRole("checkbox", {
      name: "20/07–24/07",
    });
    const earlierWeek = within(banner).getByRole("checkbox", {
      name: "13/07–17/07",
    });
    expect(latestWeek).toBeChecked();
    expect(earlierWeek).not.toBeChecked();
    expect(
      screen.queryByRole("group", { name: "Lọc chéo theo tuần" }),
    ).toBeNull();

    const explorerWeek = screen.getByRole("combobox", { name: "Tuần" });
    await waitFor(() => expect(explorerWeek).toHaveValue("2026-07-20"));
    expect(
      screen.queryByRole("region", { name: "Bộ lọc đang áp dụng" }),
    ).toBeNull();
    expect(
      screen.getByRole("region", {
        name: "Bộ lọc đang áp dụng trong Ticket Explorer",
      }),
    ).toHaveTextContent("Tuần: 20/07–24/07");
    await user.selectOptions(explorerWeek, "2026-07-13");

    expect(explorerWeek).toHaveValue("2026-07-13");
    expect(reportScope).toHaveAccessibleName(
      "Phạm vi báo cáo: 20/07–24/07",
    );
    expect(
      screen.getByRole("heading", { level: 1 }),
    ).toHaveTextContent("tuần 20/07–24/07");

    await user.click(earlierWeek);
    expect(latestWeek).toBeChecked();
    expect(earlierWeek).toBeChecked();
    expect(reportScope).toHaveAccessibleName(
      "Phạm vi báo cáo: 2 tuần đã chọn",
    );
    expect(explorerWeek).toHaveValue("__multiple__");
    expect(
      within(explorerWeek).getByRole("option", {
        name: "2 tuần từ phạm vi báo cáo",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1 }),
    ).toHaveTextContent("2 tuần đã chọn");

    await user.selectOptions(explorerWeek, "2026-07-13");
    expect(explorerWeek).toHaveValue("2026-07-13");
    expect(reportScope).toHaveAccessibleName(
      "Phạm vi báo cáo: 2 tuần đã chọn",
    );

    await user.click(
      within(banner).getByRole("button", {
        name: "Toàn bộ kỳ báo cáo (2 tuần)",
      }),
    );
    expect(explorerWeek).toHaveValue("");
    expect(reportScope).toHaveAccessibleName(
      "Phạm vi báo cáo: Toàn bộ kỳ báo cáo (2 tuần)",
    );
    expect(
      screen.getByRole("heading", { level: 1 }),
    ).toHaveTextContent("toàn bộ kỳ báo cáo");
  });

  it("keeps the Explorer's manual week override across a background refresh that returns the same scope", async () => {
    // Regression: `currentExplorerWeekPatch` is a new object on every parsed
    // snapshot even when its cohort_week/cohort_weeks strings are unchanged,
    // so a naive by-reference (or "re-run every time the memo changes")
    // effect would silently reapply the global scope on every poll and wipe
    // out any manual override the user made in Ticket Explorer -- including
    // a week selection, and (per the same mechanism) an opened-date range.
    const user = userEvent.setup();
    render(<DashboardScreen />);

    await screen.findByRole("heading", { name: /T2–T6.*7 ticket/i });
    const explorerWeek = screen.getByRole("combobox", { name: "Tuần" });
    await waitFor(() => expect(explorerWeek).toHaveValue("2026-07-20"));

    await user.selectOptions(explorerWeek, "");
    expect(explorerWeek).toHaveValue("");

    // A background refresh that reports the exact same scope (same weeks,
    // same cohort data, just a later generated_at) re-parses the envelope
    // into brand-new objects; it must not resurrect the week filter the user
    // just cleared. Waiting for the bumped timestamp to land proves the new
    // snapshot was actually applied before asserting the filter survived it.
    server.use(
      http.get("/api/dashboard", () =>
        HttpResponse.json({
          ...dashboardEnvelopeFixture,
          snapshot: {
            ...dashboardEnvelopeFixture.snapshot,
            generated_at: "2026-07-30T11:27:00Z",
          },
        }),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Làm mới" }));
    await waitFor(() =>
      expect(document.getElementById("updatedAt")).toHaveTextContent(
        "30/7/26",
      ),
    );

    expect(explorerWeek).toHaveValue("");
  });

  it("shows identical decision values across cohorts without an explanatory aside", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/dashboard", () =>
        HttpResponse.json(equivalentWtdCohortEnvelope()),
      ),
    );
    render(<DashboardScreen />);

    // Both cohorts landing on the same numbers is a correct outcome, not a
    // fact that needs its own sentence — the heading already names the week.
    await screen.findByRole("heading", { name: /T2–T6.*ticket/i });
    expect(document.getElementById("ledger-scope")).toBeNull();
    expect(screen.queryByText(/T2–CN và T2–T6 bằng nhau/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "T2–CN" }));
    expect(
      await screen.findByRole("heading", { name: /T2–CN.*10 ticket/i }),
    ).toBeVisible();
    expect(screen.queryByText(/T2–CN và T2–T6 bằng nhau/)).toBeNull();
  });

  it("keeps the restored >3-turn diagnostics on the same latest-week scope as the KPI", async () => {
    server.use(
      http.get("/api/dashboard", () =>
        HttpResponse.json(staleViewLevelRuleGt4Envelope()),
      ),
    );
    render(<DashboardScreen />);

    // The range-wide aggregate is intentionally stale at ten. Both visible
    // surfaces must still resolve to the latest week's zero.
    await screen.findByRole("heading", { level: 1 });
    expect(document.getElementById("ledger-gt4")).toHaveTextContent(
      ">3 lượt xử lý chưa chuyển CS0",
    );

    const rulePanel = document.getElementById("ruleGt4Panel");
    expect(rulePanel).not.toBeNull();
    expect(rulePanel).toBeVisible();
    expect(rulePanel).toHaveTextContent(/Tổng\s*1/);
    expect(rulePanel).toHaveTextContent(/Đã chuyển CS\s*1/);
    expect(rulePanel).toHaveTextContent(/Chưa chuyển CS\s*0/);
    expect(rulePanel).not.toHaveTextContent("10");
    expect(
      screen.queryByRole("button", { name: /ticket chưa chuyển CS/ }),
    ).toBeNull();
  });

  it("uses one decision band, one official shell mark and no decorative section numbers", async () => {
    render(<DashboardScreen />);

    const decisionBand = await screen.findByRole("group", {
      name: "Tóm tắt quyết định",
    });
    expect(screen.getByRole("link", { name: "Tới nội dung chính" })).toHaveAttribute(
      "href",
      "#dashboardMain",
    );
    expect(screen.getByRole("main")).toHaveAttribute("id", "dashboardMain");
    expect(screen.getByRole("main")).toContainElement(decisionBand);
    expect(within(decisionBand).getByRole("heading", { level: 1 })).toBeVisible();
    expect(within(decisionBand).getByText("AI First")).toBeVisible();
    const lightShellMark = document.querySelector<HTMLImageElement>(
      'img[data-brand-mark="shell-z-light"]',
    );
    const darkShellMark = document.querySelector<HTMLImageElement>(
      'img[data-brand-mark="shell-z-dark"]',
    );
    expect(lightShellMark).not.toBeNull();
    expect(lightShellMark).toHaveAttribute(
      "src",
      expect.stringContaining("zalopay-z-light.png"),
    );
    expect(darkShellMark).not.toBeNull();
    expect(darkShellMark).toHaveAttribute(
      "src",
      expect.stringContaining("zalopay-z-dark.png"),
    );
    expect(
      document.querySelectorAll('[data-brand-mark-container="shell-z"]'),
    ).toHaveLength(1);
    expect(document.body).not.toHaveTextContent(/[①②③④⑤⑥]/);
  });

  it("co link dieu huong toi muc CSAT", async () => {
    render(<DashboardScreen />);
    expect(await screen.findByRole("link", { name: "Mức hài lòng" })).toHaveAttribute("href", "#csat");
  });

  it("exposes SPA hooks without putting an ambiguous coverage badge in the header", async () => {
    render(<DashboardScreen />);

    expect(await screen.findByRole("heading", { level: 1 })).toBeVisible();
    for (const id of [
      "statusChip",
      "dynamicTitle",
      "narrativeSummary",
      "kpiGrid",
      "weeklyRows",
      "weeklyCopyButton",
      "weeklyCsvButton",
      "segmentCaption",
    ]) {
      expect(document.getElementById(id), id).not.toBeNull();
    }

    const header = screen.getByRole("banner");
    expect(document.getElementById("dqBadge")).toBeNull();
    expect(within(header).queryByText(/Skill.*(?:thiếu|%)/)).toBeNull();
    expect(document.getElementById("updatedAt")).toHaveTextContent("dữ liệu cũ");
    expect(document.getElementById("statusChip")).toHaveTextContent("Dữ liệu cũ");
  });

  it("ships the required operating controls and applies the stuck-ticket drill-down", async () => {
    const user = userEvent.setup();
    render(<DashboardScreen />);

    expect(
      await screen.findByText("Báo cáo hiệu quả CS Agent"),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Xoá lọc" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Cách đọc" }));
    const helpPanel = screen.getByRole("region", {
      name: "Cách đọc dashboard",
    });
    expect(helpPanel).toHaveTextContent("AI xử lý trọn");
    expect(helpPanel).toHaveTextContent(
      "Với WTD, phần tóm tắt và biểu đồ chỉ so các tuần tới cùng ngày đã hoàn tất khi đủ dữ liệu đối chiếu; bảng tuần vẫn giữ số thực của tuần.",
    );
    expect(helpPanel).toHaveFocus();
    expect(helpPanel).not.toHaveTextContent(/Guardrail|guardrail|\brule\b/i);
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("region", { name: "Cách đọc dashboard" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Cách đọc" })).toHaveFocus();

    const diagnosticAction = screen.getByRole("button", {
      name: "Xem 2 ticket chưa chuyển CS",
    });
    await user.click(diagnosticAction);
    const diagnosticFilters = screen.getByRole("region", {
      name: "Bộ lọc đang áp dụng",
    });
    expect(diagnosticFilters).toHaveTextContent(">3 lượt xử lý: Có");
    expect(diagnosticFilters).toHaveTextContent("Đã chuyển CS: Không");
    expect(diagnosticFilters).not.toHaveTextContent("Tuần:");
    expect(screen.getByRole("combobox", { name: "Tuần" })).toHaveValue(
      "2026-07-20",
    );
    await user.click(screen.getByRole("button", { name: "Xoá lọc" }));

    await toggleMultiSelectOption(
      user,
      document.body,
      "issueCategoryInput",
      "Category",
      "Thanh toán-IBFT",
    );

    const activeFilters = screen.getByRole("region", {
      name: "Bộ lọc đang áp dụng",
    });
    expect(activeFilters).toHaveTextContent("Category: Thanh toán-IBFT");
    expect(screen.getByRole("button", { name: "Xoá lọc" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Xoá lọc" }));
    expect(
      screen.queryByRole("region", { name: "Bộ lọc đang áp dụng" }),
    ).toBeNull();
    expect(document.body).not.toHaveTextContent(
      /rule đã bắn|guard chặn|khoảng trống rule/i,
    );
  });

  it("opens the Ticket Explorer with matching filters from a clickable ledger cell", async () => {
    const user = userEvent.setup();
    render(<DashboardScreen />);

    expect(
      await screen.findByRole("heading", { name: /T2–T6.*7 ticket/i }),
    ).toBeVisible();

    const transferCell = document.getElementById("ledger-transfer");
    await user.click(
      within(transferCell as HTMLElement).getByRole("button"),
    );
    const filtersAfterTransfer = screen.getByRole("region", {
      name: "Bộ lọc đang áp dụng",
    });
    expect(filtersAfterTransfer).toHaveTextContent("Đã chuyển CS: Có");
    expect(filtersAfterTransfer).not.toHaveTextContent("Tuần:");
    expect(filtersAfterTransfer).not.toHaveTextContent(">3 lượt xử lý");

    await user.click(screen.getByRole("button", { name: "Xoá lọc" }));

    const gt4Cell = document.getElementById("ledger-gt4");
    await user.click(within(gt4Cell as HTMLElement).getByRole("button"));
    const filtersAfterGt4 = screen.getByRole("region", {
      name: "Bộ lọc đang áp dụng",
    });
    expect(filtersAfterGt4).toHaveTextContent(">3 lượt xử lý: Có");
    expect(filtersAfterGt4).toHaveTextContent("Đã chuyển CS: Không");

    // AI First and reopen have no matching Explorer filter today, so they
    // stay plain text rather than opening a filter narrower than the number.
    expect(
      within(document.getElementById("ledger-ai-first") as HTMLElement).queryByRole(
        "button",
      ),
    ).toBeNull();
    expect(
      within(document.getElementById("ledger-reopen") as HTMLElement).queryByRole(
        "button",
      ),
    ).toBeNull();
  });

  it("filters CSAT feedback and Ticket Explorer from an explicit clearable selector", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/dashboard", () => HttpResponse.json(envelopeWithCsatBreakdown())),
    );
    render(<DashboardScreen />);

    await screen.findByRole("heading", { name: /T2–T6.*ticket/i });
    const csatSection = screen.getByRole("region", { name: "Khách hài lòng tới đâu" });
    await user.click(within(csatSection).getByRole("button", { name: "Xem 2 nội dung phản hồi" }));
    expect(
      within(csatSection).queryByRole("button", { name: "AI xử lý trọn" }),
    ).toBeNull();
    const outcomeFilter = within(csatSection).getByRole("combobox", {
      name: "Lọc nội dung theo Kết quả xử lý",
    });
    await user.selectOptions(outcomeFilter, "ai_end_to_end");

    expect(outcomeFilter).toHaveValue("ai_end_to_end");
    expect(screen.getByRole("region", { name: "Bộ lọc đang áp dụng" })).toHaveTextContent(
      "Kết quả: AI xử lý trọn",
    );
    expect(within(csatSection).getByText("Phản hồi outcome A")).toBeVisible();
    expect(within(csatSection).queryByText("Phản hồi outcome B")).toBeNull();
    const ticketExplorer = document.getElementById("tickets") as HTMLElement;
    expect(ticketExplorer).not.toBeNull();
    expect(multiSelectSummaryText(ticketExplorer, "Kết quả")).toBe(
      "AI xử lý trọn",
    );

    await user.selectOptions(outcomeFilter, "");
    expect(outcomeFilter).toHaveValue("");
    expect(screen.queryByText("Kết quả: AI xử lý trọn")).toBeNull();
    expect(multiSelectSummaryText(ticketExplorer, "Kết quả")).toBe("Tất cả");
    expect(within(csatSection).getByText("Phản hồi outcome A")).toBeVisible();
    expect(within(csatSection).getByText("Phản hồi outcome B")).toBeVisible();

    const grouping = within(csatSection).getByRole("combobox", { name: "Nhóm theo" });
    await user.selectOptions(grouping, "skill");
    const skillFilter = within(csatSection).getByRole("combobox", {
      name: "Lọc nội dung theo Skill",
    });
    await user.selectOptions(skillFilter, "interbank-fund-transfer");
    expect(screen.getByRole("region", { name: "Bộ lọc đang áp dụng" })).toHaveTextContent(
      "Skill: interbank-fund-transfer",
    );
    expect(multiSelectSummaryText(ticketExplorer, "Skill")).toBe(
      "interbank-fund-transfer",
    );
    expect(within(csatSection).getByText("Phản hồi outcome A")).toBeVisible();
    expect(within(csatSection).queryByText("Phản hồi outcome B")).toBeNull();

    await user.selectOptions(grouping, "issue_category");
    expect(screen.queryByText("Skill: interbank-fund-transfer")).toBeNull();
    await user.selectOptions(
      within(csatSection).getByRole("combobox", {
        name: "Lọc nội dung theo Category",
      }),
      "Chuyển tiền",
    );
    expect(screen.getByRole("region", { name: "Bộ lọc đang áp dụng" })).toHaveTextContent(
      "Category: Chuyển tiền",
    );
    expect(multiSelectSummaryText(ticketExplorer, "Category")).toBe(
      "Chuyển tiền",
    );

    await user.selectOptions(grouping, "skill");
    await user.selectOptions(
      within(csatSection).getByRole("combobox", {
        name: "Lọc nội dung theo Skill",
      }),
      "Nhiều skill",
    );
    expect(multiSelectSummaryText(ticketExplorer, "Skill")).toBe(
      "Nhiều skill",
    );
    expect(within(csatSection).getByText("Phản hồi outcome B")).toBeVisible();
    expect(within(csatSection).queryByText("Phản hồi outcome A")).toBeNull();
  });

  it("drills a CSAT breakdown value into Ticket Explorer", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/dashboard", () => HttpResponse.json(envelopeWithCsatBreakdown())),
    );
    render(<DashboardScreen />);

    await screen.findByRole("heading", { name: /T2–T6.*ticket/i });
    const csatSection = screen.getByRole("region", {
      name: "Khách hài lòng tới đâu",
    });
    await user.click(
      within(csatSection).getByRole("button", {
        name: "Lọc Ticket Explorer theo Kết quả xử lý: AI xử lý trọn",
      }),
    );

    expect(
      multiSelectSummaryText(
        document.getElementById("tickets") as HTMLElement,
        "Kết quả",
      ),
    ).toBe("AI xử lý trọn");
  });

  it("drills diagnostic values into clearable Ticket Explorer filters", async () => {
    const user = userEvent.setup();
    render(<DashboardScreen />);

    await screen.findByRole("heading", { name: /T2–T6.*ticket/i });
    const explorer = document.getElementById("tickets") as HTMLElement;

    await user.click(
      screen.getByRole("button", {
        name: "Lọc Ticket Explorer theo Lý do chuyển CS: Skill đề xuất chuyển CS",
      }),
    );
    expect(multiSelectSummaryText(explorer, "Lý do chuyển CS")).toBe(
      "Skill đề xuất chuyển CS",
    );
    expect(multiSelectSummaryText(explorer, "Skill")).toBe(
      "interbank-fund-transfer",
    );
    expect(
      within(explorer).getByRole("region", {
        name: "Bộ lọc đang áp dụng trong Ticket Explorer",
      }),
    ).toHaveTextContent("Lý do chuyển CS: Skill đề xuất chuyển CS");

    await user.click(
      screen.getByRole("heading", { name: "Transstatus và Step result" }),
    );
    await user.click(
      screen.getByRole("button", {
        name: "Lọc Ticket Explorer theo Transstatus: -365",
      }),
    );
    expect(multiSelectSummaryText(explorer, "Transstatus")).toBe("-365");

    await user.click(
      screen.getByRole("button", {
        name: "Lọc Ticket Explorer theo Trạng thái: Đã chuyển CS",
      }),
    );
    expect(
      within(explorer).getByRole("combobox", { name: "Hơn 3 lượt xử lý" }),
    ).toHaveValue("true");
    expect(
      within(explorer).getByRole("combobox", { name: "Đã chuyển CS" }),
    ).toHaveValue("true");
  });

  it("hien status da resolve va gan nhan chua phan loai cho phan con lai", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/dashboard", () =>
        HttpResponse.json(tpeStatusDiagnosticsEnvelope()),
      ),
    );
    render(<DashboardScreen />);

    await screen.findByRole("heading", { name: /T2–T6.*ticket/i });
    await user.click(
      screen.getByRole("heading", { name: "Transstatus và Step result" }),
    );

    const tpeTable = document.getElementById("tpeDistribution") as HTMLElement;
    expect(within(tpeTable).getByText("SUCCESSFUL")).toBeInTheDocument();
    expect(within(tpeTable).getByText("Chưa phân loại")).toBeInTheDocument();
  });

  it("keeps the last-good report visible after a refresh fails", async () => {
    const user = userEvent.setup();
    render(<DashboardScreen />);
    expect(
      await screen.findByRole("heading", { name: /T2–T6.*7 ticket/i }),
    ).toBeVisible();

    server.use(http.get("/api/dashboard", () => HttpResponse.json({ detail: { code: "dashboard_not_ready" } }, { status: 503 })));
    await user.click(screen.getByRole("button", { name: "Làm mới" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Không thể tải dữ liệu mới. Đang hiển thị dữ liệu gần nhất.");
    expect(
      screen.getByRole("heading", { name: /T2–T6.*7 ticket/i }),
    ).toBeVisible();
  });

  it("moi control loc deu co id on dinh", async () => {
    render(<DashboardScreen />);
    await screen.findByRole("heading", { name: /T2–T6.*ticket/i });

    ["ticketIdInput", "outcomeInput", "csatSatisfactionInput"].forEach((id) => {
      expect(document.getElementById(id)).not.toBeNull();
    });

    // The Freshdesk cookie dialog is always mounted (only its `open` state
    // toggles visibility), so its stable id is present without opening it.
    expect(document.getElementById("freshdeskCookieInput")).not.toBeNull();
  });

  it("cot Ticket Explorer duoc chon hien thi deu co id theo tien to columnOption", async () => {
    const user = userEvent.setup();
    render(<DashboardScreen />);
    await screen.findByRole("heading", { name: /T2–T6.*ticket/i });

    await user.click(screen.getByText("Chọn cột hiển thị"));
    expect(document.getElementById("columnOption-opened_at")).not.toBeNull();
    expect(document.getElementById("columnOption-outcome")).not.toBeNull();
  });

  it("checkbox tuan trong Phạm vi báo cáo co id theo tien to reportScope", async () => {
    server.use(
      http.get("/api/dashboard", () =>
        HttpResponse.json(envelopeWithTwoObservedWeeks()),
      ),
    );
    render(<DashboardScreen />);
    await screen.findByRole("heading", { name: /T2–T6.*7 ticket/i });

    expect(document.getElementById("reportScope-2026-07-20")).not.toBeNull();
    expect(document.getElementById("reportScope-2026-07-13")).not.toBeNull();
  });

  it("control loc noi dung phan hoi CSAT va nhom breakdown co id on dinh", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/dashboard", () => HttpResponse.json(envelopeWithCsatBreakdown())),
    );
    render(<DashboardScreen />);
    await screen.findByRole("heading", { name: /T2–T6.*ticket/i });

    expect(document.getElementById("csatBreakdownGroupingInput")).not.toBeNull();

    const csatSection = screen.getByRole("region", { name: "Khách hài lòng tới đâu" });
    await user.click(
      within(csatSection).getByRole("button", { name: "Xem 2 nội dung phản hồi" }),
    );

    [
      "csatCommentGroupingInput",
      "csatCommentWeekInput",
      "csatCommentSatisfactionInput",
      "csatCommentSortInput",
    ].forEach((id) => {
      expect(document.getElementById(id)).not.toBeNull();
    });
  });

  it("o dan ticket trong Vi sao agent lam vay co id on dinh", async () => {
    const originalHash = window.location.hash;
    window.location.hash = "#trace";
    try {
      render(<DashboardScreen />);
      await screen.findByRole("heading", { name: "Vì sao agent làm vậy" });
      expect(document.getElementById("traceTicketIdInput")).not.toBeNull();
    } finally {
      window.location.hash = originalHash;
    }
  });
});
