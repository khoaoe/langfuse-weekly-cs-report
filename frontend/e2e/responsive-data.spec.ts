import { expect, test } from "@playwright/test";

import { dashboardEnvelopeFixture } from "../test/fixtures/dashboard";

const LONG_SAFE_INTENT =
  "check_ibft_transaction_status_by_reference_number";
const LONG_INTENT_COUNTS = {
  total: 1,
  ai_first: 1,
  transferred: 0,
  reopen: 0,
};

function dashboardWithLongIntent() {
  const base = structuredClone(dashboardEnvelopeFixture);
  const views = Object.fromEntries(
    Object.entries(base.snapshot.views).map(([cohort, view]) => [
      cohort,
      {
        ...view,
        segments: {
          ...view.segments,
          intent: {
            ...view.segments.intent,
            [LONG_SAFE_INTENT]: LONG_INTENT_COUNTS,
          },
        },
        by_week: Object.fromEntries(
          Object.entries(view.by_week).map(([week, weekView]) => [
            week,
            {
              ...weekView,
              segments: {
                ...weekView.segments,
                intent: {
                  ...weekView.segments.intent,
                  [LONG_SAFE_INTENT]: LONG_INTENT_COUNTS,
                },
              },
            },
          ]),
        ),
      },
    ]),
  );

  return {
    ...base,
    snapshot: {
      ...base.snapshot,
      views,
    },
  };
}

test("long real-world intent labels stay inside the dashboard canvas", async ({
  page,
}) => {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(dashboardWithLongIntent()),
    }),
  );

  await page.goto("/");

  const intentSelect = page.locator("#intentInput");
  await expect(intentSelect).toBeVisible();
  await expect(
    page.locator(`#intentOptions option[value="${LONG_SAFE_INTENT}"]`),
  ).toHaveCount(1);

  const layout = await intentSelect.evaluate((select) => {
    const field = select.parentElement;
    if (field === null) {
      throw new Error("Intent select must remain inside its field");
    }
    const viewportWidth = document.documentElement.clientWidth;
    const selectBox = select.getBoundingClientRect();
    const fieldBox = field.getBoundingClientRect();
    return {
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth,
      selectRight: selectBox.right,
      fieldRight: fieldBox.right,
    };
  });

  expect(layout.documentWidth).toBe(layout.viewportWidth);
  expect(layout.selectRight).toBeLessThanOrEqual(layout.fieldRight + 1);
  expect(layout.selectRight).toBeLessThanOrEqual(layout.viewportWidth + 1);
});
