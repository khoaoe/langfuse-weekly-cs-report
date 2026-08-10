import { expect, test } from "@playwright/test";

import { dashboardEnvelopeFixture } from "../test/fixtures/dashboard";

const E2E_ORIGIN = "http://127.0.0.1:18765";
const FRESHDESK_TICKET_BASE_URL =
  "https://vngzalopay.freshdesk.com/a/tickets/";
const LANGFUSE_TRACES_URL =
  "https://langfuse.zalopay.vn/project/cmqubjzur000hz507ptubh2l9/traces";
const VIETNAM_OFFSET_MILLISECONDS = 7 * 60 * 60 * 1_000;

function expectedTracingDateRange(
  rangeStart: string,
  generatedAt: string,
): string {
  const start = Date.parse(`${rangeStart}T00:00:00.000+07:00`);
  const vietnamDate = new Date(
    Date.parse(generatedAt) + VIETNAM_OFFSET_MILLISECONDS,
  )
    .toISOString()
    .slice(0, 10);
  const end = Date.parse(`${vietnamDate}T23:59:59.999+07:00`);
  return `${start}-${end}`;
}

test("renders safe Freshdesk and Langfuse ticket links without requesting either service", async ({
  page,
}, testInfo) => {
  const dashboard = {
    ...structuredClone(dashboardEnvelopeFixture),
    snapshot: {
      ...structuredClone(dashboardEnvelopeFixture.snapshot),
      data_range: {
        ...dashboardEnvelopeFixture.snapshot.data_range,
        first_week_with_data: "2026-04-20",
      },
    },
  };
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(dashboard),
    }),
  );

  const thirdPartyRequests: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith(E2E_ORIGIN) && !url.startsWith("data:")) {
      thirdPartyRequests.push(url);
    }
  });

  await page.goto("/");

  const ticketRow = page
    .locator("#ticketRows tr")
    .filter({
      has: page.getByRole("link", {
        name: /Mở ticket [1-9]\d{0,19} trên Freshdesk trong thẻ mới/,
      }),
    })
    .first();
  const freshdeskLink = ticketRow.getByRole("link", {
    name: /Mở ticket [1-9]\d{0,19} trên Freshdesk trong thẻ mới/,
  });
  await expect(freshdeskLink).toBeVisible();

  const ticketId = (await freshdeskLink.textContent())?.trim() ?? "";
  expect(ticketId).toMatch(/^[1-9]\d{0,19}$/);

  await expect(ticketRow).toHaveCount(1);

  const langfuseLink = ticketRow.getByRole("link", {
    name: `Mở các trace của ticket ${ticketId} trên Langfuse trong thẻ mới`,
  });
  await expect(langfuseLink).toBeVisible();
  await expect(langfuseLink).toHaveAttribute(
    "title",
    `Mở Tracing của ticket ${ticketId} trên Langfuse`,
  );
  await expect(langfuseLink).toHaveText("");
  const langfuseIcon = langfuseLink.locator("img");
  await expect(langfuseIcon).toHaveAttribute("alt", "");
  await expect(langfuseIcon).toHaveAttribute("aria-hidden", "true");
  await expect(langfuseIcon).toHaveAttribute(
    "src",
    /\/assets\/langfuse-icon-[A-Za-z0-9_-]+\.svg$/,
  );
  const langfuseTarget = await langfuseLink.boundingBox();
  expect(langfuseTarget).not.toBeNull();
  const minimumTarget = testInfo.project.name.startsWith("mobile") ? 44 : 24;
  expect(langfuseTarget?.width).toBeGreaterThanOrEqual(minimumTarget);
  expect(langfuseTarget?.height).toBeGreaterThanOrEqual(minimumTarget);
  const langfuseFilter = encodeURIComponent(
    `sessionId;stringOptions;;any of;${ticketId}`,
  );
  const firstWeek = dashboard.snapshot.data_range.first_week_with_data;
  const tracingDateRange = expectedTracingDateRange(
    firstWeek,
    dashboard.snapshot.generated_at,
  );
  const rangeParts = tracingDateRange.split("-");
  expect(rangeParts).toHaveLength(2);
  const rangeStart = Number(rangeParts[0] ?? Number.NaN);
  const rangeEnd = Number(rangeParts[1] ?? Number.NaN);
  expect(Number.isFinite(rangeStart)).toBe(true);
  expect(Number.isFinite(rangeEnd)).toBe(true);
  expect(rangeEnd - rangeStart).toBeGreaterThan(90 * 24 * 60 * 60 * 1_000);

  for (const [link, expectedHref] of [
    [freshdeskLink, `${FRESHDESK_TICKET_BASE_URL}${ticketId}`],
    [
      langfuseLink,
      `${LANGFUSE_TRACES_URL}?filter=${langfuseFilter}&dateRange=${tracingDateRange}`,
    ],
  ] as const) {
    await expect(link).toHaveAttribute("href", expectedHref);
    await expect(link).toHaveAttribute("target", "_blank");
    const relTokens = (await link.getAttribute("rel"))?.split(/\s+/) ?? [];
    expect(relTokens).toEqual(
      expect.arrayContaining(["noopener", "noreferrer"]),
    );
  }

  expect(thirdPartyRequests).toEqual([]);
});
