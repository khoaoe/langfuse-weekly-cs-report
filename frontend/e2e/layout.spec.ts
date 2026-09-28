import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/** Phase 3 layout contract (spec 2026-09-28 §5, D13/D15/D17). Desktop only. */

test("shows the first weekly row above the fold at 1280×800", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-light", "geometry, one run");
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");

  const firstRow = page.locator("#weekly tbody tr").first();
  await expect(firstRow).toBeVisible();
  const bottom = await firstRow.evaluate((row) => row.getBoundingClientRect().bottom);
  expect(bottom).toBeLessThanOrEqual(800);
});

test("fits all 19 weekly columns at 1920 with a sticky week column", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-light", "geometry, one run");
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/");

  const table = page.locator("#weekly table");
  await expect(table).toBeVisible();
  const layout = await table.evaluate((node) => {
    const scroller = node.parentElement as HTMLElement;
    const lastHeaderRow = node.querySelectorAll("thead tr");
    const columns = lastHeaderRow[lastHeaderRow.length - 1]?.querySelectorAll("th") ?? [];
    const weekCell = node.querySelector("tbody th");
    return {
      columns: columns.length,
      overflow: scroller.scrollWidth - scroller.clientWidth,
      weekPosition: weekCell === null ? "" : getComputedStyle(weekCell).position,
    };
  });
  expect(layout.columns).toBe(19);
  expect(layout.overflow).toBeLessThanOrEqual(1);
  expect(layout.weekPosition).toBe("sticky");
});

test("places the two trend charts side by side from 1200px", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-light", "geometry, one run");
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");

  const charts = page.locator("#trend figure");
  await expect(charts).toHaveCount(2);
  const [left, right] = await charts.evaluateAll((nodes) =>
    nodes.map((node) => node.getBoundingClientRect()),
  );
  expect(Math.round(left!.top)).toBe(Math.round(right!.top));
  expect(right!.left).toBeGreaterThan(left!.right - 1);
});

for (const width of [1280, 1440, 1920]) {
  test(`has no serious axe violations at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.locator("#weekly tbody tr").first()).toBeVisible();
    await page.locator("#tickets tbody tr").first().waitFor();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(
      results.violations.map((violation) => `${violation.id}: ${violation.nodes.length}`),
    ).toEqual([]);
  });
}
