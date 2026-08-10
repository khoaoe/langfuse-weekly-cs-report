import { expect, test, type Locator, type Page } from "@playwright/test";

import { dashboardEnvelopeFixture } from "../test/fixtures/dashboard";

const E2E_ORIGIN = "http://127.0.0.1:18765";

type AriaSortDirection = "ascending" | "descending";

function dashboardWithSortableRows() {
  const base = structuredClone(dashboardEnvelopeFixture);
  const views = Object.fromEntries(
    Object.entries(base.snapshot.views).map(([key, view]) => {
      const newest = view.weekly[0];
      if (newest === undefined) {
        throw new Error("Sorting fixture requires one weekly row");
      }
      const earlier = {
        ...newest,
        cohort_week: "2026-07-13",
        total_tickets: 3,
        ai_first_count: 2,
        ai_first_rate: 2 / 3,
        ai_end_to_end_count: 1,
        ai_then_cs_count: 1,
        direct_cs_count: 1,
        unclassified_count: 0,
        reopen_7d_rate: 0.5,
        reopen_7d_denominator: 2,
        reopen_lifetime_rate: 0.5,
        reopen_lifetime_numerator: 1,
        reopen_lifetime_denominator: 2,
      };
      const issueCategory = {
        "Nhóm Zeta": { total: 3, ai_first: 2, transferred: 1, reopen: 0 },
        "Nhóm Alpha": { total: 4, ai_first: 3, transferred: 1, reopen: 1 },
        "Nhóm Beta": { total: 3, ai_first: 3, transferred: 1, reopen: 1 },
      };

      return [
        key,
        {
          ...view,
          weekly: [earlier, newest],
          by_week: {
            "2026-07-13": {
              segments: {
                ...view.segments,
                issue_category: issueCategory,
              },
              transfer_reasons: view.transfer_reasons,
            },
            [newest.cohort_week]: {
              segments: {
                ...view.segments,
                issue_category: issueCategory,
              },
              transfer_reasons: view.transfer_reasons,
            },
          },
          segments: {
            ...view.segments,
            issue_category: issueCategory,
          },
        },
      ];
    }),
  );

  return {
    ...base,
    snapshot: {
      ...base.snapshot,
      data_range: {
        ...base.snapshot.data_range,
        first_week_with_data: "2026-07-13",
      },
      views,
    },
  };
}

async function useSortingDashboard(page: Page): Promise<void> {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(dashboardWithSortableRows()),
    }),
  );
}

async function ariaSort(header: Locator): Promise<AriaSortDirection> {
  const direction = await header.getAttribute("aria-sort");
  expect(["ascending", "descending"]).toContain(direction);
  return direction as AriaSortDirection;
}

async function weeklyTotals(weekly: Locator): Promise<number[]> {
  return weekly.locator("tbody tr").evaluateAll((rows) =>
    rows.map((row) => {
      const value = row.querySelector("td")?.textContent?.replace(/[^\d-]/g, "");
      if (value === undefined || value === "") {
        throw new Error("Weekly total cell must contain a number");
      }
      return Number(value);
    }),
  );
}

async function segmentLabels(segments: Locator): Promise<string[]> {
  return segments.locator("tbody th[scope='row']").evaluateAll((headers) =>
    headers.map((header) => header.textContent?.trim() ?? ""),
  );
}

async function ticketIds(tickets: Locator): Promise<number[]> {
  return tickets.locator("#ticketRows > tr > th[scope='row']").evaluateAll((headers) =>
    headers.map((header) => {
      const value = header.getAttribute("aria-label") ?? "";
      if (!/^[1-9]\d*$/.test(value)) {
        throw new Error(`Ticket row has an invalid accessible ID: ${value}`);
      }
      return Number(value);
    }),
  );
}

function expectedNumbers(
  values: readonly number[],
  direction: AriaSortDirection,
): number[] {
  return [...values].sort((left, right) =>
    direction === "ascending" ? left - right : right - left,
  );
}

