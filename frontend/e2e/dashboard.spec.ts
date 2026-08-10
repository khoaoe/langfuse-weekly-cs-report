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

function healthyEnvelopeWithoutWarnings() {
  const base = structuredClone(dashboardEnvelopeFixture);
  const views = Object.fromEntries(
    Object.entries(base.snapshot.views).map(([key, view]) => {
      const transferReasons = {
        ...view.transfer_reasons,
        step_result_missing: {
          count: 0,
          denominator: view.transfer_reasons.observed_transfer_denominator,
        },
        tpe: view.transfer_reasons.tpe.filter(
          (row) => row.step_result !== null,
        ),
      };
      const byWeek = Object.fromEntries(
        Object.entries(view.by_week).map(([week, detail]) => [
          week,
          {
            ...detail,
            transfer_reasons: {
              ...detail.transfer_reasons,
              step_result_missing: {
                count: 0,
                denominator:
                  detail.transfer_reasons.observed_transfer_denominator,
              },
              tpe: detail.transfer_reasons.tpe.filter(
                (row) => row.step_result !== null,
              ),
            },
          },
        ]),
      );
      return [
        key,
        {
        ...view,
        totals: { ...view.totals, gt4_turn_total: 0 },
        transfer_reasons: transferReasons,
        by_week: byWeek,
        rule_gt4: {
          ...view.rule_gt4,
          gt4_turn_total: 0,
          gt4_turn_with_cs: 0,
          gt4_turn_without_cs: 0,
          max_replies_rule_fired: 0,
        },
        weekly: view.weekly.map((week) => ({
          ...week,
          gt4_turn_with_cs: 0,
          gt4_turn_without_cs: 0,
          max_replies_rule_fired: 0,
        })),
        },
      ];
    }),
  );

  return {
    ...base,
    snapshot: {
      ...base.snapshot,
      views,
      coverage: {
        issue_category: 0.92,
        app: 0.91,
        tpe: 0.9,
        intent: 0.89,
        skill: 0.88,
      },
      unmapped_tpe_codes: [],
      enrichment_status: "complete",
      gate_status: {
        allowed: true,
        structural_invalid_rate: 0,
        reasons: [],
      },
    },
  };
}

function entryCoverageEnvelope() {
  const base = structuredClone(dashboardEnvelopeFixture);
  const entryCoverage = {
    source: "freshdesk" as const,
    source_start_week: "2026-07-06" as const,
    fetched_at: "2026-08-04T03:00:00Z",
    by_week: {
      "2026-07-20": {
        freshdesk_ticket_count: 4,
        ai_replied_only: 1,
        ai_replied_then_transferred: 0,
        transferred_without_ai_reply: 0,
        invoked_no_result: 1,
        not_observed_invoked: 2,
        not_observed_human_replied: 1,
        not_observed_no_human_reply: 1,
        unresolved: 0,
      },
    },
  };
  return {
    ...base,
    snapshot: {
      ...base.snapshot,
      views: {
        mon_sun: {
          ...base.snapshot.views.mon_sun,
          entry_coverage: entryCoverage,
        },
        mon_fri: {
          ...base.snapshot.views.mon_fri,
          entry_coverage: entryCoverage,
        },
      },
    },
  };
}

const CSAT_E2E_TICKETS = [
  { ticket_id: "7000001", outcome: "ai_end_to_end", skill: "interbank-fund-transfer", issue_category: "Category A", satisfaction: "positive", response_total: 4 },
  { ticket_id: "7000002", outcome: "ai_end_to_end", skill: "interbank-fund-transfer", issue_category: "Category B", satisfaction: "neutral", response_total: 4 },
  { ticket_id: "7000003", outcome: "ai_end_to_end", skill: "Nhiều skill", issue_category: "Category C", satisfaction: "negative", response_total: 4 },
  { ticket_id: "7000004", outcome: "direct_cs", skill: "Nhiều skill", issue_category: "Category D", satisfaction: "positive", response_total: 4 },
  { ticket_id: "7000005", outcome: "direct_cs", skill: "topup", issue_category: "Category E", satisfaction: "neutral", response_total: 4 },
  { ticket_id: "7000006", outcome: "ai_then_cs", skill: "topup", issue_category: "Category F", satisfaction: "negative", response_total: 3 },
] as const;

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
      text: `Nội dung phản hồi ${String.fromCharCode(65 + ticketIndex)}-${responseIndex + 1}`,
      response_number: responseIndex + 1,
      response_total: ticket.response_total,
      is_latest_for_ticket: responseIndex === ticket.response_total - 1,
    })),
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
    },
    feedback_entries: feedbackEntries,
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
        },
      ]),
      ["Chưa ghi nhận", { total: 0, ai_first: 0, transferred: 0, reopen: 0 }],
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
  }));
}

