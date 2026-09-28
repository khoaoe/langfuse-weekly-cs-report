import { expect, test, type Page } from "@playwright/test";

const LONG_TOOL_ERRORS = [
  "get_bank_code_by_bank_name:UNKNOWN_BANK_NAME",
  "get_bank_unlink_history:NO_DATA",
  "get_zalopay_id_by_phone:NOT_FOUND",
];

async function openDashboard(page: Page) {
  await page.route("**/api/tickets**", async (route) => {
    // A test can end while this is in flight; the disposed response is not a failure.
    try {
      const response = await route.fetch();
      const body = await response.json();
      for (const item of body?.data?.items ?? body?.items ?? []) {
        item.tool_error_codes = LONG_TOOL_ERRORS;
      }
      await route.fulfill({ response, json: body });
    } catch {
      // page closed
    }
  });
  await page.goto("/");
  await expect(page.locator("#weeklyRows tr").first()).toBeVisible();
}

test.describe("UI polish round 1", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("the shell Z mark is not clipped", async ({ page }) => {
    await openDashboard(page);
    const clipped = await page
      .locator('[data-brand-mark-container="shell-z"] img:visible')
      .evaluate((img) => {
        const box = img.getBoundingClientRect();
        const image = img as HTMLImageElement;
        const scale =
          getComputedStyle(image).objectFit === "cover"
            ? Math.max(box.width / image.naturalWidth, box.height / image.naturalHeight)
            : Math.min(box.width / image.naturalWidth, box.height / image.naturalHeight);
        if (
          image.naturalWidth * scale > box.width + 0.5 ||
          image.naturalHeight * scale > box.height + 0.5
        ) {
          return "object-fit crop";
        }
        let node = img.parentElement;
        while (node) {
          const style = getComputedStyle(node);
          if (style.overflow !== "visible" || style.overflowX !== "visible") {
            const clip = node.getBoundingClientRect();
            if (
              box.left < clip.left - 0.5 ||
              box.right > clip.right + 0.5 ||
              box.top < clip.top - 0.5 ||
              box.bottom > clip.bottom + 0.5
            ) {
              return node.className || node.tagName;
            }
          }
          node = node.parentElement;
        }
        return null;
      });
    expect(clipped).toBeNull();
  });

  test("the report scope panel sits above the section nav", async ({ page }) => {
    await openDashboard(page);
    await page.locator("summary", { hasText: "WTD" }).first().click();
    const help = page.locator("#howToReadButton");
    const box = await help.boundingBox();
    if (box === null) throw new Error("no help button");
    const onTop = await page.evaluate(
      ({ x, y }) => document.elementFromPoint(x, y)?.closest("#howToReadButton") === null,
      { x: box.x + box.width / 2, y: box.y + box.height / 2 },
    );
    expect(onTop).toBe(true);
  });

  test("weekly report headers do not overlap", async ({ page }) => {
    await openDashboard(page);
    // The label must sit inside its own cell and stay on one line.
    const overlapping = await page.locator("#weekly thead th button > span:first-child").evaluateAll((labels) =>
      labels
        .filter((label) => {
          const text = label.getBoundingClientRect();
          const cell = label.closest("th")!.getBoundingClientRect();
          return text.left < cell.left - 0.5 || text.right > cell.right + 0.5 || text.height > parseFloat(getComputedStyle(label).fontSize) * 2;
        })
        .map((label) => label.textContent?.trim()),
    );
    expect(overlapping).toEqual([]);
  });

  test("the two diagnostics toggle on their own", async ({ page }) => {
    await openDashboard(page);
    for (const id of ["#tpeDistribution", "#ruleGt4Panel"]) {
      const details = page.locator(`${id} details`).first();
      await expect(details).toHaveAttribute("open", "");
      await details.locator("summary").click();
      await expect(details).not.toHaveAttribute("open", "");
    }
    await expect(page.locator("#tpeDistribution details").first()).not.toHaveAttribute("open", "");
  });

  test("a long tool-error value does not stretch its column", async ({ page }) => {
    await openDashboard(page);
    await page.locator("#ticketColumnChooser summary").click();
    await page.locator("#columnOption-tool_error_codes").check();
    const cell = page.locator("#ticketRows td", { hasText: "UNKNOWN_BANK_NAME" }).first();
    await expect(cell).toBeVisible();
    const width = await cell.evaluate((node) => node.getBoundingClientRect().width);
    expect(width).toBeLessThanOrEqual(360);
  });

  test("table frames hug their tables instead of filling the row", async ({ page }) => {
    await openDashboard(page);
    const loose = await page.locator("#segments [role=region], #tpeDistribution [role=region], #ruleGt4Panel [role=region]").evaluateAll(
      (frames) =>
        frames
          .map((frame) => {
            const table = frame.querySelector("table");
            return table === null ? 0 : frame.clientWidth - table.getBoundingClientRect().width;
          })
          .filter((gap) => gap > 4),
    );
    expect(loose).toEqual([]);
  });
});
