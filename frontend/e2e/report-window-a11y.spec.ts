import { readFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";

/**
 * Phase-1 contract (spec 2026-09-28 §3): the report and its exports cover the
 * whole week window whatever the scope, focus never hides under the sticky
 * header, the page reflows at 1280px/200%, and headings never skip a level.
 * One colour scheme is enough for geometry and exports.
 */
test.beforeEach(async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-light", "desktop geometry, one run");
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

async function windowWeekCount(page: Page): Promise<number> {
  return page.evaluate(async () => {
    const response = await fetch("/api/dashboard");
    const body = (await response.json()) as {
      snapshot: { views: { mon_fri: { weekly: unknown[] } } };
    };
    return body.snapshot.views.mon_fri.weekly.length;
  });
}

async function exportedRowCounts(page: Page) {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#weeklyCsvButton").click(),
  ]);
  const csv = await readFile(await download.path(), "utf8");
  await page.locator("#weeklyCopyButton").click();
  await expect(page.getByText("Đã chép bảng báo cáo tuần dạng TSV.")).toBeVisible();
  const tsv = await page.evaluate(() => navigator.clipboard.readText());
  return {
    // Metadata row + header row precede the data rows.
    csv: csv.trim().split("\n").length - 2,
    // Header row precedes the data rows.
    tsv: tsv.trim().split("\n").length - 1,
  };
}

test("exports every week in the window whatever the report scope", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const weeks = await windowWeekCount(page);
  expect(weeks).toBeGreaterThan(1);

  // Default scope is the running week; the export must still be the window.
  expect(await exportedRowCounts(page)).toEqual({ csv: weeks, tsv: weeks });

  const reportScope = page.locator('summary[aria-label^="Phạm vi báo cáo:"]');
  await reportScope.click();
  await page.getByRole("button", { name: /Toàn bộ kỳ báo cáo/ }).click();
  expect(await exportedRowCounts(page)).toEqual({ csv: weeks, tsv: weeks });
});

async function focusHiddenUnderHeader(page: Page, stops: number) {
  // Geometry is only meaningful once every section has loaded; a late table
  // shifts content after focus has already scrolled.
  await page.locator("#tickets tbody tr").first().waitFor();
  await page.waitForLoadState("networkidle");
  // No `End` key: Chrome animates keyboard scrolling, and the animation keeps
  // moving the page after the focus stops below have scrolled.
  await page.evaluate(() => {
    window.scrollTo(0, document.documentElement.scrollHeight);
    (document.activeElement as HTMLElement | null)?.blur();
  });
  const hidden: string[] = [];
  for (let stop = 0; stop < stops; stop += 1) {
    await page.keyboard.press("Shift+Tab");
    const result = await page.evaluate(() => {
      const focused = document.activeElement;
      const shell = document.querySelector("header");
      if (
        !(focused instanceof HTMLElement) ||
        shell === null ||
        focused === document.body ||
        shell.contains(focused)
      ) {
        return null;
      }
      const box = focused.getBoundingClientRect();
      if (box.width === 0 && box.height === 0) {
        return null;
      }
      const shellBottom = shell.getBoundingClientRect().bottom;
      return box.top < shellBottom - 1
        ? `${focused.tagName}#${focused.id}.${focused.className} "${focused.textContent?.trim().slice(0, 40)}" in ${focused.closest("section,aside,footer")?.id} top=${Math.round(box.top)} shell=${Math.round(shellBottom)}`
        : null;
    });
    if (result !== null) {
      hidden.push(result);
    }
  }
  return hidden;
}

test("keeps Shift+Tab focus clear of the sticky header at 1280px", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  expect(await focusHiddenUnderHeader(page, 60)).toEqual([]);
});

// 1280px at 200% zoom is a 640x400 CSS viewport.
test("keeps Shift+Tab focus clear of the sticky header at 1280px/200%", async ({
  page,
}) => {
  await page.setViewportSize({ width: 640, height: 400 });
  expect(await focusHiddenUnderHeader(page, 60)).toEqual([]);
});

test("reflows without sideways page overflow at 1280px/200%", async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 400 });
  const overflowing = await page.evaluate(() => {
    const limit = document.documentElement.clientWidth;
    // Tables and the section nav own their overflow in a local scroller.
    const insideLocalScroller = (node: Element) => {
      for (let parent = node.parentElement; parent !== null && parent !== document.body; parent = parent.parentElement) {
        const overflowX = getComputedStyle(parent).overflowX;
        if (overflowX === "auto" || overflowX === "scroll") {
          return true;
        }
      }
      return false;
    };
    return Array.from(document.querySelectorAll("body *"))
      .filter((node) => {
        const rect = node.getBoundingClientRect();
        return (
          rect.width > 0 &&
          (rect.right > limit + 1 || rect.left < -1) &&
          !insideLocalScroller(node)
        );
      })
      .slice(0, 5)
      .map((node) => `${node.tagName}.${String(node.className)}`);
  });
  expect(overflowing).toEqual([]);
});

test("never skips a heading level", async ({ page }) => {
  const levels = await page.evaluate(() =>
    Array.from(
      document.querySelectorAll("h1, h2, h3, h4, h5, h6, [role='heading']"),
    )
      .filter((node) => (node as HTMLElement).offsetParent !== null)
      .map((node) =>
        node.getAttribute("role") === "heading"
          ? Number(node.getAttribute("aria-level"))
          : Number(node.tagName.slice(1)),
      ),
  );
  expect(levels[0]).toBe(1);
  const jumps = levels.flatMap((level, index) =>
    index > 0 && level > (levels[index - 1] ?? 0) + 1
      ? [`${levels[index - 1]}→${level}`]
      : [],
  );
  expect(jumps).toEqual([]);
});