function twoObservedWeekEnvelope() {
  const base = structuredClone(dashboardEnvelopeFixture);
  const patchView = <T extends (typeof base.snapshot.views)["mon_fri"]>(
    view: T,
  ) => {
    const latest = view.weekly[0];
    const detail = view.by_week["2026-07-20"];
    if (latest === undefined || detail === undefined) {
      throw new Error("E2E fixture requires the latest observed week");
    }
    return {
      ...view,
      weekly: [
        {
          ...latest,
          cohort_week: "2026-07-13",
          cohort_status: "complete" as const,
        },
        latest,
      ],
      by_week: {
        ...view.by_week,
        "2026-07-13": structuredClone(detail),
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
      "#ledger-ai-first, #ledger-transfer, #ledger-reopen, #ledger-gt4",
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
    const csat = page.getByRole("region", { name: "Khách hài lòng tới đâu" });
    const source = csat.locator("#csat-source");
    await expect(source).toHaveText(
      /CSAT: Freshdesk · chỉ Admin CS ZaloPay · cập nhật .+ · Dữ liệu khác: Langfuse(?: · Chưa cập nhật hôm nay\.)?$/,
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
    await expect(
      page.getByRole("region", { name: "Bộ lọc đang áp dụng", exact: true }),
    ).toContainText("Kết quả: AI xử lý trọn");
    await expect(csat).toContainText("Hiển thị 1–10 / 12 nội dung phản hồi");
    await expect(csat.getByText("Nội dung phản hồi D-1")).toHaveCount(0);
    await expect(
      page.locator("#tickets").getByRole("combobox", { name: "Kết quả" }),
    ).toHaveValue("ai_end_to_end");

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
    await expect(
      page.locator("#tickets").getByRole("combobox", { name: "Skill" }),
    ).toHaveValue("Nhiều skill");
    await skillFilter.selectOption("");

    await csat.getByRole("button", { name: "Trang 3" }).click();
    await expect(csat.locator("#csat-comments li")).toHaveCount(3);
    await expect(csat).toContainText("Hiển thị 21–23 / 23 nội dung phản hồi");
    await expect(
      page.locator("#tickets").getByRole("columnheader", {
        name: /Mức độ hài lòng \(CS Agent\)/,
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

  test("shows Freshdesk entry coverage and keeps its drill-down local to the section", async ({
    page,
  }) => {
    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(entryCoverageEnvelope()),
      }),
    );
    await page.route("**/api/freshdesk-entry-coverage/tickets**", (route) => {
      const url = new URL(route.request().url());
      expect(url.searchParams.get("week_definition")).toBe("mon_fri");
      expect(url.searchParams.get("cohort_weeks")).toBe("2026-07-20");
      expect(url.searchParams.get("status")).toBe("not_observed_invoked");
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
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
      });
    });

    await page.goto("/");
    const section = page.getByRole("region", {
      name: "Độ phủ xử lý từ Freshdesk",
    });
    await expect(section).toContainText("Không thấy lần gọi CS-agent");
    await section.getByRole("button", { name: "Xem ticket" }).nth(1).click();
    await expect(section).toContainText("7043723");
    await expect(section).toContainText("Trang 1 · 1 ticket");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
    ).toBe(true);
  });

  test("keeps the CSAT table inside its own mobile scroller", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name !== "mobile-light",
      "the CSAT mobile overflow contract only needs one browser run",
    );
    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(csatDecisionEnvelope()),
      }),
    );

    await page.goto("/");
    const csat = page.getByRole("region", { name: "Khách hài lòng tới đâu" });
    await expect(csat.locator("#csat-source")).toContainText("CSAT: Freshdesk");

    const layout = await csat.evaluate((section) => {
      const localScroller = section.querySelector<HTMLElement>(
        '[class*="tableScroll"]',
      );
      return {
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
        sectionWidth: section.getBoundingClientRect().width,
        scrollerWidth: localScroller?.getBoundingClientRect().width ?? null,
        scrollerHasOverflow:
          localScroller !== null &&
          localScroller.scrollWidth > localScroller.clientWidth,
      };
    });

    expect(layout.documentWidth).toBe(layout.viewportWidth);
    expect(layout.scrollerWidth).not.toBeNull();
    expect(layout.scrollerWidth).toBeLessThanOrEqual(layout.sectionWidth + 1);
    expect(layout.scrollerHasOverflow).toBe(true);
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
    await expect(page.locator("#ledger-gt4")).toContainText("3");

    await page.getByRole("button", { name: "T2–CN" }).click();

    await expect(
      page.getByRole("heading", { level: 1, name: /T2–CN.*10 ticket/ }),
    ).toBeVisible();
    await expect(page.locator("#ledger-ai-first")).toContainText(
      /AI First\s*8\s*80,0% trong 10 ticket tuần này/,
    );
    await expect(page.locator("#ledger-transfer")).toContainText("3");
    await expect(page.locator("#ledger-reopen")).toContainText("2");
    await expect(page.locator("#ledger-gt4")).toContainText("2");
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
      .locator("#ledger-gt4")
      .evaluate((node) => node.getBoundingClientRect().bottom);

    expect(bottom).toBeLessThanOrEqual(900);
  });

  test("places the weekly report directly after the decision state on mobile", async ({
    page,
  }, testInfo) => {
    test.skip(!testInfo.project.name.startsWith("mobile"), "mobile layout rule");

    await page.goto("/");
    await expect(page.locator("#weekly")).toBeVisible();
    const attentionRail = page.getByRole("list", { name: "Việc cần chú ý" });
    if ((await attentionRail.count()) > 0) {
      await attentionRail.evaluate((node) => {
        node.setAttribute("hidden", "");
      });
    }
    const mobileDecisionLayout = await page.evaluate(() => {
      const decision = document.querySelector("main > section");
      const weekly = document.getElementById("weekly");
      if (decision === null || weekly === null) {
        throw new Error("Missing decision or weekly section");
      }
      return {
        decisionBottom: decision.getBoundingClientRect().bottom,
        weeklyTop: weekly.getBoundingClientRect().top,
      };
    });

    expect(mobileDecisionLayout.weeklyTop).toBeGreaterThanOrEqual(
      mobileDecisionLayout.decisionBottom,
    );
    expect(
      mobileDecisionLayout.weeklyTop - mobileDecisionLayout.decisionBottom,
    ).toBeLessThanOrEqual(64);
  });

  test("does not render the removed action-warning rail", async ({
    page,
  }, testInfo) => {
    test.skip(!testInfo.project.name.startsWith("mobile"), "mobile layout rule");
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

  test("keeps a healthy mobile decision state before the weekly report", async ({
    page,
  }, testInfo) => {
    test.skip(!testInfo.project.name.startsWith("mobile"), "mobile layout rule");
    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(healthyEnvelopeWithoutWarnings()),
      }),
    );

    await page.goto("/");

    await expect(page.getByRole("list", { name: "Việc cần chú ý" })).toHaveCount(0);
    const layout = await page.evaluate(() => {
      const decision = document.querySelector("main > section");
      const weekly = document.getElementById("weekly");
      if (decision === null || weekly === null) {
        throw new Error("Missing decision or weekly section");
      }
      return {
        decisionBottom: decision.getBoundingClientRect().bottom,
        weeklyTop: weekly.getBoundingClientRect().top,
      };
    });
    expect(layout.weeklyTop).toBeGreaterThanOrEqual(layout.decisionBottom);
    expect(layout.weeklyTop - layout.decisionBottom).toBeLessThanOrEqual(64);
  });

  test("shows exactly the six decision columns at the 768px boundary", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name !== "desktop-light",
      "the breakpoint geometry only needs one color-scheme run",
    );

    await page.setViewportSize({ width: 768, height: 900 });
    await page.goto("/");

    await expect(page.getByRole("button", { name: "Xem đủ cột" })).toBeVisible();
    const visibleHeaders = await page.locator("#weekly thead th").evaluateAll((headers) =>
      headers
        .filter((header) => {
          const box = header.getBoundingClientRect();
          return (
            getComputedStyle(header).display !== "none" &&
            box.width > 0 &&
            box.height > 0
          );
        })
        .map((header) => header.textContent?.trim() ?? ""),
    );

    expect(visibleHeaders).toEqual([
      "Tuần",
      "Tổng ticket",
      "AI First",
      "Tỷ lệ AI First",
      "Chuyển CS ngay từ đầu",
      "Tổng chuyển CS",
    ]);

    await page.getByRole("button", { name: "Xem đủ cột" }).click();
    const expandedHeaders = await page.locator("#weekly thead [scope='col']").evaluateAll(
      (headers) =>
        headers.filter((header) => {
          const box = header.getBoundingClientRect();
          return getComputedStyle(header).display !== "none" && box.width > 0;
        }).length,
    );
    expect(expandedHeaders).toBe(13);

    const localOverflow = await page.locator("#weekly [role='region']").evaluate(
      (node) => ({
        scrollWidth: node.scrollWidth,
        clientWidth: node.clientWidth,
        pageWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
      }),
    );
    expect(localOverflow.scrollWidth).toBeGreaterThan(localOverflow.clientWidth);
    expect(localOverflow.pageWidth).toBe(localOverflow.viewportWidth);
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
      segment.getByRole("columnheader", { name: /Ticket/ }),
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
    await diagnostics.locator("summary").click();
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
    await expect(diagnostics).toContainText(
      "1/3 ticket chuyển CS (33,3%) không có Step result. Các ca này hiện chưa truy được tới bước lỗi cụ thể.",
    );
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
      name: "Ticket có hơn 4 lượt xử lý",
      exact: true,
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

  test("gives every interactive control a 44px touch target on mobile", async ({
    page,
  }, testInfo) => {
    test.skip(!testInfo.project.name.startsWith("mobile"), "mobile target rule");

    await page.goto("/");
    await expect(page.locator("#weekly")).toBeVisible();
    const shellHeight = await page
      .getByRole("banner")
      .evaluate((node) => node.getBoundingClientRect().height);
    expect(shellHeight).toBeLessThanOrEqual(245);

    const undersized = await page.evaluate(() => {
      const selector =
        "button, a[href], select, input:not([type='hidden']), summary, [role='tab'], [role='button']:not(button):not([aria-hidden='true'])";
      return Array.from(document.querySelectorAll(selector))
        .filter((node) => {
          const hitTarget =
            node.matches("input[type='checkbox'], input[type='radio']")
              ? node.closest("label") ?? node
              : node;
          const rect = hitTarget.getBoundingClientRect();
          return (
            rect.width > 0 &&
            rect.height > 0 &&
            (rect.width < 44 || rect.height < 44)
          );
        })
        .map((node) => {
          const hitTarget =
            node.matches("input[type='checkbox'], input[type='radio']")
              ? node.closest("label") ?? node
              : node;
          const rect = hitTarget.getBoundingClientRect();
          const label =
            node.getAttribute("aria-label") ??
            node.textContent?.trim().slice(0, 24) ??
            "";
          return `${node.tagName}:${label} (${rect.width.toFixed(1)}×${rect.height.toFixed(
            1,
          )})`;
        });
    });

    expect(undersized).toEqual([]);
  });

  test("bounds active filters and the reading guide outside the mobile sticky flow", async ({
    page,
  }, testInfo) => {
    test.skip(!testInfo.project.name.startsWith("mobile"), "mobile shell rule");

    await page.goto("/");
    await page
      .locator("#tickets")
      .getByRole("combobox", { name: "Kết quả" })
      .selectOption("ai_end_to_end");

    const chips = page.getByRole("region", {
      name: "Bộ lọc đang áp dụng",
      exact: true,
    });
    await expect(chips).toBeVisible();
    await chips.evaluate((region) => {
      const template = region.firstElementChild;
      if (template === null) {
        throw new Error("Missing active-filter chip");
      }
      for (let index = 1; index < 12; index += 1) {
        region.append(template.cloneNode(true));
      }
    });

    const chipLayout = await chips.evaluate((region) => {
      const style = getComputedStyle(region);
      region.scrollLeft = region.scrollWidth;
      return {
        flexWrap: style.flexWrap,
        overflowX: style.overflowX,
        clientHeight: region.clientHeight,
        scrollHeight: region.scrollHeight,
        clientWidth: region.clientWidth,
        scrollWidth: region.scrollWidth,
        scrollLeft: region.scrollLeft,
      };
    });
    expect(chipLayout.flexWrap).toBe("nowrap");
    expect(chipLayout.overflowX).toBe("auto");
    expect(chipLayout.scrollHeight).toBe(chipLayout.clientHeight);
    expect(chipLayout.scrollWidth).toBeGreaterThan(chipLayout.clientWidth);
    expect(chipLayout.scrollLeft).toBeGreaterThan(0);
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth >
          document.documentElement.clientWidth,
      ),
    ).toBe(false);

    const shell = page.getByRole("banner");
    const shellHeightBefore = await shell.evaluate(
      (node) => node.getBoundingClientRect().height,
    );
    expect(shellHeightBefore).toBeLessThanOrEqual(310);
    expect(
      await page.locator("#sectionNav").evaluate(
        (node) => getComputedStyle(node).maskImage,
      ),
    ).toContain("linear-gradient");
    await page.getByRole("button", { name: "Cách đọc" }).click();

    const guide = page.getByRole("region", { name: "Cách đọc dashboard" });
    await expect(guide).toBeFocused();
    const guideLayout = await guide.evaluate((node) => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return {
        position: style.position,
        overflowY: style.overflowY,
        height: rect.height,
      };
    });
    const shellHeightAfter = await shell.evaluate(
      (node) => node.getBoundingClientRect().height,
    );
    expect(shellHeightAfter).toBeCloseTo(shellHeightBefore, 0);
    expect(guideLayout.position).toBe("absolute");
    expect(guideLayout.overflowY).toBe("auto");
    expect(guideLayout.height).toBeLessThanOrEqual(844 * 0.45 + 1);
  });

  test("keeps chart overflow local and the global report scope touch-safe on mobile", async ({
    page,
  }, testInfo) => {
    test.skip(!testInfo.project.name.startsWith("mobile"), "mobile chart rule");

    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(twoObservedWeekEnvelope()),
      }),
    );
    await page.goto("/");

    const chartRegions = page.getByRole("region", {
      name: /Biểu đồ (volume|tỷ lệ), cuộn ngang khi cần/,
    });
    await expect(chartRegions).toHaveCount(2);

    const chartMeasurements = await chartRegions.evaluateAll((regions) =>
      regions.map((region) => {
        region.scrollLeft = region.scrollWidth;
        return {
          clientWidth: region.clientWidth,
          scrollWidth: region.scrollWidth,
          scrollLeft: region.scrollLeft,
        };
      }),
    );
    for (const measurement of chartMeasurements) {
      expect(measurement.scrollWidth).toBeGreaterThan(measurement.clientWidth);
      expect(measurement.scrollLeft).toBeGreaterThan(0);
    }

    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth >
          document.documentElement.clientWidth,
      ),
    ).toBe(false);

    const reportScope = page.locator(
      'summary[aria-label^="Phạm vi báo cáo:"]',
    );
    await expect(reportScope).toBeVisible();
    const reportScopeBox = await reportScope.boundingBox();
    expect(reportScopeBox).not.toBeNull();
    expect(reportScopeBox?.width ?? 0).toBeGreaterThanOrEqual(44);
    expect(reportScopeBox?.height ?? 0).toBeGreaterThanOrEqual(44);

    await reportScope.click();
    const scopeOptions = page.getByRole("group", {
      name: "Chọn tuần cho báo cáo",
    });
    await expect(scopeOptions.getByRole("checkbox")).toHaveCount(2);
    await scopeOptions.getByRole("checkbox", { name: "13/07–17/07" }).check();
    await expect(reportScope).toHaveAccessibleName(
      "Phạm vi báo cáo: 2 tuần đã chọn",
    );
    await expect(page.locator("#cohortWeekInput")).toHaveValue("__multiple__");

    await page.locator("#cohortWeekInput").selectOption("2026-07-13");
    await expect(page.locator("#cohortWeekInput")).toHaveValue("2026-07-13");
    await expect(reportScope).toHaveAccessibleName(
      "Phạm vi báo cáo: 2 tuần đã chọn",
    );

    await scopeOptions
      .getByRole("button", { name: "Toàn bộ kỳ báo cáo (2 tuần)" })
      .click();
    await expect(page.locator("#cohortWeekInput")).toHaveValue("");
  });

  test("keeps nav target headings below the sticky shell", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name.endsWith("dark"),
      "anchor geometry is covered once per viewport",
    );

    await page.goto("/");
    await expect(page.locator("#weekly")).toBeVisible();

    for (const sectionId of [
      "weekly",
      "trend",
      "segments",
      "diagnostics",
      "quality",
      "tickets",
    ]) {
      await page.locator(`#sectionNav a[href="#${sectionId}"]`).click();
      await expect(page).toHaveURL(new RegExp(`#${sectionId}$`));

      await expect
        .poll(() =>
          page.evaluate((targetId) => {
            const shell = document.querySelector("header");
            const section = document.getElementById(targetId);
            const headingId = section?.getAttribute("aria-labelledby");
            const heading =
              headingId === null || headingId === undefined
                ? null
                : document.getElementById(headingId);
            if (shell === null || heading === null) {
              throw new Error(`Missing shell or labelled heading for #${targetId}`);
            }
            return heading.getBoundingClientRect().top - shell.getBoundingClientRect().bottom;
          }, sectionId),
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
