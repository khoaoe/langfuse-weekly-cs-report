import AxeBuilder from "@axe-core/playwright";
import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

import {
  divergentCohortEnvelope,
  equivalentWtdCohortEnvelope,
} from "../test/fixtures/cohort";
import { dashboardEnvelopeFixture } from "../test/fixtures/dashboard";
import type { TicketRow } from "../src/lib/dashboard-schema";

const ORIGIN = "http://127.0.0.1:18765";

/** Console output that any strict-CSP or network violation would produce. */
function collectProblems(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (message: ConsoleMessage) => {
    if (message.type() === "error" || message.type() === "warning") {
      problems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  return problems;
}

const CSAT_E2E_TICKETS = [
  { ticket_id: "7000001", outcome: "ai_end_to_end", skill: "interbank-fund-transfer", issue_category: "Category A", satisfaction: "positive", response_total: 4 },
  { ticket_id: "7000002", outcome: "ai_end_to_end", skill: "interbank-fund-transfer", issue_category: "Category B", satisfaction: "neutral", response_total: 4 },
  { ticket_id: "7000003", outcome: "ai_end_to_end", skill: "Nhiều skill", issue_category: "Category C", satisfaction: "negative", response_total: 4 },
  { ticket_id: "7000004", outcome: "direct_cs", skill: "Nhiều skill", issue_category: "Category D", satisfaction: "positive", response_total: 4 },
  { ticket_id: "7000005", outcome: "direct_cs", skill: "topup", issue_category: "Category E", satisfaction: "neutral", response_total: 4 },
  { ticket_id: "7000006", outcome: "ai_then_cs", skill: "topup", issue_category: "Category F", satisfaction: "negative", response_total: 3 },
] as const;

const CSAT_E2E_APP = "241 - Chuyển Tiền ATM";

function csatDecisionEnvelope() {
  const base = structuredClone(dashboardEnvelopeFixture);
  const countsFor = (tickets: readonly (typeof CSAT_E2E_TICKETS)[number][]) => ({
    ticket_count: tickets.length,
    positive: tickets.filter((ticket) => ticket.satisfaction === "positive").length,
    neutral: tickets.filter((ticket) => ticket.satisfaction === "neutral").length,
    negative: tickets.filter((ticket) => ticket.satisfaction === "negative").length,
  });
  const dimensionRows = (dimension: "skill" | "issue_category") =>
    [...new Set(CSAT_E2E_TICKETS.map((ticket) => ticket[dimension]))].map((value) => ({
      value,
      ...countsFor(CSAT_E2E_TICKETS.filter((ticket) => ticket[dimension] === value)),
    }));
  const feedbackEntries = CSAT_E2E_TICKETS.flatMap((ticket, ticketIndex) =>
    Array.from({ length: ticket.response_total }, (_, responseIndex) => ({
      ticket_id: ticket.ticket_id,
      responded_at: new Date(
        Date.UTC(2026, 6, 20 + ticketIndex, responseIndex),
      ).toISOString(),
      satisfaction_bucket:
        responseIndex === ticket.response_total - 1
          ? ticket.satisfaction
          : (["neutral", "negative", "positive"] as const)[responseIndex % 3] ?? "neutral",
      outcome: ticket.outcome,
      skill: ticket.skill,
      issue_category: ticket.issue_category,
      app: CSAT_E2E_APP,
      text: `Nội dung phản hồi ${String.fromCharCode(65 + ticketIndex)}-${responseIndex + 1}`,
      response_number: responseIndex + 1,
      response_total: ticket.response_total,
      is_latest_for_ticket: responseIndex === ticket.response_total - 1,
    })),
  );
  const feedbackPool = Object.fromEntries(
    feedbackEntries.map((entry) => [
      `${entry.ticket_id}:${entry.response_number}`,
      entry,
    ]),
  );
  const week = {
    response_count: feedbackEntries.length,
    ...countsFor(CSAT_E2E_TICKETS),
    by_outcome: {
      ai_end_to_end: countsFor(
        CSAT_E2E_TICKETS.filter((ticket) => ticket.outcome === "ai_end_to_end"),
      ),
      ai_then_cs: countsFor(
        CSAT_E2E_TICKETS.filter((ticket) => ticket.outcome === "ai_then_cs"),
      ),
      direct_cs: countsFor(
        CSAT_E2E_TICKETS.filter((ticket) => ticket.outcome === "direct_cs"),
      ),
      unclassified: { ticket_count: 0, positive: 0, neutral: 0, negative: 0 },
    },
    by_dimension: {
      skill: dimensionRows("skill"),
      issue_category: dimensionRows("issue_category"),
      app: [{ value: CSAT_E2E_APP, ...countsFor(CSAT_E2E_TICKETS) }],
    },
    feedback_entry_keys: Object.keys(feedbackPool),
  };
  const segmentCounts = (values: readonly string[]) =>
    Object.fromEntries([
      ...values.map((value, index) => [
        value,
        {
          total: index === 0 ? 11 - values.length : 1,
          ai_first: index === 0 ? 9 - values.length : 1,
          transferred: index === 0 ? 3 : 0,
          reopen: index === 0 ? 2 : 0,
          ai_end_to_end: index === 0 ? 9 - values.length - 3 : 1,
          direct_cs: 0,
        },
      ]),
      ["Chưa ghi nhận", { total: 0, ai_first: 0, transferred: 0, reopen: 0, ai_end_to_end: 0, direct_cs: 0 }],
    ]);
  const patchView = (view: (typeof base.snapshot.views)["mon_fri"]) => {
    const detail = view.by_week["2026-07-20"];
    if (detail === undefined) throw new Error("E2E fixture requires the latest week");
    const segments = {
      ...view.segments,
      skill: segmentCounts(dimensionRows("skill").map((row) => row.value)),
      issue_category: segmentCounts(
        dimensionRows("issue_category").map((row) => row.value),
      ),
    };
    return {
      ...view,
      segments,
      by_week: {
        ...view.by_week,
        "2026-07-20": { ...detail, segments },
      },
      csat: {
        source: "freshdesk" as const,
        fetched_at: "2026-08-03T03:00:00Z",
        by_week: { "2026-07-20": week },
        feedback_pool: feedbackPool,
      },
      outcome_reconciliation: {
        source: "freshdesk" as const,
        fetched_at: "2026-08-03T03:05:00Z",
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
    };
  };
  return {
    ...base,
    snapshot: {
      ...base.snapshot,
      views: {
        mon_fri: patchView(base.snapshot.views.mon_fri),
        mon_sun: patchView(base.snapshot.views.mon_sun),
      },
    },
  };
}

function csatTicketRows(): readonly TicketRow[] {
  return CSAT_E2E_TICKETS.map((ticket) => ({
    ticket_id: ticket.ticket_id,
    opened_at: "2026-07-20T02:00:00Z",
    cohort_week: "2026-07-20",
    cohort_status: "complete",
    is_weekend_start: false,
    outcome: ticket.outcome,
    ai_first: ticket.outcome !== "direct_cs",
    transferred: ticket.outcome !== "ai_end_to_end",
    reopen_lifetime: 0,
    reopen_within_7d: 0,
    ai_reply_count: ticket.outcome === "direct_cs" ? 0 : 1,
    turn_count: 2,
    gt4_turn: false,
    issue_category: ticket.issue_category,
    app: "Zalopay",
    product_code: "IBFT",
    skill: ticket.skill,
    intent: null,
    tpe_code: null,
    tpe_status: null,
    guardrail_rule: null,
    transfer_reason:
      ticket.outcome === "ai_end_to_end" ? null : "unknown",
    escalation_guard_blocked: false,
    csat_satisfaction: ticket.satisfaction,
    data_quality: "valid",
    model_core: null,
    tool_error_codes: [],
    ai_review_rating: null,
  }));
}

test.describe("Zalopay weekly CS dashboard", () => {
  test("loads with no console, CSP or third-party request", async ({ page }) => {
    const problems = collectProblems(page);
    const external: string[] = [];
    page.on("request", (request) => {
      if (!request.url().startsWith(ORIGIN) && !request.url().startsWith("data:")) {
        external.push(request.url());
      }
    });

    const response = await page.goto("/");
    await expect(page.getByRole("banner")).toContainText("Zalopay");

    expect(response?.headers()["cache-control"]).toBe("no-store");
    const policy = response?.headers()["content-security-policy"] ?? "";
    expect(policy).toContain("script-src 'self'");
    expect(policy).toContain("script-src-attr 'none'");
    expect(policy).toContain("style-src-attr 'none'");
    expect(policy).not.toContain("unsafe-inline");
    expect(policy).not.toContain("unsafe-eval");

    expect(external).toEqual([]);
    expect(problems).toEqual([]);
  });

  test("shows the decision ledger and never scrolls the page sideways", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    // `overflow-x: clip` stops the page scrolling sideways but does not hide a
    // real break from layout, so measure the elements themselves. Descendants
    // of an intentional local scroller are allowed to extend past the viewport:
    // the table and section navigation own that overflow by design.
    const overflowing = await page.evaluate(() => {
      const limit = document.documentElement.clientWidth;
      const belongsToLocalScroller = (node: Element) => {
        let parent = node.parentElement;
        while (parent !== null && parent !== document.body) {
          const overflowX = window.getComputedStyle(parent).overflowX;
          if (
            (overflowX === "auto" || overflowX === "scroll") &&
            parent.scrollWidth > parent.clientWidth + 1
          ) {
            return true;
          }
          parent = parent.parentElement;
        }
        return false;
      };

      return Array.from(document.querySelectorAll("body *"))
        .filter((node) => {
          const rect = node.getBoundingClientRect();
          const crossesCanvas = rect.right > limit + 1 || rect.left < -1;
          return rect.width > 0 && crossesCanvas && !belongsToLocalScroller(node);
        })
        .slice(0, 5)
        .map((node) => `${node.tagName}.${String(node.className)}`);
    });
    expect(overflowing).toEqual([]);
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth >
          document.documentElement.clientWidth,
      ),
    ).toBe(false);

    const ledgerCells = page.locator(
      "#ledger-ai-first, #ledger-transfer, #ledger-reopen, #ledger-direct-cs",
    );
    await expect(ledgerCells).toHaveCount(4);
  });

  test("uses an explicit clearable CSAT feedback filter across all three surfaces", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name !== "desktop-light",
      "the full CSAT decision path only needs one browser run",
    );
    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(csatDecisionEnvelope()),
      }),
    );
    await page.route("**/api/tickets**", (route) => {
      const url = new URL(route.request().url());
      let rows = [...csatTicketRows()];
      for (const key of [
        "outcome",
        "skill",
        "issue_category",
        "csat_satisfaction",
      ] as const) {
        const value = url.searchParams.get(key);
        if (value !== null) {
          rows = rows.filter((row) => row[key] === value);
        }
      }
      const pageNumber = Number(url.searchParams.get("page") ?? "1");
      const pageSize = Number(url.searchParams.get("page_size") ?? "50");
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: rows.slice((pageNumber - 1) * pageSize, pageNumber * pageSize),
          page: pageNumber,
          page_size: pageSize,
          total: rows.length,
        }),
      });
    });

    await page.goto("/");
    const csat = page.getByRole("region", { name: "Mức hài lòng" });
    const source = csat.locator("#csat-source");
    await expect(source).toHaveText(
      /^CSAT: Freshdesk · cập nhật .+(?: · Chưa cập nhật hôm nay\.|\.)$/,
    );
    const reportScope = page.locator(
      'summary[aria-label^="Phạm vi báo cáo:"]',
    );
    await reportScope.click();
    await page
      .getByRole("button", { name: /Toàn bộ kỳ báo cáo/ })
      .click();
    await expect(reportScope).toHaveAccessibleName(
      /Phạm vi báo cáo: Toàn bộ kỳ báo cáo/,
    );
    await expect(page.locator("#cohortWeekInput")).toHaveValue("");
    const sourceLines = await source.evaluate((node) => {
      const style = getComputedStyle(node);
      return {
        height: node.getBoundingClientRect().height,
        lineHeight: Number.parseFloat(style.lineHeight),
      };
    });
    expect(sourceLines.height).toBeLessThanOrEqual(sourceLines.lineHeight + 1);
    await expect(csat.getByRole("rowheader", { name: "AI xử lý trọn" })).toBeVisible();
    await expect(
      csat.getByRole("button", {
        name: "Lọc Ticket Explorer theo Kết quả xử lý: AI xử lý trọn",
        exact: true,
      }),
    ).toBeVisible();
    await csat.getByRole("button", { name: "Xem 23 nội dung phản hồi" }).click();

    const outcomeFilter = csat.getByRole("combobox", {
      name: "Lọc nội dung theo Kết quả xử lý",
    });
    await outcomeFilter.selectOption("ai_end_to_end");
    await expect(outcomeFilter).toHaveValue("ai_end_to_end");
    const explorerFilters = page.getByRole("region", {
      name: "Bộ lọc đang áp dụng trong Ticket Explorer",
    });
    await expect(explorerFilters).toContainText("Kết quả: AI xử lý trọn");
    await expect(csat).toContainText("Hiển thị 1–10 / 12 nội dung phản hồi");
    await expect(csat.getByText("Nội dung phản hồi D-1")).toHaveCount(0);

    await outcomeFilter.selectOption("");
    await expect(outcomeFilter).toHaveValue("");
    await expect(page.getByText("Kết quả: AI xử lý trọn")).toHaveCount(0);
    await expect(csat).toContainText("Hiển thị 1–10 / 23 nội dung phản hồi");

    await csat.getByRole("combobox", { name: "Nhóm theo" }).selectOption("skill");
    const skillFilter = csat.getByRole("combobox", {
      name: "Lọc nội dung theo Skill",
    });
    await skillFilter.selectOption("Nhiều skill");
    await expect(csat).toContainText("Hiển thị 1–8 / 8 nội dung phản hồi");
    await expect(explorerFilters).toContainText("Skill: Nhiều skill");
    await skillFilter.selectOption("");

    await csat.getByRole("button", { name: "Trang 3" }).click();
    await expect(csat.locator("#csat-comments li")).toHaveCount(3);
    await expect(csat).toContainText("Hiển thị 21–23 / 23 nội dung phản hồi");
    await expect(
      page.locator("#tickets").getByRole("columnheader", {
        name: /Khách hàng đánh giá/,
      }),
    ).toBeVisible();
    await expect(page.locator("#segments").getByRole("rowheader", {
      name: "Chưa ghi nhận",
    })).toHaveCount(0);
    await expect(
      page.getByRole("region", {
        name: "Đối chiếu kết quả xử lý với Freshdesk",
      }),
    ).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText(
      /Đối chiếu Freshdesk|đã xác định có CS người trả lời sau|AI First phía trên/i,
    );
    await expect(page.locator("body")).not.toContainText("bình luận");
  });

  test("switches every decision value with the selected cohort", async ({
    page,
  }) => {
    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(divergentCohortEnvelope()),
      }),
    );
    await page.goto("/");

    const cohortButtons = page
      .getByRole("group", { name: "Định nghĩa tuần" })
      .getByRole("button");
    await expect(cohortButtons).toHaveText(["T2–T6", "T2–CN"]);
    await expect(page.getByRole("button", { name: "T2–T6" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(
      page.getByRole("heading", { level: 1, name: /T2–T6.*20 ticket/ }),
    ).toBeVisible();
    await expect(page.locator("#ledger-ai-first")).toContainText("50,0%");
    await expect(page.locator("#ledger-transfer")).toContainText("7");
    await expect(page.locator("#ledger-reopen")).toContainText("4");
    await expect(page.locator("#ledger-direct-cs")).toContainText("2");

    await page.getByRole("button", { name: "T2–CN" }).click();

    await expect(
      page.getByRole("heading", { level: 1, name: /T2–CN.*10 ticket/ }),
    ).toBeVisible();
    await expect(page.locator("#ledger-ai-first")).toContainText(
      /AI First\s*8\s*80,0%/,
    );
    await expect(page.locator("#ledger-transfer")).toContainText("3");
    await expect(page.locator("#ledger-reopen")).toContainText("2");
    await expect(page.locator("#ledger-direct-cs")).toContainText("1");
    await expect(
      page.getByText(/Hai cohort đang cho cùng số liệu/),
    ).toHaveCount(0);
  });

  test("switches cohort state even when both cohorts have identical values", async ({
    page,
  }) => {
    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(equivalentWtdCohortEnvelope()),
      }),
    );
    await page.goto("/");

    const monSun = page.getByRole("button", { name: "T2–CN" });
    await monSun.click();
    await expect(monSun).toHaveAttribute("aria-pressed", "true");
    await expect(
      page.getByRole("heading", { level: 1, name: /T2–CN.*10 ticket/ }),
    ).toBeVisible();
  });

  test("keeps the whole decision state above the fold on desktop", async ({
    page,
  }, testInfo) => {
    test.skip(!testInfo.project.name.startsWith("desktop"), "desktop layout rule");

    await page.goto("/");
    const bottom = await page
      .locator("#ledger-direct-cs")
      .evaluate((node) => node.getBoundingClientRect().bottom);

    expect(bottom).toBeLessThanOrEqual(900);
  });

  test("does not render the removed action-warning rail", async ({
    page,
  }) => {
    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(dashboardEnvelopeFixture),
      }),
    );

    await page.goto("/");
    await expect(page.getByRole("list", { name: "Việc cần chú ý" })).toHaveCount(0);
  });

  test("scrolls the weekly table locally with a sticky header and week column", async ({
    page,
  }) => {
    await page.goto("/");
    const scroller = page.locator("#weekly [role='region']");
    await expect(scroller).toBeVisible();

    const measurements = await scroller.evaluate((node) => {
      // Scroll the container so the assertion proves the header actually
      // sticks rather than merely sitting at the top while at rest.
      node.scrollTop = Math.max(0, node.scrollHeight - node.clientHeight);
      node.scrollLeft = Math.max(0, node.scrollWidth - node.clientWidth);

      // The grouped row is hidden on mobile, so choose the first header whose
      // row is actually rendered in the current viewport.
      const header = Array.from(node.querySelectorAll("thead th")).find(
        (candidate) =>
          candidate.closest("tr") !== null &&
          getComputedStyle(candidate.closest("tr") as HTMLTableRowElement)
            .display !== "none",
      );
      const firstColumn = node.querySelector("tbody th");
      const headerStyle = header === undefined ? null : getComputedStyle(header);
      const columnStyle = firstColumn === null ? null : getComputedStyle(firstColumn);
      const box = node.getBoundingClientRect();
      return {
        scrollable: node.scrollWidth >= node.clientWidth,
        scrolledDown: node.scrollTop,
        headerPosition: headerStyle?.position ?? "",
        headerTop: headerStyle?.top ?? "",
        columnPosition: columnStyle?.position ?? "",
        columnLeft: columnStyle?.left ?? "",
        // `clientTop` removes the container border, which is outside the
        // scrolling viewport the sticky element is pinned to.
        offsetFromWrapTop:
          header === undefined
            ? -1
            : header.getBoundingClientRect().top - (box.top + node.clientTop),
        offsetFromWrapLeft:
          firstColumn === null
            ? -1
            : firstColumn.getBoundingClientRect().left - (box.left + node.clientLeft),
      };
    });

    expect(measurements.scrollable).toBe(true);
    expect(measurements.headerPosition).toBe("sticky");
    // Inside a scroll container the sticky origin is the container itself.
    expect(measurements.headerTop).toBe("0px");
    expect(measurements.columnPosition).toBe("sticky");
    expect(measurements.columnLeft).toBe("0px");
    expect(Math.round(measurements.offsetFromWrapTop)).toBe(0);
    expect(Math.round(measurements.offsetFromWrapLeft)).toBe(0);

    const wtdBackgrounds = await page
      .locator("#weekly tbody tr")
      .first()
      .evaluate((row) => {
        const weekHeader = row.querySelector("th");
        const metricCell = row.querySelector("td");
        return {
          header:
            weekHeader === null ? "" : getComputedStyle(weekHeader).backgroundColor,
          metric:
            metricCell === null ? "" : getComputedStyle(metricCell).backgroundColor,
        };
      });
    expect(wtdBackgrounds.header).toBe(wtdBackgrounds.metric);
  });

  test("sorts report data tables from keyboard-native column headers", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name !== "desktop-light",
      "sorting behavior only needs one full browser run",
    );

    await page.goto("/");

    const weekly = page.locator("#weekly table");
    await expect(weekly).toBeVisible();
    await expect(
      weekly.getByRole("columnheader", { name: /Tuần/ }),
    ).toHaveAttribute("aria-sort", "descending");

    const weeklyRowsBefore = await weekly.locator("tbody th").allTextContents();
    await weekly.getByRole("button", { name: /Sắp xếp theo Tổng ticket/ }).click();
    await expect(
      weekly.getByRole("columnheader", { name: /Tổng ticket/ }),
    ).toHaveAttribute("aria-sort", "descending");
    const weeklyRowsAfter = await weekly.locator("tbody th").allTextContents();
    expect(weeklyRowsAfter).not.toEqual(weeklyRowsBefore);

    const segment = page.locator("#segments table");
    await expect(segment).toBeVisible();
    await expect(
      segment.getByRole("columnheader", { name: /Chuyển CS/ }),
    ).toHaveAttribute("aria-sort", "descending");
    await segment.getByRole("button", { name: /Sắp xếp theo Giá trị/ }).click();
    await expect(
      segment.getByRole("columnheader", { name: /Giá trị/ }),
    ).toHaveAttribute("aria-sort", "ascending");

    const tickets = page.locator("#tickets table");
    const openedHeader = tickets.getByRole("columnheader", {
      name: /Thời gian mở/,
    });
    await expect(openedHeader).toBeVisible();
    await openedHeader.getByRole("button").click();
    await expect(openedHeader).toHaveAttribute("aria-sort", "ascending");
    const ascendingTimes = await tickets.locator("tbody time").evaluateAll(
      (nodes) => nodes.map((node) => Date.parse(node.getAttribute("datetime") ?? "")),
    );
    expect(ascendingTimes).toEqual([...ascendingTimes].sort((a, b) => a - b));

    await openedHeader.getByRole("button").click();
    await expect(openedHeader).toHaveAttribute("aria-sort", "descending");
    const descendingTimes = await tickets.locator("tbody time").evaluateAll(
      (nodes) => nodes.map((node) => Date.parse(node.getAttribute("datetime") ?? "")),
    );
    expect(descendingTimes).toEqual([...descendingTimes].sort((a, b) => b - a));
  });

  test("shows exact-source Transstatus and Step result without inferred taxonomy labels", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name !== "desktop-light",
      "source contract only needs one full browser run",
    );
    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(dashboardEnvelopeFixture),
      }),
    );

    await page.goto("/");

    const diagnostics = page.locator("#tpeDistribution");
    await expect(
      diagnostics.getByRole("heading", {
        name: "Transstatus và Step result",
      }),
    ).toBeVisible();
    await expect(diagnostics.locator("thead th")).toHaveText([
      "Transstatus",
      "Step result",
      "Ticket",
      "Tỷ lệ ticket có mã này",
    ]);
    await expect(diagnostics.getByText("-1013", { exact: true })).toBeVisible();
    await expect(
      diagnostics.getByText("Không có Step result", { exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("list", { name: "Việc cần chú ý" })).toHaveCount(0);
    await expect(page.getByText(/taxonomy|case 2|Đang xử lý/i)).toHaveCount(0);

    const transferReasons = page.locator("#guardrailDistribution");
    await expect(
      transferReasons.getByRole("heading", { name: "Lý do chuyển CS" }),
    ).toBeVisible();
    await expect(transferReasons.locator("thead th")).toHaveText([
      "Lý do chuyển CS",
      "Giá trị nguồn",
      "Nguồn phát hiện",
      "Skill",
      "Ticket",
      "Tỷ lệ",
    ]);
    const skillPath = transferReasons.getByRole("row", {
      name: /Skill đề xuất chuyển CS/,
    });
    await expect(skillPath).toContainText("cs_escalation");
    await expect(skillPath).toContainText(
      "skill_guardrail_checked · stage=output",
    );
    const outputPath = transferReasons.getByRole("row", {
      name: /Phản hồi AI được nhận diện là cần chuyển CS/,
    });
    await expect(outputPath).toContainText("cs_escalation");
    await expect(outputPath).toContainText("output_guardrail");

    const gt4 = page.getByRole("region", {
      name: /^Ticket có hơn 3 lượt xử lý/,
    });
    await expect(gt4).toBeVisible();
    await expect(
      gt4.getByRole("row", { name: /Trạng thái: Tổng/ }),
    ).toBeVisible();
    await expect(
      gt4.getByRole("row", { name: /Trạng thái: Đã chuyển CS/ }),
    ).toBeVisible();
    await expect(
      gt4.getByRole("row", { name: /Trạng thái: Chưa chuyển CS/ }),
    ).toBeVisible();
    await expect(page.locator("body")).not.toContainText(
      /rule đã bắn|khoảng trống rule|guard chặn/i,
    );
  });

  test("nav labels match their h2 in page order and land below the sticky shell", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name.endsWith("dark"),
      "anchor geometry is covered once per viewport",
    );

    await page.goto("/");
    await expect(page.locator("#weekly")).toBeVisible();

    const links = page.locator("#sectionNav a[href^='#']");
    const targets = await links.evaluateAll((nodes) =>
      nodes.map((node) => ({
        id: (node.getAttribute("href") ?? "").slice(1),
        label: node.textContent?.trim() ?? "",
      })),
    );
    const headings = await page.evaluate((ids) =>
      ids.map((id) => {
        const section = document.getElementById(id);
        const heading = document.getElementById(
          section?.getAttribute("aria-labelledby") ?? "",
        );
        return {
          text: heading?.textContent?.trim() ?? "",
          top: section?.getBoundingClientRect().top ?? Number.NaN,
        };
      }),
    targets.map((target) => target.id));

    // D17: nav label is the h2 text, and nav order is page order.
    expect(headings.map((heading) => heading.text)).toEqual(
      targets.map((target) => target.label),
    );
    const tops = headings.map((heading) => heading.top);
    expect(tops).toEqual([...tops].sort((left, right) => left - right));

    for (const { id } of targets) {
      await page.locator(`#sectionNav a[href="#${id}"]`).click();
      await expect
        .poll(() =>
          page.evaluate((targetId) => {
            const shell = document.querySelector("header");
            const section = document.getElementById(targetId);
            const heading = document.getElementById(
              section?.getAttribute("aria-labelledby") ?? "",
            );
            if (shell === null || heading === null) {
              throw new Error(`Missing shell or labelled heading for #${targetId}`);
            }
            return heading.getBoundingClientRect().top - shell.getBoundingClientRect().bottom;
          }, id),
        )
        .toBeGreaterThanOrEqual(-1);
    }
  });

  test("exposes exactly one polite live region for runtime state", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("[role='status'][aria-live='polite']")).toHaveCount(1);
  });

  test("has no serious or critical accessibility violation", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();

    const blocking = results.violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );
    expect(
      blocking.flatMap((violation) =>
        violation.nodes.map(
          (node) => `${violation.id} @ ${node.target.join(" ")} — ${node.failureSummary ?? ""}`,
        ),
      ),
    ).toEqual([]);
  });

  test("announces loading before the first snapshot exists", async ({ page }) => {
    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          status: "loading",
          refreshing: true,
          last_error_code: null,
          last_error_at: null,
          snapshot: null,
        }),
      }),
    );

    await page.goto("/");

    await expect(page.getByRole("status")).toHaveText("Đang tải dữ liệu dashboard.");
    await expect(page.getByRole("banner")).toContainText("Zalopay");
    await expect(page.locator("#weekly")).toHaveCount(0);
  });

  test("keeps the last-good report and hides the error code when a refresh fails", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const title = await page.getByRole("heading", { level: 1 }).textContent();

    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: { code: "private_upstream_timeout" } }),
      }),
    );
    await page.route("**/api/refresh", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: { code: "private_upstream_timeout" } }),
      }),
    );
    await page.getByRole("button", { name: "Làm mới" }).click();

    await expect(page.getByRole("status")).toHaveText(
      "Không thể tải dữ liệu mới. Đang hiển thị dữ liệu gần nhất.",
    );
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(title ?? "");
    await expect(page.locator("body")).not.toContainText("private_upstream_timeout");
  });

  test("refuses a malformed snapshot instead of rendering it", async ({ page }) => {
    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ready",
          refreshing: false,
          last_error_code: null,
          last_error_at: null,
          snapshot: { views: {} },
        }),
      }),
    );

    await page.goto("/");

    await expect(page.getByRole("status")).toHaveText(
      "Chưa tải được dữ liệu dashboard. Hệ thống sẽ thử lại.",
    );
    await expect(page.locator("#weekly")).toHaveCount(0);
  });

  test("serves hashed assets immutably and refuses traversal", async ({ request }) => {
    const document = await request.get("/");
    const html = await document.text();
    const asset = /\/assets\/[A-Za-z0-9._-]+\.js/.exec(html)?.[0];
    expect(asset).toBeTruthy();

    const script = await request.get(asset as string);
    expect(script.status()).toBe(200);
    expect(script.headers()["cache-control"]).toBe(
      "private, max-age=31536000, immutable",
    );

    const traversal = await request.get("/assets/%2e%2e/%2e%2e/pyproject.toml");
    expect(traversal.status()).toBe(404);
    expect(await traversal.text()).not.toContain("weekly-cs-dashboard");
  });

  test("never sends a browser payload containing an internal identifier", async ({
    request,
  }) => {
    const payload = await (await request.get("/api/dashboard")).text();

    for (const forbidden of ["traceId", "sessionId", "UserID", "TransID"]) {
      expect(payload).not.toContain(forbidden);
    }
  });
});