test.describe("Sắp xếp bảng dữ liệu", () => {
  test("sorts the weekly report by a numeric column and exposes aria-sort", async ({
    page,
  }) => {
    await useSortingDashboard(page);
    await page.goto("/");

    const weekly = page.locator("#weekly");
    const totalHeader = weekly.getByRole("columnheader", {
      name: /Tổng ticket/,
    });
    const sortButton = totalHeader.getByRole("button", {
      name: /Sắp xếp theo Tổng ticket/,
    });

    await expect(totalHeader).toHaveAttribute("aria-sort", "none");
    await sortButton.click();

    const firstDirection = await ariaSort(totalHeader);
    const firstOrder = await weeklyTotals(weekly);
    expect(firstOrder).toEqual(expectedNumbers(firstOrder, firstDirection));

    await sortButton.click();

    const secondDirection = await ariaSort(totalHeader);
    expect(secondDirection).not.toBe(firstDirection);
    const secondOrder = await weeklyTotals(weekly);
    expect(secondOrder).toEqual(expectedNumbers(secondOrder, secondDirection));
    expect(secondOrder).toEqual([...firstOrder].reverse());
  });

  test("sorts the segment table by its visible label", async ({ page }) => {
    await useSortingDashboard(page);
    await page.goto("/");

    const segments = page.locator("#segmentList");
    const labelHeader = segments.getByRole("columnheader", { name: /Giá trị/ });
    const sortButton = labelHeader.getByRole("button", {
      name: /Sắp xếp theo Giá trị/,
    });

    await expect(labelHeader).toHaveAttribute("aria-sort", "none");
    await sortButton.click();

    const firstDirection = await ariaSort(labelHeader);
    const ascending = ["Nhóm Alpha", "Nhóm Beta", "Nhóm Zeta"];
    await expect
      .poll(() => segmentLabels(segments))
      .toEqual(firstDirection === "ascending" ? ascending : [...ascending].reverse());

    await sortButton.click();

    const secondDirection = await ariaSort(labelHeader);
    expect(secondDirection).not.toBe(firstDirection);
    await expect
      .poll(() => segmentLabels(segments))
      .toEqual(secondDirection === "ascending" ? ascending : [...ascending].reverse());
  });

  test("keeps Ticket Explorer sorting global and same-origin", async ({ page }) => {
    const thirdPartyRequests: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (!url.startsWith(E2E_ORIGIN) && !url.startsWith("data:")) {
        thirdPartyRequests.push(url);
      }
    });

    await page.goto("/");

    const tickets = page.locator("#tickets");
    await expect(tickets.locator("#ticketRows > tr").first()).toBeVisible();
    const ticketHeader = tickets.getByRole("columnheader", { name: /Ticket/ });
    const sortButton = ticketHeader.getByRole("button", {
      name: /Sắp xếp theo Ticket/,
    });

    const ascendingResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/tickets" &&
        url.searchParams.get("sort_by") === "ticket_id" &&
        url.searchParams.get("sort_direction") === "asc"
      );
    });
    await sortButton.click();
    expect((await ascendingResponse).status()).toBe(200);

    await expect(ticketHeader).toHaveAttribute("aria-sort", "ascending");
    await expect
      .poll(async () => {
        const ids = await ticketIds(tickets);
        return ids.join(",") === expectedNumbers(ids, "ascending").join(",");
      })
      .toBe(true);

    const descendingResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/tickets" &&
        url.searchParams.get("sort_by") === "ticket_id" &&
        url.searchParams.get("sort_direction") === "desc"
      );
    });
    await sortButton.click();
    expect((await descendingResponse).status()).toBe(200);

    await expect(ticketHeader).toHaveAttribute("aria-sort", "descending");
    await expect
      .poll(async () => {
        const ids = await ticketIds(tickets);
        return ids.join(",") === expectedNumbers(ids, "descending").join(",");
      })
      .toBe(true);
    expect(thirdPartyRequests).toEqual([]);
  });
});
